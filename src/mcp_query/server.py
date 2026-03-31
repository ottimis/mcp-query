"""MCP server with database query tools."""

from __future__ import annotations

import json
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import audit, db
from .config import load_config

mcp = FastMCP("mcp-query")


def _json_serialize(obj: Any) -> Any:
    """Handle non-serializable types."""
    import datetime
    import decimal
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    if isinstance(obj, datetime.timedelta):
        return str(obj)
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    if isinstance(obj, bytes):
        return obj.hex()
    if isinstance(obj, set):
        return list(obj)
    return str(obj)


def _format_result(result: dict[str, Any]) -> str:
    """Format a query result as readable text for Claude."""
    if result["status"] == "denied":
        return f"DENIED: {result['error']}"

    if result["status"] == "error":
        return f"ERROR: {result['error']}"

    if result["query_type"] in ("SELECT", "SHOW", "DESCRIBE", "DESC", "EXPLAIN", "WITH"):
        rows = result["rows"]
        if not rows:
            return "Query returned 0 rows."

        # Format as table
        columns = result["columns"]
        lines = [" | ".join(str(c) for c in columns)]
        lines.append("-" * len(lines[0]))
        for row in rows:
            lines.append(" | ".join(str(row.get(c, "")) for c in columns))

        footer = f"\n({result['rows_affected']} rows, {result['execution_ms']}ms)"
        return "\n".join(lines) + footer

    return (
        f"{result['query_type']} OK: {result['rows_affected']} rows affected "
        f"({result['execution_ms']}ms)"
    )


@mcp.tool()
def list_connections() -> str:
    """List all configured database connections with their driver, database, and permission level."""
    config = load_config()

    if not config.connections:
        return "No connections configured. Add connections to ~/.mcp-query/config.yaml"

    lines = []
    for name, conn in config.connections.items():
        pw_status = "password set" if conn.has_password() else "NO PASSWORD"
        perms = conn.permissions_display()
        if conn.driver == "sqlite":
            lines.append(
                f"- {name}: {conn.driver} | {conn.database} | "
                f"permissions=[{perms}] | max_rows={conn.max_rows}"
            )
        else:
            lines.append(
                f"- {name}: {conn.driver} | {conn.user}@{conn.host}:{conn.effective_port()}/{conn.database} | "
                f"permissions=[{perms}] | max_rows={conn.max_rows} | {pw_status}"
            )
    return "\n".join(lines)


@mcp.tool()
def list_tables(connection: str) -> str:
    """List all tables in a database.

    Args:
        connection: Name of the database connection to use.
    """
    config = load_config()
    conn_config = config.get_connection(connection)

    sql = db.list_tables_query(conn_config)
    result = db.execute_query(conn_config, sql)

    audit.log_query(
        connection=connection,
        sql=sql,
        query_type=result["query_type"],
        permission=conn_config.permissions,
        status=result["status"],
        rows_affected=result["rows_affected"],
        execution_ms=result["execution_ms"],
        error=result.get("error"),
    )

    if result["status"] != "ok":
        return f"Error: {result['error']}"

    tables = []
    for row in result["rows"]:
        # Get first value from row (column name varies by driver)
        val = list(row.values())[0] if row else ""
        tables.append(str(val))

    if not tables:
        return "No tables found."

    return "\n".join(tables)


@mcp.tool()
def describe_table(connection: str, table: str) -> str:
    """Show the structure of a database table (columns, types, keys).

    Args:
        connection: Name of the database connection to use.
        table: Name of the table to describe.
    """
    config = load_config()
    conn_config = config.get_connection(connection)

    sql = db.describe_table_query(conn_config, table)
    result = db.execute_query(conn_config, sql)

    audit.log_query(
        connection=connection,
        sql=sql,
        query_type=result["query_type"],
        permission=conn_config.permissions,
        status=result["status"],
        rows_affected=result["rows_affected"],
        execution_ms=result["execution_ms"],
        error=result.get("error"),
    )

    return _format_result(result)


@mcp.tool()
def query(connection: str, sql: str) -> str:
    """Execute a SQL query on a database connection.

    The query type is checked against the connection's allowed operations.
    Permissions can be a preset (read, write, admin) or a custom list of
    allowed operations (e.g. [select, insert]).

    Multi-statement queries are blocked. SELECT queries have an automatic row limit.

    Args:
        connection: Name of the database connection to use.
        sql: The SQL query to execute.
    """
    config = load_config()
    conn_config = config.get_connection(connection)

    result = db.execute_query(conn_config, sql)

    audit.log_query(
        connection=connection,
        sql=sql,
        query_type=result["query_type"],
        permission=conn_config.permissions,
        status=result["status"],
        rows_affected=result["rows_affected"],
        execution_ms=result["execution_ms"],
        error=result.get("error"),
    )

    # Cleanup old logs periodically (on every 100th query, lightweight check)
    try:
        import random
        if random.randint(1, 100) == 1:
            audit.cleanup_old_logs(config.log_retention_days)
    except Exception:
        pass

    return _format_result(result)


@mcp.tool()
def query_log(connection: str = "", limit: int = 20) -> str:
    """Show recent query audit log entries.

    Args:
        connection: Filter by connection name (empty = all connections).
        limit: Maximum number of entries to return (default 20).
    """
    entries = audit.read_logs(
        connection=connection or None,
        limit=limit,
    )

    if not entries:
        return "No log entries found."

    lines = []
    for e in entries:
        status_icon = {"ok": "OK", "denied": "DENIED", "error": "ERR"}.get(e["status"], "?")
        error_part = f" | {e['error']}" if e.get("error") else ""
        sql_preview = e["sql"][:80] + ("..." if len(e["sql"]) > 80 else "")
        lines.append(
            f"[{e['ts'][:19]}] {status_icon} | {e['connection']} | "
            f"{e['query_type']} | {e['rows_affected']} rows | "
            f"{e['execution_ms']}ms | {sql_preview}{error_part}"
        )

    return "\n".join(lines)


def run_server() -> None:
    """Start the MCP server on stdio transport."""
    mcp.run(transport="stdio")
