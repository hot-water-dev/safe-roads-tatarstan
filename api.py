import sqlite3 # Работа с базой данных SQLite
import numpy as np # Математические операции с массивами (для будущей работы с координатами)
import pandas as pd # Работа с таблицами, почти как Exel
from sklearn.cluster import DBSCAN # Алгоритм кластеризации (поиск очагов аварийности)
from sklearn.preprocessing import StandardScaler # Приведение данных к одному масштабу
from fastapi import FastAPI, Query # Создание API (сервер, который отдаёт данные)
from fastapi.middleware.cors import CORSMiddleware # Разрешение фронтенду (React) обращаться к API
from typing import Optional # Показывает, что параметр может быть пуст

 # ============================================================
 # НАСТРОЙКИ
 # ============================================================
DB_NAME = 'accidents.db' # Имя нашей базы данных

app = FastAPI(title="Анализ аварийности РТ", version="1.0.0") # Создадим сервер 'app', наполним метаданные

 # Разрешаем фронтенду (React) обращаться к нашему API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Разрешаем запросы с любых сайтов
    allow_credentials=True, # Разрешаем передачу cookies
    allow_methods=["*"], # Разрешаем любые HTTP-методы
    allow_headers=["*"], # Разрешаем любые заголовки
)

 # ============================================================
 # ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ: подключение к БД
 # ============================================================
def get_db():
    conn = sqlite3.connect(DB_NAME) # Открываем базу данных
    conn.row_factory = sqlite3.Row # Настраиваем возврат строк как словарей
    return conn # Возвращаем подключение


 # ============================================================
 # ЭНДПОИНТ 1: Получить все ДТП
 # ============================================================
@app.get("/api/accidents") # Регистрируем URL-адрес, по которому будет проходить запрос
def get_accidents(
        district: Optional[str] = Query(None, description="Район"), # Фильтр по району (необязательный)
        dtp_type: Optional[str] = Query(None, description="Тип ДТП"), # Фильтр по типу ДТП (необязательный)
        month: Optional[str] = Query(None, description="Месяц (YYYY-MM)"), # Фильтр по месяцу (необязательный)
        min_killed: Optional[int] = Query(None, description="Мин. погибших"), # Фильтр по количеству погибших (от кокого-то числа)
        limit: int = Query(500, description="Максимум записей") # Ограничение количества возвращаемых записей (не засорять все строками)
):
    # Получить список ДТП с фильтрами"
    conn = get_db() # Получаем подключение к БД через вспомогательную функцию

    query = "SELECT * FROM accidents WHERE 1=1" # Базовый запрос. WHERE 1=1 — это хак, чтобы удобно добавлять условия через AND
    params = [] # Список параметров для подстановки в запрос

    if district: # Если пользователь передал параметр района
        query += " AND district = ?" # Добавляем условие
        params.append(district) # Добавляем значение в список параметров
    if dtp_type: # Если пользователь передал тип ДТП
        query += " AND dtp_type = ?" # Добавляем условие
        params.append(dtp_type) # Добавляем значение
    if month: # Если пользователь передал месяц
 # Фильтр по месяцу (формат даты в БД: DD.MM.YYYY)
        query += " AND SUBSTR(date, 4, 7) = ?" # SUBSTR извлекает подстроку: начинаем с 4-го символа, берём 7 символов (получаем MM.YYYY)
        params.append(month[5:7] + "." + month[:4]) # Преобразуем "2026-05" в "05.2026"
    if min_killed is not None: # Если пользователь передал количество погибших (0 — это валидное значение)
        query += " AND killed >= ?" # Добавляем условие "погибших больше или равно N"
        params.append(min_killed) # Добавляем значение

    query += f" LIMIT {limit}" # Ограничиваем количество возвращаемых записей

    rows = conn.execute(query, params).fetchall() # Выполняем запрос и получаем все строки результата
    conn.close() # Закрываем подключение к БД

    return [dict(row) for row in rows] # Преобразуем каждую строку в словарь и возвращаем список


 # ============================================================
 # ЭНДПОИНТ 2: Получить кластеры (очаги аварийности)
 # ============================================================
@app.get("/api/clusters") # Регистрируем URL
def get_clusters(
        eps: float = Query(0.01, description="Радиус кластеризации (в градусах, ~1 км)"), # Параметр DBSCAN: максимальное расстояние между точками в одном кластере
        min_samples: int = Query(3, description="Мин. ДТП для образования кластера"), # Параметр DBSCAN: минимум точек, чтобы считаться кластером
        month: Optional[str] = Query(None, description="Фильтр по месяцу (YYYY-MM)") # Фильтр по месяцу (необязательный)
):
    # Автоматический поиск очагов аварийности через DBSCAN
    conn = get_db() # Получаем подключение к БД

 # Загружаем данные
    query = """
        SELECT id, emtp_number, date, time, district, dtp_type, 
               killed, injured, latitude, longitude, road_name, road_category
        FROM accidents 
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
        AND latitude != 0 AND longitude != 0
    """

    if month: # Если передан фильтр по месяцу
        query += " AND SUBSTR(date, 4, 7) = ?" # Добавляем условие фильтрации по месяцу
        df = pd.read_sql_query(query, conn, params=[month[5:7] + "." + month[:4]]) # Выполняем запрос и загружаем результат в pandas DataFrame
    else: # Если фильтр не передан
        df = pd.read_sql_query(query, conn) # Загружаем все данные в DataFrame

    conn.close() # Закрываем подключение к БД

    if len(df) < min_samples: # Если записей меньше, чем нужно для кластера
        return {"clusters": [], "noise_count": len(df), "total": len(df)} # Возвращаем пустой результат (кластеризация невозможна)

 # --------------------------------------------------------
 # КЛАСТЕРИЗАЦИЯ DBSCAN
 # --------------------------------------------------------
 # Используем только координаты для географической кластеризации
    coords = df[['latitude', 'longitude']].values # Извлекаем только колонки с координатами и превращаем в numpy-массив

 # Нормализация (чтобы широта и долгота имели одинаковый вес)
    scaler = StandardScaler() # Создаём объект нормализатора
    coords_scaled = scaler.fit_transform(coords) # fit — вычисляет среднее и стандартное отклонение, transform — применяет формулу: (x - mean) / std

 # Запускаем DBSCAN
    clustering = DBSCAN(eps=eps, min_samples=min_samples) # Создаём объект DBSCAN с нашими параметрами
    df['cluster'] = clustering.fit_predict(coords_scaled) # fit_predict — обучает модель на данных и сразу присваивает каждой точке номер кластера

 # --------------------------------------------------------
 # АНАЛИЗ КЛАСТЕРОВ
 # --------------------------------------------------------
    clusters = [] # Пустой список, куда будем складывать информацию о каждом кластере
    noise_count = len(df[df['cluster'] == -1]) # Считаем количество точек с меткой -1 (это "шум" — одиночные ДТП, не попавшие ни в один кластер)

    for cluster_id in sorted(df['cluster'].unique()): # Перебираем все уникальные номера кластеров (отсортированные по возрастанию)
        if cluster_id == -1: # Если это одиночные ДТП
            continue # Пропускаем — нам не интересны одиночные аварии

        cluster_data = df[df['cluster'] == cluster_id] # Фильтруем DataFrame: оставляем только строки текущего кластера

 # Основная статистика
        total_killed = int(cluster_data['killed'].sum()) # Суммируем погибших в кластере и преобразуем в обычный int
        total_injured = int(cluster_data['injured'].sum()) # Суммируем раненых в кластере
        total_participants = len(cluster_data) # Считаем количество ДТП в кластере

 # Преобладающий тип ДТП
        dtp_type_counts = cluster_data['dtp_type'].value_counts() # value_counts() считает, сколько раз встречается каждое значение (например: "Столкновение": 5, "Наезд": 3)
        main_dtp_type = dtp_type_counts.index[0] if len(dtp_type_counts) > 0 else "Неизвестно" # Берём первое (самое частое) значение, если оно есть
        main_dtp_pct = round(dtp_type_counts.iloc[0] / total_participants * 100) if total_participants > 0 else 0 # Считаем процент: (количество самого частого типа / всего ДТП) * 100

 # Преобладающий район
        district_counts = cluster_data['district'].value_counts() # Считаем частоту районов в кластере
        main_district = district_counts.index[0] if len(district_counts) > 0 else "Неизвестно" # Берём самый частый район

 # Уровень опасности
        if total_killed > 0: # Если есть погибшие
            danger_level = "critical" # Критический уровень (красный)
        elif total_injured >= 5: # Если 5 и более раненых
            danger_level = "high" # Высокий уровень (оранжевый)
        elif total_injured >= 2: # Если 2 и более раненых
            danger_level = "medium" # Средний уровень (жёлтый)
        else: # Во всех остальных случаях
            danger_level = "low" # Низкий уровень (зелёный)

 # Цвет для карты
        color_map = { # Словарь: уровень опасности → цвет для отрисовки на карте
            "critical": "red",
            "high": "orange",
            "medium": "yellow",
            "low": "green"
        }

 # Центр кластера (среднее координат)
        center_lat = float(cluster_data['latitude'].mean()) # Считаем среднюю широту всех точек кластера (где поставить маркер на карте)
        center_lon = float(cluster_data['longitude'].mean()) # Считаем среднюю долготу

 # Временной анализ
        time_data = cluster_data['time'].dropna() # Берём колонку time и удаляем пустые значения (NaN)
        night_count = 0 # Счётчик ночных ДТП
        for t in time_data: # Перебираем каждое время в кластере
            try: # На случай, если время в неправильном формате
                hour = int(t.split(':')[0]) # Разделяем строку "14:30" по ":" и берём первую часть (часы), преобразуем в число
                if hour >= 21 or hour < 6: # Если время между 21:00 и 06:00
                    night_count += 1 # Увеличиваем счётчик ночных ДТП
            except: # Если что-то пошло не так (например, время в странном формате)
                pass # Пропускаем запись
        night_pct = round(night_count / len(time_data) * 100) if len(time_data) > 0 else 0 # Считаем процент ночных ДТП

        clusters.append({ # Добавляем словарь с информацией о кластере в список
            "id": int(cluster_id), # Номер кластера
            "center_lat": round(center_lat, 6), # Широта центра (округляем до 6 знаков, чтобы не было длинных хвостов)
            "center_lon": round(center_lon, 6), # Долгота центра
            "accidents_count": total_participants, # Количество ДТП в кластере
            "killed_total": total_killed, # Всего погибших
            "injured_total": total_injured, # Всего раненых
            "main_dtp_type": main_dtp_type, # Самый частый тип ДТП
            "main_dtp_pct": main_dtp_pct, # Процент этого типа
            "main_district": main_district, # Самый частый район
            "danger_level": danger_level, # Уровень опасности (текстом)
            "color": color_map[danger_level], # Цвет для карты (берём из словаря по уровню)
            "night_pct": night_pct, # Процент ночных ДТП
            "accidents": [ # Список всех ДТП в этом кластере (подробная информация)
                {
                    "id": int(row['id']), # ID записи в БД
                    "emtp_number": row['emtp_number'], # Номер ДТП
                    "date": row['date'], # Дата
                    "time": row['time'], # Время
                    "dtp_type": row['dtp_type'], # Тип ДТП
                    "killed": row['killed'], # Погибших
                    "injured": row['injured'], # Раненых
                    "latitude": row['latitude'], # Широта
                    "longitude": row['longitude'] # Долгота
                }
                for _, row in cluster_data.iterrows() # iterrows() — итерация по строкам DataFrame; _ — это индекс строки (нам не нужен), row — сама строка
            ]
        })

 # Сортируем по опасности (погибшие > раненые > количество)
    clusters.sort(key=lambda x: (x['killed_total'], x['injured_total'], x['accidents_count']), reverse=True) # lambda — анонимная функция; сортируем по кортежу (сначала по погибшим, потом по раненым, потом по количеству); reverse=True — по убыванию

    return { # Возвращаем словарь
        "clusters": clusters, # Список всех кластеров
        "total_clusters": len(clusters), # Общее количество кластеров
        "noise_count": noise_count, # Количество "шума" (одиночных ДТП)
        "total_accidents": len(df), # Общее количество обработанных ДТП
        "eps_used": eps, # Параметр eps, который использовался (для отладки)
        "min_samples_used": min_samples # Параметр min_samples, который использовался
    }


 # ============================================================
 # ЭНДПОИНТ 3: Общая статистика
 # ============================================================
@app.get("/api/stats") # Регистрируем URL
def get_stats():
    # Общая статистика по всем ДТП
    conn = get_db() # Получаем подключение к БД

 # Общая статистика
    total = conn.execute("SELECT COUNT(*) FROM accidents").fetchone()[0] # Считаем общее количество записей в таблице accidents
    total_killed = conn.execute("SELECT SUM(killed) FROM accidents").fetchone()[0] or 0 # Суммируем всех погибших (0 — если SUM вернёт None)
    total_injured = conn.execute("SELECT SUM(injured) FROM accidents").fetchone()[0] or 0 # Суммируем всех раненых

 # По районам
    districts = conn.execute("""
        SELECT district, COUNT(*) as cnt, SUM(killed) as killed, SUM(injured) as injured
        FROM accidents GROUP BY district ORDER BY killed DESC, cnt DESC LIMIT 10
    """).fetchall() # GROUP BY — группируем по району; ORDER BY killed DESC — сортируем по убыванию погибших; LIMIT 10 — берём топ-10

 # По типам ДТП
    types = conn.execute("""
        SELECT dtp_type, COUNT(*) as cnt, SUM(killed) as killed
        FROM accidents GROUP BY dtp_type ORDER BY killed DESC, cnt DESC LIMIT 10
    """).fetchall() # Аналогично: группируем по типу ДТП, сортируем по погибшим, берём топ-10

 # По месяцам
    months = conn.execute("""
        SELECT SUBSTR(date, 4, 7) as month, COUNT(*) as cnt, SUM(killed) as killed
        FROM accidents GROUP BY month ORDER BY month
    """).fetchall() # SUBSTR(date, 4, 7) извлекает MM.YYYY из даты; GROUP BY month — группируем по месяцу; ORDER BY month — сортируем по возрастанию (хронологически)

    conn.close() # Закрываем подключение к БД

    return { # Возвращаем словарь со статистикой
        "total_accidents": total, # Всего ДТП
        "total_killed": int(total_killed), # Всего погибших (преобразуем в int, чтобы не было numpy-типа)
        "total_injured": int(total_injured), # Всего раненых
        "top_districts": [dict(d) for d in districts], # Топ-10 районов (преобразуем каждую строку в словарь)
        "top_types": [dict(t) for t in types], # Топ-10 типов ДТП
        "monthly": [dict(m) for m in months] # Статистика по месяцам
    }


 # ============================================================
 # ЭНДПОИНТ 4: Детали конкретного кластера
 # ============================================================
@app.get("/api/cluster/{cluster_id}") # {cluster_id} — ID кластера
def get_cluster_detail(cluster_id: int): # FastAPI автоматически преобразует строку из URL в int
    # Получить детальную информацию о конкретном кластере
    conn = get_db() # Получаем подключение к БД

 # Загружаем все ДТП и кластеризуем заново
    df = pd.read_sql_query("""
        SELECT * FROM accidents 
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
        AND latitude != 0 AND longitude != 0
    """, conn) # Загружаем все ДТП с координатами в DataFrame

    conn.close() # Закрываем подключение к БД

    coords = df[['latitude', 'longitude']].values # Извлекаем координаты в numpy-массив
    scaler = StandardScaler() # Создаём нормализатор
    coords_scaled = scaler.fit_transform(coords) # Нормализуем координаты

    clustering = DBSCAN(eps=0.01, min_samples=3) # Создаём DBSCAN с фиксированными параметрами
    df['cluster'] = clustering.fit_predict(coords_scaled) # Кластеризуем данные

    cluster_data = df[df['cluster'] == cluster_id] # Фильтруем: оставляем только ДТП из запрошенного кластера

    if len(cluster_data) == 0: # Если кластер не найден
        return {"error": "Кластер не найден"} # Возвращаем ошибку

    return { # Возвращаем информацию о кластере
        "cluster_id": cluster_id, # ID кластера
        "accidents_count": len(cluster_data), # Количество ДТП
        "killed_total": int(cluster_data['killed'].sum()), # Всего погибших
        "injured_total": int(cluster_data['injured'].sum()), # Всего раненых
        "accidents": [dict(row) for _, row in cluster_data.iterrows()] # Список всех ДТП в кластере (каждая строка → словарь)
    }


 # ============================================================
 # ЗАПУСК СЕРВЕРА
 # ============================================================
if __name__ == "__main__": # Этот блок выполняется только если файл запущен напрямую (не импортирован)
    import uvicorn # Импортируем ASGI-сервер (официант, который принимает запросы и передаёт их в FastAPI)

    print("Запуск сервера...") # Выводим сообщение в консоль
    print("API документация: http://localhost:8000/docs") # Подсказка, где посмотреть автодокументацию
    uvicorn.run(app, host="0.0.0.0", port=8000) # Запускаем сервер: host="0.0.0.0" — слушаем все сетевые интерфейсы, port=8000 — на порту 8000
