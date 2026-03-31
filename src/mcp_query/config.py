"""Configuration loading and Keychain integration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import keyring
import yaml

CONFIG_DIR = Path.home() / ".mcp-query"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
KEYCHAIN_SERVICE = "mcp-query"


# Shorthand permission presets
PERMISSION_PRESETS: dict[str, list[str]] = {
    "read": ["select", "show", "describe", "explain", "with"],
    "write": ["select", "show", "describe", "explain", "with", "insert", "update", "delete", "replace"],
    "admin": [
        "select", "show", "describe", "explain", "with",
        "insert", "update", "delete", "replace",
        "create", "alter", "drop", "truncate", "grant", "revoke", "rename",
    ],
}


def resolve_permissions(raw: str | list[str]) -> list[str]:
    """Resolve permissions from shorthand or explicit list."""
    if isinstance(raw, str):
        if raw in PERMISSION_PRESETS:
            return PERMISSION_PRESETS[raw]
        # Single operation like "select"
        return [raw.lower()]
    return [p.lower() for p in raw]


@dataclass
class ConnectionConfig:
    name: str
    driver: str  # mysql | pgsql | sqlite
    host: str = "localhost"
    port: int | None = None
    database: str = ""
    user: str = ""
    permissions: str | list[str] = "read"  # shorthand or list of operations
    max_rows: int = 500
    timeout: int = 30

    def allowed_operations(self) -> list[str]:
        return resolve_permissions(self.permissions)

    def is_operation_allowed(self, operation: str) -> bool:
        return operation.lower() in self.allowed_operations()

    def permissions_display(self) -> str:
        """Human-readable permission string."""
        if isinstance(self.permissions, str) and self.permissions in PERMISSION_PRESETS:
            return self.permissions
        ops = self.allowed_operations()
        return ", ".join(ops)

    def default_port(self) -> int:
        return {"mysql": 3306, "pgsql": 5432}.get(self.driver, 0)

    def effective_port(self) -> int:
        return self.port or self.default_port()

    def get_password(self) -> str | None:
        return keyring.get_password(KEYCHAIN_SERVICE, self.name)

    def set_password(self, password: str) -> None:
        keyring.set_password(KEYCHAIN_SERVICE, self.name, password)

    def delete_password(self) -> None:
        try:
            keyring.delete_password(KEYCHAIN_SERVICE, self.name)
        except keyring.errors.PasswordDeleteError:
            pass

    def has_password(self) -> bool:
        return self.get_password() is not None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"driver": self.driver}
        if self.driver != "sqlite":
            d["host"] = self.host
            if self.port:
                d["port"] = self.port
            d["user"] = self.user
        d["database"] = self.database
        # Save as shorthand if it matches a preset, otherwise as list
        if isinstance(self.permissions, str) and self.permissions in PERMISSION_PRESETS:
            d["permissions"] = self.permissions
        elif isinstance(self.permissions, list):
            d["permissions"] = self.permissions
        else:
            d["permissions"] = self.permissions
        d["max_rows"] = self.max_rows
        if self.timeout != 30:
            d["timeout"] = self.timeout
        return d


@dataclass
class AppConfig:
    connections: dict[str, ConnectionConfig] = field(default_factory=dict)
    default_max_rows: int = 500
    default_permissions: str = "read"
    log_retention_days: int = 30

    def get_connection(self, name: str) -> ConnectionConfig:
        if name not in self.connections:
            available = ", ".join(self.connections.keys()) or "(none)"
            raise ValueError(f"Connection '{name}' not found. Available: {available}")
        return self.connections[name]


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (CONFIG_DIR / "logs").mkdir(exist_ok=True)


def load_config() -> AppConfig:
    ensure_config_dir()

    if not CONFIG_FILE.exists():
        return AppConfig()

    with open(CONFIG_FILE) as f:
        raw = yaml.safe_load(f) or {}

    defaults = raw.get("defaults", {})
    default_max_rows = defaults.get("max_rows", 500)
    default_permissions = defaults.get("permissions", "read")
    log_retention_days = defaults.get("log_retention_days", 30)

    connections: dict[str, ConnectionConfig] = {}
    for name, cfg in raw.get("connections", {}).items():
        connections[name] = ConnectionConfig(
            name=name,
            driver=cfg.get("driver", "mysql"),
            host=cfg.get("host", "localhost"),
            port=cfg.get("port"),
            database=cfg.get("database", ""),
            user=cfg.get("user", ""),
            permissions=cfg.get("permissions", default_permissions),
            max_rows=cfg.get("max_rows", default_max_rows),
            timeout=cfg.get("timeout", 30),
        )

    return AppConfig(
        connections=connections,
        default_max_rows=default_max_rows,
        default_permissions=default_permissions,
        log_retention_days=log_retention_days,
    )


def save_config(config: AppConfig) -> None:
    ensure_config_dir()

    raw: dict[str, Any] = {
        "defaults": {
            "max_rows": config.default_max_rows,
            "permissions": config.default_permissions,
            "log_retention_days": config.log_retention_days,
        },
        "connections": {},
    }

    for name, conn in config.connections.items():
        raw["connections"][name] = conn.to_dict()

    with open(CONFIG_FILE, "w") as f:
        yaml.dump(raw, f, default_flow_style=False, sort_keys=False)


def add_connection(config: AppConfig, name: str, **kwargs: Any) -> ConnectionConfig:
    conn = ConnectionConfig(name=name, **kwargs)
    config.connections[name] = conn
    save_config(config)
    return conn


def remove_connection(config: AppConfig, name: str) -> None:
    if name in config.connections:
        config.connections[name].delete_password()
        del config.connections[name]
        save_config(config)
