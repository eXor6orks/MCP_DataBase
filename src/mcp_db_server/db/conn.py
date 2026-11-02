from sqlalchemy import Engine, create_engine

from mcp_db_server.config import AppConfig

POOL_SIZE = 5
MAX_OVERFLOW = 10
PRE_PING = True

class ConnectionManager:
    """
    Manages database connections based on the configuration.
    
    TODO : Integrate policy checks to ensure that connections
    adhere to the defined policies before allowing access.
    TODO : Implement connection pooling and reuse to optimize 
    resource usage.
    TODO : Add logging for connection creation, disposal, and
    errors to facilitate debugging and monitoring.
    """

    def __init__(self, config: AppConfig):
        self._config = config
        self._engines: dict[str, Engine] = {}

    def names(self) -> list[str]:
        return list(self._config.connections.keys())

    def get_engine(self, connection: str) -> Engine:
        if connection not in self._engines:
            try:
                conn_config = self._config.connections[connection]
            except KeyError:
                raise ValueError (
                    f"Connexion inconnue : '{connection}'. Disponibles : {', '.join(self.names())}"
                ) from None
            self._engines[connection] = create_engine(
                                            conn_config.url, 
                                            pool_size=POOL_SIZE, 
                                            max_overflow=MAX_OVERFLOW, 
                                            pool_pre_ping=PRE_PING
                                        )
        return self._engines[connection]

    def dispose(self) -> None:
        for engine in self._engines.values():
            engine.dispose()
        self._engines.clear()