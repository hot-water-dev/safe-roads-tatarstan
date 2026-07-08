import sqlite3  # Работа с базой данных SQLite
import pandas as pd  # Работа с таблицами, почти как Excel
import os  # Для чтения переменных окружения
import requests  # Для HTTP-запросов к GigaChat
import uuid  # Для генерации уникальных ID запросов (нужно для GigaChat)
import urllib3  # Для отключения SSL-предупреждений
from dotenv import load_dotenv  # Загрузка .env файла

from sklearn.cluster import DBSCAN  # Алгоритм кластеризации (поиск очагов аварийности)
from sklearn.preprocessing import StandardScaler  # Приведение данных к одному масштабу
from fastapi import FastAPI, Query  # Создание API (сервер, который отдаёт данные)
from fastapi.middleware.cors import CORSMiddleware  # Разрешение фронтенду (React) обращаться к API
from typing import Optional  # Показывает, что параметр может быть пуст

# Загружаем переменные окружения из .env файла
load_dotenv()

# ============================================================
# НАСТРОЙКИ
# ============================================================
DB_NAME = 'accidents.db'  # Имя нашей базы данных
GIGACHAT_AUTH_KEY = os.getenv("GIGACHAT_AUTH_KEY")  # Ключ авторизации GigaChat (Base64)

# Радиусы кластеризации в градусах (примерно)
EPS_CITY = 0.005  # ~500 метров для городских дорог (местного значения)
EPS_HIGHWAY = 0.01  # ~1 км для трасс (региональных и федеральных)

app = FastAPI(title="Анализ аварийности РТ", version="1.0.0")  # Создаём сервер 'app', наполним метаданные

# Разрешаем фронтенду (React) обращаться к нашему API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Разрешаем запросы с любых сайтов
    allow_credentials=True,  # Разрешаем передачу cookies
    allow_methods=["*"],  # Разрешаем любые HTTP-методы
    allow_headers=["*"],  # Разрешаем любые заголовки
)


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================
def get_db():
    """Подключение к БД с настройкой возврата строк как словарей"""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def load_accidents_data(conn, month: Optional[str] = None):
    """Загрузить данные о ДТП из БД с опциональной фильтрацией по месяцу"""
    query = """
        SELECT id, emtp_number, date, time, district, dtp_type, 
               killed, injured, latitude, longitude, road_name, road_category, lighting
        FROM accidents 
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
        AND latitude != 0 AND longitude != 0
    """
    params = []

    if month:  # Если передан фильтр по месяцу
        query += " AND SUBSTR(date, 4, 7) = ?"  # Фильтр по месяцу
        params = [month[5:7] + "." + month[:4]]  # Преобразуем "2026-05" в "05.2026"

    return pd.read_sql_query(query, conn, params=params)


def classify_road_type(road_category: str) -> str:
    """
    Определить тип дороги по полю road_category.
    - "Местного значения" → городская дорога (eps ~500м)
    - "Региональная" или "Федеральная" → трасса (eps ~1км)
    """
    if pd.isna(road_category):  # Если поле пустое — считаем городской
        return 'city'

    category_lower = str(road_category).lower()  # Приводим к нижнему регистру

    # Если в названии есть "местного" — это городская/сельская дорога
    if 'местного' in category_lower:
        return 'city'

    # Всё остальное (региональная, федеральная) — трасса
    return 'highway'


def clusterize_data(df, eps_city=EPS_CITY, eps_highway=EPS_HIGHWAY, min_samples=3):
    """
    Кластеризовать данные с помощью DBSCAN с адаптивным радиусом.
    Городские дороги (местного значения): eps_city (~500м)
    Трассы (региональные и федеральные): eps_highway (~1км)
    """
    # Определяем тип дороги по полю road_category для каждого ДТП
    df['road_type'] = df['road_category'].apply(classify_road_type)

    # Разделяем данные на городские и трассы
    city_data = df[df['road_type'] == 'city'].copy()  # Городские дороги
    highway_data = df[df['road_type'] == 'highway'].copy()  # Трассы

    # Инициализируем колонку cluster (по умолчанию — шум)
    df['cluster'] = -1

    # Кластеризуем городские дороги (меньший радиус — плотнее кластеры)
    if len(city_data) >= min_samples:
        coords_city = city_data[['latitude', 'longitude']].values  # Извлекаем координаты
        scaler_city = StandardScaler()  # Создаём нормализатор
        coords_city_scaled = scaler_city.fit_transform(coords_city)  # Нормализуем

        clustering_city = DBSCAN(eps=eps_city, min_samples=min_samples)  # Радиус ~500м
        city_clusters = clustering_city.fit_predict(coords_city_scaled)  # Кластеризуем

        city_data['cluster'] = city_clusters  # Присваиваем кластеры (0, 1, 2, ...)

    # Кластеризуем трассы (больший радиус — разреженнее кластеры)
    if len(highway_data) >= min_samples:
        coords_highway = highway_data[['latitude', 'longitude']].values  # Извлекаем координаты
        scaler_highway = StandardScaler()  # Создаём нормализатор
        coords_highway_scaled = scaler_highway.fit_transform(coords_highway)  # Нормализуем

        clustering_highway = DBSCAN(eps=eps_highway, min_samples=min_samples)  # Радиус ~1км
        highway_clusters = clustering_highway.fit_predict(coords_highway_scaled)  # Кластеризуем

        # Сдвигаем ID на 1000, чтобы не конфликтовать с городскими кластерами
        highway_data['cluster'] = highway_clusters + 1000

    # Объединяем результаты обратно в основной DataFrame
    df.loc[city_data.index, 'cluster'] = city_data['cluster']
    df.loc[highway_data.index, 'cluster'] = highway_data['cluster']

    return df


def analyze_lighting(lighting_data):
    """
    Анализ освещённости в кластере.
    Возвращает словарь со статистикой:
    - main_lighting: преобладающее освещение
    - night_pct: процент ночных ДТП
    - day_pct: процент дневных ДТП
    - lighting_stats: полная статистика по типам освещения
    """
    result = {
        "main_lighting": "Неизвестно",
        "night_pct": 0,
        "day_pct": 0,
        "lighting_stats": {}
    }

    if len(lighting_data) == 0:
        return result

    # Считаем статистику по каждому типу освещения
    lighting_counts = lighting_data.value_counts()
    result["lighting_stats"] = {k: int(v) for k, v in lighting_counts.items()}
    result["main_lighting"] = lighting_counts.index[0]

    # Считаем ночные ДТП (темное время или сумерки)
    night_count = sum(1 for l in lighting_data if 'темное' in l.lower() or 'сумерки' in l.lower())
    result["night_pct"] = round(night_count / len(lighting_data) * 100)

    # Считаем дневные ДТП (светлое время)
    day_count = sum(1 for l in lighting_data if 'светлое' in l.lower())
    result["day_pct"] = round(day_count / len(lighting_data) * 100)

    return result


def get_road_type_label(cluster_data) -> str:
    """Определить преобладающий тип дороги в кластере для отображения"""
    if 'road_type' not in cluster_data.columns:
        return 'Неизвестно'

    road_types = cluster_data['road_type'].value_counts()  # Считаем частоту типов
    main_road_type = road_types.index[0] if len(road_types) > 0 else 'city'
    return 'Трасса' if main_road_type == 'highway' else 'Городская дорога'


def get_gigachat_token():
    """Получить токен доступа к GigaChat через OAuth"""
    if not GIGACHAT_AUTH_KEY:
        return None, "GIGACHAT_AUTH_KEY не найден в .env файле"

    try:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        token_response = requests.post(
            "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "Authorization": f"Basic {GIGACHAT_AUTH_KEY}",
                "RqUID": str(uuid.uuid4())  # Уникальный ID запроса (обязательно UUID!)
            },
            data={"scope": "GIGACHAT_API_PERS"},
            verify=False,
            timeout=10
        )

        if token_response.status_code != 200:
            return None, f"Ошибка получения токена: {token_response.status_code}"

        return token_response.json().get("access_token"), None

    except Exception as e:
        return None, str(e)


def get_cluster_data(cluster_id: int):
    """Получить данные кластера по его ID (загрузка + кластеризация + фильтрация)"""
    conn = get_db()
    df = load_accidents_data(conn)
    conn.close()

    df = clusterize_data(df)  # Кластеризуем с адаптивным радиусом
    cluster_data = df[df['cluster'] == cluster_id]

    return cluster_data if len(cluster_data) > 0 else None


# ============================================================
# ЭНДПОИНТ 1: Получить все ДТП
# ============================================================
@app.get("/api/accidents")
def get_accidents(
        district: Optional[str] = Query(None, description="Район"),
        dtp_type: Optional[str] = Query(None, description="Тип ДТП"),
        month: Optional[str] = Query(None, description="Месяц (YYYY-MM)"),
        min_killed: Optional[int] = Query(None, description="Мин. погибших"),
        limit: int = Query(500, description="Максимум записей")
):
    """Получить список ДТП с фильтрами"""
    conn = get_db()

    query = "SELECT * FROM accidents WHERE 1=1"  # WHERE 1=1 — хак для удобного добавления условий через AND
    params = []

    if district:
        query += " AND district = ?"
        params.append(district)
    if dtp_type:
        query += " AND dtp_type = ?"
        params.append(dtp_type)
    if month:
        query += " AND SUBSTR(date, 4, 7) = ?"
        params.append(month[5:7] + "." + month[:4])  # "2026-05" → "05.2026"
    if min_killed is not None:
        query += " AND killed >= ?"
        params.append(min_killed)

    query += f" LIMIT {limit}"

    rows = conn.execute(query, params).fetchall()
    conn.close()

    return [dict(row) for row in rows]


# ============================================================
# ЭНДПОИНТ 2: Получить кластеры (очаги аварийности)
# ============================================================
@app.get("/api/clusters")
def get_clusters(
        min_samples: int = Query(3, description="Мин. ДТП для образования кластера"),
        month: Optional[str] = Query(None, description="Фильтр по месяцу (YYYY-MM)")
):
    """Автоматический поиск очагов аварийности через DBSCAN с адаптивным радиусом"""
    conn = get_db()
    df = load_accidents_data(conn, month)
    conn.close()

    if len(df) < min_samples:
        return {"clusters": [], "noise_count": len(df), "total": len(df)}

    # Кластеризуем с адаптивным радиусом (город: 500м, трасса: 1км)
    df = clusterize_data(df, eps_city=EPS_CITY, eps_highway=EPS_HIGHWAY, min_samples=min_samples)

    clusters = []
    noise_count = len(df[df['cluster'] == -1])

    # Цветовая схема для уровней опасности
    color_map = {
        "critical": "red",
        "high": "orange",
        "medium": "yellow",
        "low": "green"
    }

    for cluster_id in sorted(df['cluster'].unique()):
        if cluster_id == -1:  # Пропускаем "шум" — одиночные ДТП
            continue

        cluster_data = df[df['cluster'] == cluster_id]

        # Основная статистика
        total_killed = int(cluster_data['killed'].sum())
        total_injured = int(cluster_data['injured'].sum())
        total_participants = len(cluster_data)

        # Преобладающий тип ДТП
        dtp_type_counts = cluster_data['dtp_type'].value_counts()
        main_dtp_type = dtp_type_counts.index[0] if len(dtp_type_counts) > 0 else "Неизвестно"
        main_dtp_pct = round(dtp_type_counts.iloc[0] / total_participants * 100) if total_participants > 0 else 0

        # Преобладающий район
        district_counts = cluster_data['district'].value_counts()
        main_district = district_counts.index[0] if len(district_counts) > 0 else "Неизвестно"

        # Тип дороги в кластере (городская или трасса)
        road_type_label = get_road_type_label(cluster_data)

        # Уровень опасности
        if total_killed > 0:
            danger_level = "critical"
        elif total_injured >= 5:
            danger_level = "high"
        elif total_injured >= 2:
            danger_level = "medium"
        else:
            danger_level = "low"

        # Определение центра кластера (ближайшая реальная точка ДТП)
        mean_lat = cluster_data['latitude'].mean()
        mean_lon = cluster_data['longitude'].mean()

        cluster_data_copy = cluster_data.copy()
        cluster_data_copy['distance_to_center'] = (
            (cluster_data_copy['latitude'] - mean_lat) ** 2 +
            (cluster_data_copy['longitude'] - mean_lon) ** 2
        ) ** 0.5

        closest_accident = cluster_data_copy.loc[cluster_data_copy['distance_to_center'].idxmin()]
        center_lat = float(closest_accident['latitude'])
        center_lon = float(closest_accident['longitude'])

        # Анализ освещённости (используем вспомогательную функцию)
        lighting_data = cluster_data['lighting'].dropna()
        lighting_info = analyze_lighting(lighting_data)

        clusters.append({
            "id": int(cluster_id),
            "center_lat": round(center_lat, 6),
            "center_lon": round(center_lon, 6),
            "accidents_count": total_participants,
            "killed_total": total_killed,
            "injured_total": total_injured,
            "main_dtp_type": main_dtp_type,
            "main_dtp_pct": main_dtp_pct,
            "main_district": main_district,
            "danger_level": danger_level,
            "color": color_map[danger_level],
            "main_lighting": lighting_info["main_lighting"],
            "night_pct": lighting_info["night_pct"],
            "road_type": road_type_label,  # Добавили тип дороги
            "accidents": [
                {
                    "id": int(row['id']),
                    "emtp_number": row['emtp_number'],
                    "date": row['date'],
                    "time": row['time'],
                    "dtp_type": row['dtp_type'],
                    "killed": row['killed'],
                    "injured": row['injured'],
                    "latitude": row['latitude'],
                    "longitude": row['longitude']
                }
                for _, row in cluster_data.iterrows()
            ]
        })

    # Сортируем по опасности (погибшие > раненые > количество)
    clusters.sort(key=lambda x: (x['killed_total'], x['injured_total'], x['accidents_count']), reverse=True)

    return {
        "clusters": clusters,
        "total_clusters": len(clusters),
        "noise_count": noise_count,
        "total_accidents": len(df),
        "eps_city": EPS_CITY,  # Возвращаем параметры для отладки
        "eps_highway": EPS_HIGHWAY,
        "min_samples_used": min_samples
    }


# ============================================================
# ЭНДПОИНТ 3: Общая статистика
# ============================================================
@app.get("/api/stats")
def get_stats():
    """Общая статистика по всем ДТП"""
    conn = get_db()

    total = conn.execute("SELECT COUNT(*) FROM accidents").fetchone()[0]
    total_killed = conn.execute("SELECT SUM(killed) FROM accidents").fetchone()[0] or 0
    total_injured = conn.execute("SELECT SUM(injured) FROM accidents").fetchone()[0] or 0

    districts = conn.execute("""
        SELECT district, COUNT(*) as cnt, SUM(killed) as killed, SUM(injured) as injured
        FROM accidents GROUP BY district ORDER BY killed DESC, cnt DESC LIMIT 10
    """).fetchall()

    types = conn.execute("""
        SELECT dtp_type, COUNT(*) as cnt, SUM(killed) as killed
        FROM accidents GROUP BY dtp_type ORDER BY killed DESC, cnt DESC LIMIT 10
    """).fetchall()

    months = conn.execute("""
        SELECT SUBSTR(date, 4, 7) as month, COUNT(*) as cnt, SUM(killed) as killed
        FROM accidents GROUP BY month ORDER BY month
    """).fetchall()

    conn.close()

    return {
        "total_accidents": total,
        "total_killed": int(total_killed),
        "total_injured": int(total_injured),
        "top_districts": [dict(d) for d in districts],
        "top_types": [dict(t) for t in types],
        "monthly": [dict(m) for m in months]
    }


# ============================================================
# ЭНДПОИНТ 4: Детали конкретного кластера
# ============================================================
@app.get("/api/cluster/{cluster_id}")
def get_cluster_detail(cluster_id: int):
    """Получить детальную информацию о конкретном кластере"""
    cluster_data = get_cluster_data(cluster_id)

    if cluster_data is None:
        return {"error": "Кластер не найден"}

    # Анализ освещённости (используем вспомогательную функцию)
    lighting_data = cluster_data['lighting'].dropna()
    lighting_info = analyze_lighting(lighting_data)

    # Тип дороги в кластере
    road_type_label = get_road_type_label(cluster_data)

    return {
        "cluster_id": cluster_id,
        "accidents_count": len(cluster_data),
        "killed_total": int(cluster_data['killed'].sum()),
        "injured_total": int(cluster_data['injured'].sum()),
        "main_lighting": lighting_info["main_lighting"],
        "night_pct": lighting_info["night_pct"],
        "road_type": road_type_label,  # Добавили тип дороги
        "accidents": [dict(row) for _, row in cluster_data.iterrows()]
    }


# ============================================================
# ЭНДПОИНТ 5: Получить рекомендации ИИ для кластера (GigaChat)
# ============================================================
@app.get("/api/recommendation/{cluster_id}")
def get_recommendation(cluster_id: int):
    """Получить рекомендации по снижению аварийности с помощью GigaChat"""
    cluster_data = get_cluster_data(cluster_id)

    if cluster_data is None:
        return {"error": "Кластер не найден"}

    # Собираем статистику
    total_killed = int(cluster_data['killed'].sum())
    total_injured = int(cluster_data['injured'].sum())
    total_accidents = len(cluster_data)

    dtp_type_counts = cluster_data['dtp_type'].value_counts()
    main_dtp_type = dtp_type_counts.index[0] if len(dtp_type_counts) > 0 else "Неизвестно"

    district_counts = cluster_data['district'].value_counts()
    main_district = district_counts.index[0] if len(district_counts) > 0 else "Неизвестно"

    # Тип дороги в кластере
    road_type_label = get_road_type_label(cluster_data)

    # Анализ освещённости (используем вспомогательную функцию)
    lighting_data = cluster_data['lighting'].dropna()
    lighting_info = analyze_lighting(lighting_data)

    # Формируем строки для промпта
    lighting_details = ", ".join([f"{k}: {v}" for k, v in lighting_info["lighting_stats"].items()]) or "Нет данных"

    if len(dtp_type_counts) > 0:
        top_dtp_list = list(dtp_type_counts.items())[:3]
        top_dtp_types = ", ".join([f"{k}: {v}" for k, v in top_dtp_list])
    else:
        top_dtp_types = "Нет данных"

    prompt = f"""Ты — эксперт по безопасности дорожного движения в России. 
Проанализируй данные об очаге аварийности и дай конкретные рекомендации по снижению аварийности и смертности.

ДАННЫЕ ОЧАГА:
- Местоположение: {main_district}
- Тип дороги: {road_type_label}
- Всего ДТП: {total_accidents}
- Погибло: {total_killed}
- Ранено: {total_injured}
- Преобладающий тип ДТП: {main_dtp_type}
- Распределение по типам ДТП (топ-3): {top_dtp_types}
- Преобладающее освещение: {lighting_info["main_lighting"]}
- Полная статистика по освещению: {lighting_details}
- Процент дневных ДТП (светлое время): {lighting_info["day_pct"]}%
- Процент ночных ДТП (темное время + сумерки): {lighting_info["night_pct"]}%

Задача:
1. Дай краткий анализ ситуации (2-3 предложения) — учти ВСЕ факторы: тип дороги, тип ДТП, освещение, тяжесть последствий
2. Предложи 3-5 конкретных рекомендаций по снижению аварийности
3. Если это трасса — предложи меры для загородных дорог (отбойники, освещение, патрулирование)
4. Если это городская дорога — предложи меры для городских улиц (переходы, лежачие полицейские, камеры)
5. Если есть погибшие — выдели меры по предотвращению смертности
6. Если большинство ДТП происходит в светлое время — не фокусируйся на освещении, а предложи другие меры (разметка, знаки, лежачие полицейские, камеры)
7. Если большинство ДТП происходит в темное время — предложи меры по улучшению освещения
8. Учитывай преобладающий тип ДТП при формулировке рекомендаций
9. Не добавляй лишнего форматирования в ответ

Формат ответа:
Анализ: [твой анализ]

Рекомендации:
1. [первая рекомендация]
2. [вторая рекомендация]
..."""

    # Получаем токен GigaChat
    access_token, error = get_gigachat_token()
    if error:
        return {"error": error}

    # Отправляем запрос к GigaChat
    try:
        response = requests.post(
            "https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {access_token}"
            },
            json={
                "model": "GigaChat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.5,
                "max_tokens": 1000
            },
            verify=False,
            timeout=30
        )

        if response.status_code == 200:
            result = response.json()
            recommendation = result['choices'][0]['message']['content']

            return {
                "cluster_id": cluster_id,
                "recommendation": recommendation,
                "stats": {
                    "total_accidents": total_accidents,
                    "total_killed": total_killed,
                    "total_injured": total_injured,
                    "main_dtp_type": main_dtp_type,
                    "main_lighting": lighting_info["main_lighting"],
                    "night_pct": lighting_info["night_pct"],
                    "day_pct": lighting_info["day_pct"],
                    "lighting_stats": lighting_info["lighting_stats"],
                    "road_type": road_type_label  # Добавили тип дороги
                }
            }
        else:
            return {
                "error": f"Ошибка GigaChat API: {response.status_code}",
                "details": response.text
            }

    except requests.exceptions.Timeout:
        return {"error": "Таймаут запроса к GigaChat (30 секунд)", "details": "Попробуйте ещё раз"}
    except Exception as e:
        return {"error": "Ошибка при запросе к GigaChat", "details": str(e)}


# ============================================================
# ЗАПУСК СЕРВЕРА
# ============================================================
if __name__ == "__main__":
    import uvicorn

    print("Запуск сервера...")
    print("API документация: http://localhost:8000/docs")
    print("Чтобы запустить Frontend: cd D:/ProjectPython/safe-roads-tatarstan/frontend; npm run dev")
    print("Frontend: http://localhost:5173/")
    uvicorn.run(app, host="0.0.0.0", port=8000)