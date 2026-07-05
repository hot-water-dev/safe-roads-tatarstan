import os
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime

# ============================================================
# НАСТРОЙКИ
# ============================================================
XML_FOLDER = 'xml_data'
DB_NAME = 'accidents.db'


# ============================================================
# 1. СОЗДАНИЕ БАЗЫ ДАННЫХ
# ============================================================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Таблица ДТП
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS accidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emtp_number TEXT UNIQUE,
            date TEXT,
            time TEXT,
            district TEXT,
            dtp_type TEXT,
            killed INTEGER DEFAULT 0,
            injured INTEGER DEFAULT 0,
            latitude REAL,
            longitude REAL,
            street TEXT,
            house TEXT,
            settlement TEXT,
            road_name TEXT,
            road_category TEXT,
            weather TEXT,
            road_condition TEXT,
            lighting TEXT
        )
    ''')

    # Таблица ТС
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vehicles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            accident_id INTEGER,
            n_ts INTEGER,
            marka TEXT,
            model TEXT,
            type TEXT,
            FOREIGN KEY (accident_id) REFERENCES accidents(id)
        )
    ''')

    # Таблица участников
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            accident_id INTEGER,
            vehicle_id INTEGER,
            category TEXT,
            severity TEXT,
            violations TEXT,
            alcohol TEXT,
            FOREIGN KEY (accident_id) REFERENCES accidents(id),
            FOREIGN KEY (vehicle_id) REFERENCES vehicles(id)
        )
    ''')

    conn.commit()
    conn.close()
    print("✅ База данных создана")


# ============================================================
# 2. ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ
# ============================================================
def get_text(parent, tag):
    """Безопасно получает текст из XML-тега."""
    el = parent.find(tag)
    if el is not None and el.text:
        return el.text.strip()
    return None


def get_all_text(parent, tag):
    """Получает все значения тега (если их несколько)."""
    elements = parent.findall(tag)
    texts = [el.text.strip() for el in elements if el.text]
    return ', '.join(texts) if texts else None


# ============================================================
# 3. ПАРСИНГ XML
# ============================================================
def parse_xml_files():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    files = [f for f in os.listdir(XML_FOLDER) if f.endswith('.xml')]
    print(f" Найдено XML файлов: {len(files)}")

    total_accidents = 0

    for filename in sorted(files):
        filepath = os.path.join(XML_FOLDER, filename)
        print(f"🔄 Обработка: {filename}")

        try:
            tree = ET.parse(filepath)
            root = tree.getroot()

            for tab in root.findall('tab'):
                emtp = get_text(tab, 'EMTP_NUMBER')
                if not emtp:
                    continue

                # Проверяем, нет ли уже такого ДТП в базе
                cursor.execute("SELECT id FROM accidents WHERE emtp_number=?", (emtp,))
                if cursor.fetchone():
                    continue

                # Данные ДТП
                date = get_text(tab, 'date')
                time_val = get_text(tab, 'time')
                district = get_text(tab, 'district')
                dtp_type = get_text(tab, 'DTPV')
                killed = int(get_text(tab, 'POG') or 0)
                injured = int(get_text(tab, 'RAN') or 0)

                # infoDtp
                info = tab.find('infoDtp')
                if info is None:
                    continue

                lat_text = get_text(info, 'COORD_W')
                lon_text = get_text(info, 'COORD_L')
                latitude = float(lat_text) if lat_text else None
                longitude = float(lon_text) if lon_text else None

                street = get_text(info, 'street')
                house = get_text(info, 'house')
                settlement = get_text(info, 'NP')
                road_name = get_text(info, 'dor')
                road_category = get_text(info, 'dor_z')
                weather = get_text(info, 'spog')
                road_condition = get_text(info, 's_pch')
                lighting = get_text(info, 'osv')

                # Вставляем ДТП
                cursor.execute('''
                    INSERT INTO accidents 
                    (emtp_number, date, time, district, dtp_type, killed, injured,
                     latitude, longitude, street, house, settlement, road_name,
                     road_category, weather, road_condition, lighting)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (emtp, date, time_val, district, dtp_type, killed, injured,
                      latitude, longitude, street, house, settlement, road_name,
                      road_category, weather, road_condition, lighting))

                acc_id = cursor.lastrowid

                # Парсим ТС
                for ts in info.findall('ts_info'):
                    n_ts = int(get_text(ts, 'n_ts') or 0)
                    marka = get_text(ts, 'marka_ts')
                    model = get_text(ts, 'm_ts')
                    ts_type = get_text(ts, 't_ts')

                    cursor.execute('''
                        INSERT INTO vehicles (accident_id, n_ts, marka, model, type)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (acc_id, n_ts, marka, model, ts_type))

                    ts_id = cursor.lastrowid

                    # Участники, привязанные к ТС
                    for uch in ts.findall('ts_uch'):
                        category = get_text(uch, 'k_UCH')
                        severity = get_text(uch, 's_T')
                        violations = get_all_text(uch, 'NPDD')
                        alcohol = get_text(uch, 'ALCO')

                        cursor.execute('''
                            INSERT INTO participants 
                            (accident_id, vehicle_id, category, severity, violations, alcohol)
                            VALUES (?, ?, ?, ?, ?, ?)
                        ''', (acc_id, ts_id, category, severity, violations, alcohol))

                # Пешеходы и велосипедисты (отдельно от ТС)
                for uch in info.findall('uchInfo'):
                    category = get_text(uch, 'k_UCH')
                    severity = get_text(uch, 's_T')
                    violations = get_all_text(uch, 'NPDD')
                    alcohol = get_text(uch, 'ALCO')

                    cursor.execute('''
                        INSERT INTO participants 
                        (accident_id, vehicle_id, category, severity, violations, alcohol)
                        VALUES (?, NULL, ?, ?, ?, ?)
                    ''', (acc_id, category, severity, violations, alcohol))

                total_accidents += 1

            print(f"   ✅ {filename}: обработано")

        except Exception as e:
            print(f"   ❌ Ошибка в {filename}: {e}")

    conn.commit()
    conn.close()
    print(f"\n🎉 Всего загружено ДТП: {total_accidents}")


# ============================================================
# 4. ЗАПУСК
# ============================================================
if __name__ == "__main__":
    print("=" * 50)
    print("ЭТАП 1: Подготовка данных")
    print("=" * 50)

    init_db()
    parse_xml_files()

    # Проверка
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM accidents")
    print(f"📊 ДТП в базе: {cursor.fetchone()[0]}")

    cursor.execute("SELECT COUNT(*) FROM vehicles")
    print(f"🚗 ТС в базе: {cursor.fetchone()[0]}")

    cursor.execute("SELECT COUNT(*) FROM participants")
    print(f" Участников в базе: {cursor.fetchone()[0]}")

    # Пример первых 3 ДТП
    print("\n Пример данных:")
    cursor.execute('''
        SELECT emtp_number, date, district, dtp_type, killed, injured, latitude, longitude
        FROM accidents LIMIT 3
    ''')
    for row in cursor.fetchall():
        print(f"  {row}")

    conn.close()