import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.mysql_store import init_mysql_schema
print("mysql initialized" if init_mysql_schema() else "mysql unavailable; use server/mysql_schema.sql after starting MySQL")
