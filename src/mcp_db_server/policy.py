"""
Policy management module for the MCP server.

Future evolutions:
    - Add support for user-specific policies.
    - Add support for role-based policies.
    - Add policies for database management at the
      table level (create, drop, etc.).
"""
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

from enum import Enum
from typing import Callable

"""
Exceptions section.

PolicyException: Base class for all policy-related exceptions.
NotFoundPolicyException: Raised when a policy file is not found.
InvalidPolicyException: Raised when a policy file is invalid or cannot be parsed.
PolicyDeniedException: Raised when an operation is denied by the policy.
"""

class PolicyException(Exception):
    """Custom exception for policy errors."""

class NotFoundPolicyException(PolicyException):
    """Raised when a policy is not found."""

class InvalidPolicyException(PolicyException):
    """Raised when a policy is invalid."""

class PolicyDeniedException(PolicyException):
    """Raised when an operation is denied by the policy."""

class AccessLevel(Enum):
    READ = "read"
    WRITE_DATA = "write_data"
    WRITE_SCHEMA = "write_schema"

_POLICY_REGISTRY: dict[str, tuple[AccessLevel, Callable[[dict], tuple[str, str]]]] = {}

_EXEMPT_TOOLS: set[str] = set()

def requires_policy(level: AccessLevel, extractor: Callable[[dict], tuple[str, str]]):
    """
    Decorator that registers a function with a specific access
    level.

    Args:
        level (AccessLevel): The access level required by the function.
        extractor (Callable[[dict], tuple[str, str]]): A function that extracts
            the connection name and the table name from the function's
            arguments.
    """
    def decorator(fn):
        _POLICY_REGISTRY[fn.__name__] = (level, extractor)
        return fn
    return decorator

def no_policy_check(fn):
    """
    Exempts a tool from the policy check. Reserved for pure discovery
    tools (connection/table names) that never access data or schema.
    """
    _EXEMPT_TOOLS.add(fn.__name__)
    return fn

def read_extractor(args: dict) -> tuple[str, str]:
    return args["connection_name"], args["table_name"]

class TablePolicy(BaseModel):
    read: bool = False
    write_data: bool = False
    write_schema: bool = False

class ConnectionPolicy(BaseModel):
    tables: dict[str, TablePolicy] = {}
    default: TablePolicy

class AppPolicy(BaseModel):
    connections: dict[str, ConnectionPolicy]

class Policy:
    """
    Class that manages and enforces policies for
    database operations, based on the provided
    AppPolicy configuration.
    """
    def __init__(self, app_policy: AppPolicy):
        self._app_policy = app_policy

    def _table_policy(self, connection_name: str, table_name: str) -> TablePolicy:
        conn_policy = self._app_policy.connections.get(connection_name)
        if conn_policy is None:
            raise PolicyDeniedException(f"Unknown connection in policy: '{connection_name}'")
        return conn_policy.tables.get(table_name, conn_policy.default)

    def check(self, connection_name: str, table_name: str, level: AccessLevel) -> None:
        table_policy = self._table_policy(connection_name, table_name)
        if not getattr(table_policy, level.value):
            raise PolicyDeniedException(
                f"Operation '{level.value}' denied on '{connection_name}.{table_name}'"
            )

def create_policy_file(
    connection_names: list[str],
    policy_path: str | Path = "config/policy.yaml",
) -> None:
    """Creates a closed-by-default policy file, with one entry per known connection."""
    default_policy = {
        "connections": {
            name: {
                "tables": {},
                "default": {"read": False, "write_data": False, "write_schema": False},
            }
            for name in connection_names
        }
    }
    policy_path = Path(policy_path)
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    with open(policy_path, "w", encoding="utf-8") as f:
        yaml.dump(default_policy, f, sort_keys=False)

def verify_policy_structure(app_policy: AppPolicy, connection_names: list[str]) -> None:
    """
    Checks that every known connection (from config.yaml) has an explicit
    entry in the policy. The 'default' of each existing entry is
    already mandatory thanks to the ConnectionPolicy model.

    Args:
        app_policy: The policy, already validated by pydantic.
        connection_names: The names of the connections actually configured.

    Raises:
        InvalidPolicyException: If a configured connection has no entry in policy.yaml.
    """
    missing = [name for name in connection_names if name not in app_policy.connections]
    if missing:
        raise InvalidPolicyException(
            f"Connections without an entry in policy.yaml: {', '.join(missing)}. "
            f"Every configured connection must have an explicit policy (at least 'default')."
        )

def read_policy_file(policy_path: str | Path | None = "config/policy.yaml") -> AppPolicy:
    policy_path = Path(policy_path)
    if not policy_path.exists():
        raise NotFoundPolicyException(f"Policy file '{policy_path}' not found.")

    raw_text = policy_path.read_text(encoding="utf-8")
    try:
        policy_dict = yaml.safe_load(raw_text)
        return AppPolicy.model_validate(policy_dict)
    except (yaml.YAMLError, ValidationError) as e:
        raise InvalidPolicyException(f"Error parsing policy file: {e}") from e

def load_policy(
    connection_names: list[str],
    policy_path: str | Path | None = "config/policy.yaml",
) -> AppPolicy:
    try:
        app_policy = read_policy_file(policy_path)
        verify_policy_structure(app_policy, connection_names)
        return app_policy
    except NotFoundPolicyException:
        create_policy_file(connection_names, policy_path)
        raise PolicyException(
            f"Policy file not found. A default (closed) policy file has been created at "
            f"'{policy_path}' for connections: {', '.join(connection_names)}. "
            f"Please review and update it as necessary."
        ) from None
    except (InvalidPolicyException, TypeError) as e:
        raise PolicyException(f"Error loading policy: {e}") from e
