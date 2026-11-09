from fastmcp import FastMCP

from mcp_db_server.config import AppConfig, load_config
from mcp_db_server.policy import load_policy
from mcp_db_server.db.conn import ConnectionManager
from mcp_db_server.tools import read as read_tools
from mcp_db_server.policy import AccessLevel, no_policy_check, read_extractor, requires_policy

try:
    config : AppConfig = load_config()
except Exception as e:
    print(f'Error loading configuration: {e}')
    raise SystemExit(1)

try:
    policy = load_policy(connection_names=config.connections.keys())
except Exception as e:
    print(f'{e}')
    raise SystemExit(1)


mcp = FastMCP("mcp-db-server")

_conn_manager = ConnectionManager(config)

@mcp.tool
@no_policy_check
def list_connections() -> list[str]:
    """
    List all available database connections defined in the configuration.
    
    Returns:
        list[str]: A list of connection names.
    """
    return _conn_manager.names()

@mcp.tool
@no_policy_check
def list_tables(connection_name : str) -> list[str]:
    """
    List all tables in the specified database connection.
    
    Args:
        connection_name (str): The name of the database connection as defined in the configuration.
    
    Returns:
        list[str]: A list of table names available in the specified connection.
    
    Raises:
        ValueError: If the specified connection name does not exist in the configuration.
    """
    return read_tools.list_tables(_conn_manager, connection_name)

@mcp.tool
@requires_policy(AccessLevel.READ, read_extractor)
def describe_table(connection_name : str, table_name : str) -> dict:
    """
    Retrieve the schema of a specific table in the specified database connection.
    
    Args:
        connection_name (str): The name of the database connection as defined in the configuration.
        table_name (str): The name of the table whose schema is to be retrieved.
    
    Returns:
        dict: A dictionary containing the table name and its columns' details.
    
    Raises:
        ValueError: If the specified connection name does not exist in the configuration.
    """
    return read_tools.schema_table(_conn_manager, connection_name, table_name)

@mcp.tool
@requires_policy(AccessLevel.READ, read_extractor)
def list_rows(
    connection_name: str,
    table_name: str,
    after_cursor: str | None = None,
    limit: int = 50,
) -> dict:
    """
    List rows from a specific table in the specified database connection,
    paginated by cursor.

    Pagination uses keyset (cursor on a unique column) whenever the table
    has a single-column primary key, unique constraint, or unique index.
    If none is found, it falls back to offset-based pagination — slower
    and less stable under concurrent writes, but keeps the tool usable on
    any table. Check "pagination_mode" in the response to know which was used.

    Args:
        connection_name (str): The name of the database connection as defined in the configuration.
        table_name (str): The name of the table from which to retrieve rows.
        after_cursor (str, optional): Opaque cursor returned by a previous call, to fetch the next page.
        limit (int, optional): The maximum number of rows to retrieve. Defaults to 50.

    Returns:
        dict: {
            "rows": list[dict],
            "next_cursor": str | None,   # None when there is no further page
            "pagination_mode": "keyset" | "offset",
        }

    Raises:
        ValueError: If the connection is unknown, the table has a composite primary key,
            or the limit exceeds the maximum allowed value.
    """
    return read_tools.list_rows(_conn_manager, connection_name, table_name, after_cursor, limit)


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)