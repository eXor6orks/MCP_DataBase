import base64
import json

from sqlalchemy import MetaData, Table, inspect, select

from mcp_db_server.db.conn import ConnectionManager

DEFAULT_LIMIT = 50
MAX_LIMIT = 500

def _encode_cursor(value) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode()

def _decode_cursor(cursor: str):
    return json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())

def list_tables(conn : ConnectionManager, connection_name : str) -> list[str]:
    engine = conn.get_engine(connection_name)
    return inspect(engine).get_table_names()

def schema_table(conn : ConnectionManager, connection_name : str, table_name : str) -> dict :
    engine = conn.get_engine(connection_name)
    metadata = MetaData()
    table = Table(table_name, metadata, autoload_with=engine)

    column_info = []
    for column in table.columns:
        column_info.append({
            "name": column.name,
            "type": str(column.type),
            "nullable": column.nullable,
            "default": str(column.default) if column.default is not None else None,
            "primary_key": column.primary_key,
        })
    return {
        "name": table_name,
        "columns": column_info
    }

def list_rows(
        conn : ConnectionManager,
        connection_name : str,
        table_name : str,
        after_cursor : str | None = None,
        limit : int = DEFAULT_LIMIT
) -> list[dict]:
    if limit > MAX_LIMIT:
        raise ValueError(f"Limit exceeds maximum allowed value of {MAX_LIMIT}")

    engine = conn.get_engine(connection_name)
    inspector = inspect(engine)
    ordering_col_name, _ = _find_ordering_column(inspector, table_name)

    metadata = MetaData()
    table = Table(table_name, metadata, autoload_with=engine)

    if ordering_col_name is not None:
        order_col = table.c[ordering_col_name]
        query = select(table).order_by(order_col).limit(limit)
        if after_cursor is not None:
            query = query.where(order_col > _decode_cursor(after_cursor))
        pagination_mode = "keyset"
    else:
        offset = _decode_cursor(after_cursor) if after_cursor is not None else 0
        query = select(table).order_by(*table.columns).limit(limit).offset(offset)
        pagination_mode = "offset"

    with engine.connect() as connection:
        result = connection.execute(query)
        rows = [dict(row._mapping) for row in result]

    if pagination_mode == "keyset":
        next_cursor = _encode_cursor(rows[-1][ordering_col_name]) if len(rows) == limit else None
    else:
        next_cursor = _encode_cursor(offset + len(rows)) if len(rows) == limit else None

    return {"rows": rows, "next_cursor": next_cursor, "pagination_mode": pagination_mode}

def _find_ordering_column(inspector, table_name: str) -> tuple[str | None, bool]:
    """Retourne (colonne à utiliser, is_unique).
    Priorité : clé primaire simple > contrainte UNIQUE simple > index UNIQUE simple.
    (colonne=None, False) si rien d'unique n'a été trouvé.
    """
    pk_cols = inspector.get_pk_constraint(table_name).get("constrained_columns") or []
    if len(pk_cols) == 1:
        return pk_cols[0], True
    if len(pk_cols) > 1:
        raise ValueError(f"'{table_name}' a une clé primaire composite — non supporté pour l'instant")

    for uc in inspector.get_unique_constraints(table_name):
        cols = uc.get("column_names") or []
        if len(cols) == 1:
            return cols[0], True

    for idx in inspector.get_indexes(table_name):
        if idx.get("unique") and len(idx.get("column_names", [])) == 1:
            return idx["column_names"][0], True

    return None, False