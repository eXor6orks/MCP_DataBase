"""
TODO : integrate the validation of the database type
and version to ensure compatibility with the application.
See : https://docs.sqlalchemy.org/en/21/dialects/index.html
for more information.
"""

import os
import re
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError, field_validator

_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")

class ConfigError(Exception):
    """Custom exception for configuration errors."""

class ConnectionConfig(BaseModel):
    url: str
    description: str

class AppConfig(BaseModel):
    connections: dict[str, ConnectionConfig]

    @field_validator("connections")
    @classmethod
    def validate_connections(cls, v):
        if not v:
            raise ValueError("Connections dictionary cannot be empty")
        return v

def _subs_env_vars(value: str) -> str:
    """Substitute environment variables in the given string."""
    def replace(match: re.Match) -> str:
        var_name = match.group(1)
        value = os.environ.get(var_name)
        if not value:
            raise ConfigError(
                f"Variable d'environnement '{var_name}' référencée dans config.yaml "
                f"mais absente ou vide (vérifie ton fichier .env)."
            )
        return value

    return _ENV_VAR_PATTERN.sub(replace, value)

def load_config(
        config_path: str | Path = "config/config.yaml",
        env_file: str |Path | None = ".env",
    ) -> AppConfig:
    if env_file and Path(env_file).exists():
        load_dotenv(env_file)

    config_path = Path(config_path)
    if not config_path.exists():
        raise ConfigError(f"Fichier de configuration '{config_path}' introuvable.")

    raw_text = config_path.read_text(encoding="utf-8")
    resolved_text = _subs_env_vars(raw_text)
    raw_data = yaml.safe_load(resolved_text)

    try:
        return AppConfig.model_validate(raw_data)
    except ValidationError as e:
        raise ConfigError(f"Erreur de validation de la configuration: {e}") from e