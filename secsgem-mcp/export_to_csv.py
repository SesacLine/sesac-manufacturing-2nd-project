import sqlite3
import pandas as pd
import os

DB_PATH = "datasets/fab.db"
OUT_DIR = "datasets/csv_export"
os.makedirs(OUT_DIR, exist_ok=True)

conn = sqlite3.connect(DB_PATH)

tables = {
    "wafer":        "SELECT lot_id, wafer_id, source, die_size, is_normal FROM wafer",
    "lot_history":  "SELECT * FROM lot_history",
    "telemetry":    "SELECT * FROM telemetry",
    "alarm":        "SELECT * FROM alarm",
    "maintenance":  "SELECT * FROM maintenance",
    "metric_series":"SELECT * FROM metric_series",
    "event_log":    "SELECT * FROM event_log",
}

for name, query in tables.items():
    df = pd.read_sql_query(query, conn)
    path = f"{OUT_DIR}/{name}.csv"
    df.to_csv(path, index=False)
    print(f"✅ {name}.csv — {len(df):,}행")

conn.close()
print("\n완료. datasets/csv_export/ 폴더 확인")
