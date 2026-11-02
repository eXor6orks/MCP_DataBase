from fastmcp import FastMCP

from mcp_db_server.config import AppConfig, load_config
from mcp_db_server.policy import load_policy
from mcp_db_server.db.conn import ConnectionManager
from mcp_db_server.tools import read as read_tools

try:
    config : AppConfig = load_config()
except Exception as e:
    print(f'Error loading configuration: {e}')
    raise SystemExit(1)

# try:
#     policy = load_policy()
# except Exception as e:
#     print(f'{e}')
#     raise SystemExit(1)

# print(policy.connections["mysql_test"])

mcp = FastMCP("mcp-db-server")

_conn_manager = ConnectionManager(config)

@mcp.tool
def list_connections() -> list[str]:
    """
    List all available database connections defined in the configuration.
    
    Returns:
        list[str]: A list of connection names.
    """
    return _conn_manager.names()

@mcp.tool
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