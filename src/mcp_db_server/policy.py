from datetime import datetime
import os
import re
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError, field_validator, model_validator

class PolicyException(Exception):
    """Custom exception for policy errors."""

class NotFoundPolicyException(PolicyException):
    """Raised when a policy is not found."""

class InvalidPolicyException(PolicyException):
    """Raised when a policy is invalid."""

class ConnectionPolicy(BaseModel):
    # Permissions
    readOnly: bool = True
    write: bool = False
    update: bool = False
    delete: bool = False
    # Additional metadata
    description: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def check_coherence(self):
        if self.readOnly and (self.write or self.update or self.delete):
            raise ValueError("readOnly=true est incompatible avec write/update/delete")
        return self

class AppPolicy(BaseModel):
    connections: dict[str, ConnectionPolicy]

def create_policy_file():
    """Create a default policy file if it doesn't exist."""
    pass

def create_policy_database_element():
    """Create a default policy database element if it doesn't exist."""
    pass

def read_policy_file(policy_path : str | Path | None = "config/policy.yaml") -> AppPolicy:
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
        policy_path: str | Path | None = "config/policy.yaml"
    ) -> AppPolicy:
    try:
        return read_policy_file(policy_path)
    except NotFoundPolicyException as e:
        create_policy_file()
        raise PolicyException(f"Policy file not found. A default policy file has been created at '{policy_path}'. Please review and update it as necessary.") from e
    except (InvalidPolicyException, TypeError) as e:
        raise PolicyException(f"Error loading policy: {e}") from e
