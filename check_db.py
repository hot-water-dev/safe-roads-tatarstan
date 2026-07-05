import sqlite3
import pandas as pd

conn = sqlite3.connect('accidents.db')

# 1. Показать все колонки таблицы
print("=" * 60)
print("КОЛОНКИ ТАБЛИЦЫ accidents:")
print("=" * 60)
cursor = conn.execute("PRAGMA table_info(accidents)")
for row in cursor:
    print(f"  {row[1]:20s} ({row[2]})")

# 2. Показать уникальные значения в ключевых колонках
print("\n" + "=" * 60)
print("УНИКАЛЬНЫЕ ЗНАЧЕНИЯ В КОЛОНКАХ:")
print("=" * 60)

for col in ['district', 'road_category', 'road_name', 'lighting', 'dtp_type']:
    try:
        df = pd.read_sql_query(f"SELECT DISTINCT {col} FROM accidents WHERE {col} IS NOT NULL LIMIT 20", conn)
        print(f"\n{col} (первые 20 значений):")
        for _, row in df.iterrows():
            print(f"  - {row[col]}")
    except Exception as e:
        print(f"\n{col}: колонка не найдена или ошибка ({e})")

# 3. Посчитать, сколько записей имеют road_category и road_name
print("\n" + "=" * 60)
print("ЗАПОЛНЕННОСТЬ ПОЛЕЙ:")
print("=" * 60)
df = pd.read_sql_query("SELECT * FROM accidents", conn)
print(f"Всего записей: {len(df)}")
print(f"road_category заполнено: {df['road_category'].notna().sum()} из {len(df)}")
print(f"road_name заполнено: {df['road_name'].notna().sum()} из {len(df)}")
print(f"district заполнено: {df['district'].notna().sum()} из {len(df)}")

conn.close()