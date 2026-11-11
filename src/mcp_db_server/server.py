from fastmcp import FastMCP
from typing import Any
import logging
import sys

from mcp_db_server.config import AppConfig, load_config, ConfigError
from mcp_db_server.policy import load_policy, PolicyException
from mcp_db_server.db.conn import ConnectionManager
from mcp_db_server.tools import read as read_tools
from mcp_db_server.tools.read import DEFAULT_LIMIT, FilterCondition
from mcp_db_server.policy import AccessLevel, no_policy_check, read_extractor, requires_policy
from mcp_db_server.middleware.PolicyMiddleware import PolicyMiddleware

from fastmcp.server.middleware.error_handling import ErrorHandlingMiddleware
from fastmcp.server.middleware.logging import LoggingMiddleware

"""Load logging process in server"""
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

"""Load configuration and policy files"""
try:
    config : AppConfig = load_config()
except ConfigError:
    logger.exception("Erreur de chargement de la configuration")
    raise SystemExit(1)

try:
    _policy = load_policy(connection_names=config.connections.keys())
except PolicyException as e:
    logger.exception(f"Error loading policy: {e}")
    raise SystemExit(1)


mcp = FastMCP("mcp-db-server")

mcp.add_middleware(ErrorHandlingMiddleware())
mcp.add_middleware(LoggingMiddleware())
mcp.add_middleware(PolicyMiddleware(_policy))

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
    limit: int = DEFAULT_LIMIT,
    filters: list[FilterCondition] | dict[str, Any] | None = None,
    columns: list[str] | None = None,
) -> dict:
    """
    List rows from a table, paginated by cursor, with optional filtering and column selection.

    Args:
        connection_name (str): The database connection name, as defined in the configuration.
        table_name (str): The table to read from.
        after_cursor (str, optional): Cursor from a previous call, to fetch the next page.
        limit (int, optional): Max rows to return. Defaults to 50.
        filters (optional): Either a simple dict for equality filters, e.g.
            {"status": "pending", "city": "Lyon"} — OR a list of conditions for
            comparisons, e.g. [{"column": "amount", "operator": "gt", "value": 1000}].
            Operators: eq, ne, gt, gte, lt, lte, like, in, is_null (=, >, contains, etc.
            are also accepted and normalized automatically).
        columns (list[str], optional): Subset of columns to return. Defaults to all.

    Returns:
        dict: {"rows": list[dict], "next_cursor": str | None, "pagination_mode": "keyset" | "offset"}

    Raises:
        ValueError: Unknown connection, unknown column/operator, composite PK, or limit too high.
    """
    return read_tools.list_rows(
        _conn_manager, connection_name, table_name, after_cursor, limit, filters, columns
    )


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)