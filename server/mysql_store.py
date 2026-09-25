from __future__ import annotations
from .secrets import _parse_env_file, ENV_FILE
import os
from typing import Any

# 支持进程环境和 .env.local；密码只用于连接，不返回 API 响应。
_FILE_ENV = _parse_env_file(ENV_FILE)
def _setting(name: str, default: str = "") -> str:
    return os.getenv(name, _FILE_ENV.get(name, default)).strip()
_USE_MYSQL = _setting("X100_MYSQL_ENABLED", "1") == "1"
# 订单工具每次查询建立短连接；连接失败由上层降级到脱敏演示数据。
def _connect():
    if not _USE_MYSQL: return None
    try:
        import mysql.connector
        return mysql.connector.connect(
            host=_setting("X100_MYSQL_HOST", "127.0.0.1"),
            port=int(_setting("X100_MYSQL_PORT", "3306")),
            user=_setting("X100_MYSQL_USER", "root"),
            password=_setting("X100_MYSQL_PASSWORD", ""),
            database=_setting("X100_MYSQL_DATABASE", "x100_demo"),
            connection_timeout=2,
        )
    except Exception:
        return None

def get_order(order_id: str) -> dict[str, Any] | None:
    conn=_connect()
    if conn is None: return None
    try:
        cur=conn.cursor(dictionary=True)
        cur.execute("SELECT order_id, owner_id, status, ordered_at, item_summary, eta FROM orders WHERE order_id=%s", (order_id,))
        row=cur.fetchone()
        if not row: return None
        return {"owner": row["owner_id"], "status": row["status"], "orderedAt": str(row["ordered_at"]), "item": row["item_summary"], "eta": str(row["eta"] or "")}
    finally:
        conn.close()

# 初始化只写入虚构演示订单，不能接触真实客户数据。
def init_mysql_schema():
    try:
        import mysql.connector
        conn=mysql.connector.connect(host=_setting("X100_MYSQL_HOST", "127.0.0.1"), port=int(_setting("X100_MYSQL_PORT", "3306")), user=_setting("X100_MYSQL_USER", "root"), password=_setting("X100_MYSQL_PASSWORD", ""), connection_timeout=2)
    except Exception:
        return False
    try:
        cur=conn.cursor()
        cur.execute("CREATE DATABASE IF NOT EXISTS x100_demo CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        cur.execute("USE x100_demo")
        cur.execute("""CREATE TABLE IF NOT EXISTS orders (order_id VARCHAR(32) PRIMARY KEY, owner_id VARCHAR(64) NOT NULL, status VARCHAR(32) NOT NULL, ordered_at DATE NOT NULL, item_summary VARCHAR(128) NOT NULL, eta DATE NULL)""")
        cur.executemany("INSERT INTO orders VALUES (%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE owner_id=VALUES(owner_id), status=VALUES(status), ordered_at=VALUES(ordered_at), item_summary=VALUES(item_summary), eta=VALUES(eta)",[("ORD-DEMO-1001","demo-user","运输中","2026-09-17","X100 主机","2026-09-26"),("ORD-DEMO-1002","other-user","已签收","2026-09-18","X100 配件","2026-09-23")])
        conn.commit(); return True
    finally: conn.close()
