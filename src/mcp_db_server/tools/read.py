import base64
import json
from typing import Any, Literal
from pydantic import BaseModel, field_validator

from sqlalchemy import MetaData, Table, inspect, select, and_

from mcp_db_server.db.conn import ConnectionManager

DEFAULT_LIMIT = 50
MAX_LIMIT = 500

_OPERATORS = {
    "eq": lambda col, val: col == val,
    "ne": lambda col, val: col != val,
    "gt": lambda col, val: col > val,
    "gte": lambda col, val: col >= val,
    "lt": lambda col, val: col < val,
    "lte": lambda col, val: col <= val,
    "like": lambda col, val: col.like(val),
    "in": lambda col, val: col.in_(val),
    "is_null": lambda col, val: col.is_(None) if val else col.is_not(None),
}

_OPERATOR_ALIASES = {
    "=": "eq", "==": "eq", "is": "eq",
    "!=": "ne", "<>": "ne",
    ">": "gt", ">=": "gte", "<": "lt", "<=": "lte",
    "contains": "like", "matches": "like",
}

FilterValue = str | int | float | bool | list[str | int | float] | None

class FilterCondition(BaseModel):
    column: str
    operator: Literal["eq", "ne", "gt", "gte", "lt", "lte", "like", "in", "is_null"]
    value: FilterValue = None

    @field_validator("operator", mode="before")
    @classmethod
    def normalize_operator(cls, v):
        if isinstance(v, str):
            v = _OPERATOR_ALIASES.get(v.strip().lower(), v.strip().lower())
        return v

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

def _normalize_filters(filters: "list[FilterCondition] | list[dict] | dict | None") -> list[FilterCondition]:
    if filters is None:
        return []
    if isinstance(filters, dict):
        return [FilterCondition(column=col, operator="eq", value=val) for col, val in filters.items()]
    return [f if isinstance(f, FilterCondition) else FilterCondition.model_validate(f) for f in filters]


def _build_filter_clauses(table: Table, conditions: list[FilterCondition]) -> list:
    clauses = []
    for cond in conditions:
        if cond.column not in table.c:
            raise ValueError(
                f"Colonne inconnue dans le filtre : '{cond.column}' "
                f"(disponibles : {', '.join(c.name for c in table.c)}). "
                f"Format attendu : {{'column': ..., 'operator': 'eq'|'ne'|'gt'|'gte'|'lt'|'lte'|'like'|'in'|'is_null', 'value': ...}}"
            )
        clauses.append(_OPERATORS[cond.operator](table.c[cond.column], cond.value))
    return clauses

def _resolve_selected_columns(table: Table, columns: list[str] | None, ordering_col_name: str | None):
    if columns is None:
        return list(table.columns), None

    unknown = set(columns) - {c.name for c in table.c}
    if unknown:
        raise ValueError(f"Colonnes inconnues : {', '.join(sorted(unknown))}")

    requested = list(dict.fromkeys(columns))
    select_cols = list(requested)
    if ordering_col_name and ordering_col_name not in select_cols:
        select_cols.append(ordering_col_name)

    strip_col = ordering_col_name if ordering_col_name and ordering_col_name not in requested else None
    return [table.c[name] for name in select_cols], strip_col

def list_rows(
    conn: ConnectionManager,
    connection_name: str,
    table_name: str,
    after_cursor: str | None = None,
    limit: int = DEFAULT_LIMIT,
    filters: list[FilterCondition] | dict[str, Any] | None = None,
    columns: list[str] | None = None,
) -> dict:
    if limit > MAX_LIMIT:
        raise ValueError(f"Limit exceeds maximum allowed value of {MAX_LIMIT}")

    engine = conn.get_engine(connection_name)
    inspector = inspect(engine)
    ordering_col_name, _ = _find_ordering_column(inspector, table_name)

    metadata = MetaData()
    table = Table(table_name, metadata, autoload_with=engine)

    select_cols, strip_col = _resolve_selected_columns(table, columns, ordering_col_name)
    conditions = _normalize_filters(filters)
    clauses = _build_filter_clauses(table, conditions) if conditions else []

    if ordering_col_name is not None:
        order_col = table.c[ordering_col_name]
        query = select(*select_cols).order_by(order_col).limit(limit)
        if after_cursor is not None:
            clauses.append(order_col > _decode_cursor(after_cursor))
        pagination_mode = "keyset"
    else:
        offset = _decode_cursor(after_cursor) if after_cursor is not None else 0
        query = select(*select_cols).order_by(*table.columns).limit(limit).offset(offset)
        pagination_mode = "offset"

    if clauses:
        query = query.where(and_(*clauses))

    with engine.connect() as connection:
        rows = [dict(row._mapping) for row in connection.execute(query)]

    if pagination_mode == "keyset":
        next_cursor = _encode_cursor(rows[-1][ordering_col_name]) if len(rows) == limit else None
    else:
        next_cursor = _encode_cursor(offset + len(rows)) if len(rows) == limit else None

    if strip_col is not None:
        for row in rows:
            row.pop(strip_col, None)

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