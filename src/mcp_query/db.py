"""Database connections, query execution, and permission enforcement."""

from __future__ import annotations

import re
import time
from typing import Any

import sqlparse

from .config import ConnectionConfig

# All known query types (for validation)
KNOWN_QUERY_TYPES = {
    "SELECT", "SHOW", "DESCRIBE", "DESC", "EXPLAIN", "WITH",
    "INSERT", "UPDATE", "DELETE", "REPLACE",
    "CREATE", "ALTER", "DROP", "TRUNCATE", "GRANT", "REVOKE", "RENAME",
}

# DESC is an alias for DESCRIBE
QUERY_TYPE_ALIASES = {"DESC": "DESCRIBE"}


def detect_query_type(sql: str) -> str:
    """Detect the type of SQL statement using sqlparse."""
    parsed = sqlparse.parse(sql.strip())
    if not parsed:
        raise ValueError("Empty or invalid SQL")

    stmt = parsed[0]
    first_token = stmt.token_first(skip_cm=True, skip_ws=True)
    if first_token is None:
        raise ValueError("Cannot determine query type")

    return first_token.ttype and first_token.normalized or first_token.value.upper().split()[0]


def check_permission(sql: str, config: ConnectionConfig) -> tuple[str, bool, str]:
    """Check if a query is allowed given the connection's permissions.

    Returns: (query_type, allowed, reason)
    """
    # Block multi-statement queries
    statements = [s for s in sqlparse.split(sql) if s.strip()]
    if len(statements) > 1:
        return "MULTI", False, "Multi-statement queries are not allowed"

    query_type = detect_query_type(sql)

    if query_type not in KNOWN_QUERY_TYPES:
        return query_type, False, f"Unknown query type: {query_type}"

    # Normalize aliases (DESC -> DESCRIBE)
    normalized = QUERY_TYPE_ALIASES.get(query_type, query_type)

    if config.is_operation_allowed(normalized):
        return query_type, True, "OK"

    allowed = config.permissions_display()
    return query_type, False, (
        f"{query_type} is not allowed. Permitted operations: {allowed}"
    )


def apply_row_limit(sql: str, max_rows: int) -> str:
    """Add LIMIT to SELECT queries if not already present."""
    query_type = detect_query_type(sql)
    if query_type != "SELECT" and query_type != "WITH":
        return sql

    # Check if LIMIT is already present (simple regex, works for most cases)
    if re.search(r'\bLIMIT\s+\d+', sql, re.IGNORECASE):
        return sql

    return f"{sql.rstrip().rstrip(';')} LIMIT {max_rows}"


def get_connection(config: ConnectionConfig) -> Any:
    """Create a database connection based on driver type."""
    password = config.get_password() or ""

    if config.driver == "mysql":
        import pymysql
        return pymysql.connect(
            host=config.host,
            port=config.effective_port(),
            user=config.user,
            password=password,
            database=config.database,
            connect_timeout=config.timeout,
            read_timeout=config.timeout,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )

    elif config.driver == "pgsql":
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(
            host=config.host,
            port=config.effective_port(),
            user=config.user,
            password=password,
            dbname=config.database,
            connect_timeout=config.timeout,
        )
        conn.autocommit = True
        return conn

    elif config.driver == "sqlite":
        import sqlite3
        conn = sqlite3.connect(config.database, timeout=config.timeout)
        conn.row_factory = sqlite3.Row
        return conn

    else:
        raise ValueError(f"Unsupported driver: {config.driver}")


def execute_query(config: ConnectionConfig, sql: str) -> dict[str, Any]:
    """Execute a query with permission checks and row limits.

    Returns a dict with: query_type, rows, columns, rows_affected, execution_ms, status, error
    """
    # Check permissions
    query_type, allowed, reason = check_permission(sql, config)
    if not allowed:
        return {
            "query_type": query_type,
            "status": "denied",
            "error": reason,
            "rows": [],
            "columns": [],
            "rows_affected": 0,
            "execution_ms": 0,
        }

    # Apply row limit for SELECT queries
    effective_sql = apply_row_limit(sql, config.max_rows)

    conn = None
    try:
        start = time.monotonic()
        conn = get_connection(config)

        if config.driver == "pgsql":
            import psycopg2.extras
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        else:
            cursor = conn.cursor()

        cursor.execute(effective_sql)
        elapsed_ms = round((time.monotonic() - start) * 1000, 2)

        # Fetch results for SELECT-type queries
        if query_type in ("SELECT", "SHOW", "DESCRIBE", "DESC", "EXPLAIN", "WITH"):
            rows_raw = cursor.fetchall()
            if config.driver == "sqlite":
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                rows = [dict(zip(columns, row)) for row in rows_raw]
            elif config.driver == "pgsql":
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                rows = [dict(r) for r in rows_raw]
            else:
                rows = [dict(r) for r in rows_raw]
                columns = list(rows[0].keys()) if rows else (
                    [desc[0] for desc in cursor.description] if cursor.description else []
                )
            return {
                "query_type": query_type,
                "status": "ok",
                "error": None,
                "rows": rows,
                "columns": columns,
                "rows_affected": len(rows),
                "execution_ms": elapsed_ms,
            }
        else:
            # DML/DDL
            affected = cursor.rowcount if cursor.rowcount >= 0 else 0
            if config.driver != "pgsql":
                conn.commit()
            return {
                "query_type": query_type,
                "status": "ok",
                "error": None,
                "rows": [],
                "columns": [],
                "rows_affected": affected,
                "execution_ms": elapsed_ms,
            }

    except Exception as e:
        elapsed_ms = round((time.monotonic() - start) * 1000, 2) if 'start' in dir() else 0
        return {
            "query_type": query_type,
            "status": "error",
            "error": str(e),
            "rows": [],
            "columns": [],
            "rows_affected": 0,
            "execution_ms": elapsed_ms,
        }
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def list_tables_query(config: ConnectionConfig) -> str:
    """Return the SQL to list tables for the given driver."""
    if config.driver == "mysql":
        return "SHOW TABLES"
    elif config.driver == "pgsql":
        return (
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name"
        )
    elif config.driver == "sqlite":
        return "SELECT name AS table_name FROM sqlite_master WHERE type='table' ORDER BY name"
    raise ValueError(f"Unsupported driver: {config.driver}")


def describe_table_query(config: ConnectionConfig, table: str) -> str:
    """Return the SQL to describe a table for the given driver."""
    # Validate table name to prevent injection
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_.]*$', table):
        raise ValueError(f"Invalid table name: {table}")

    if config.driver == "mysql":
        return f"DESCRIBE `{table}`"
    elif config.driver == "pgsql":
        return (
            f"SELECT column_name, data_type, is_nullable, column_default, "
            f"character_maximum_length "
            f"FROM information_schema.columns "
            f"WHERE table_name = '{table}' AND table_schema = 'public' "
            f"ORDER BY ordinal_position"
        )
    elif config.driver == "sqlite":
        return f"PRAGMA table_info({table})"
    raise ValueError(f"Unsupported driver: {config.driver}")


def test_connection(config: ConnectionConfig) -> dict[str, Any]:
    """Test if a database connection works."""
    conn = None
    try:
        start = time.monotonic()
        conn = get_connection(config)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        elapsed_ms = round((time.monotonic() - start) * 1000, 2)
        return {"status": "ok", "message": f"Connected in {elapsed_ms}ms"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
