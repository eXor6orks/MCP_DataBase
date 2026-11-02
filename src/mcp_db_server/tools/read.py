import base64
import json

from sqlalchemy import MetaData, Table, inspect, select

from mcp_db_server.db.conn import ConnectionManager

DEFAULT_LIMIT = 50
MAX_LIMIT = 500

def list_tables(conn : ConnectionManager, connection_name : str) -> list[str]:
    engine = conn.get_engine(connection_name)
    return inspect(engine).get_table_names()
