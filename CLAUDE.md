# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**mcp-query** is a local MCP (Model Context Protocol) server that provides Claude Code with secure database access. Credentials are stored in the macOS Apple Keychain, permissions are enforced per-connection at the operation level, and all queries are logged for audit.

## Commands

```bash
# Install dependencies
uv sync

# Run the MCP server (stdio transport, called by Claude Code automatically)
uv run mcp-query serve

# Open the web management UI
uv run mcp-query ui

# List configured connections
uv run mcp-query list

# Set a connection password in Keychain
uv run mcp-query set-password <connection-name>

# View audit logs
uv run mcp-query logs
uv run mcp-query logs -c <connection> -n 50

# Test imports
uv run python -c "from mcp_query.server import run_server"
```

## Architecture

The server runs as a stdio MCP process spawned by Claude Code. A separate HTTP server (`ui`) provides a browser-based management interface.

```
Claude Code --stdio--> server.py (FastMCP, 5 tools)
                          |
                   config.py (YAML + Keychain)
                   db.py (connections + permissions + execution)
                   audit.py (JSONL logging)

Browser --> ui.py (HTTP :9847, embedded SPA)
               |
         config.py, db.py, audit.py (same modules)
```

### Module Responsibilities

| Module | Role |
|--------|------|
| `server.py` | FastMCP server, 5 tool definitions, result formatting |
| `config.py` | `ConnectionConfig`/`AppConfig` dataclasses, YAML load/save, Keychain via `keyring`, permission presets and resolution |
| `db.py` | `detect_query_type()` via sqlparse, `check_permission()` against connection's allowed ops, `execute_query()` pipeline, driver-specific SQL for list_tables/describe_table, `test_connection()` |
| `audit.py` | JSONL append to `~/.mcp-query/logs/queries-YYYY-MM-DD.jsonl`, read with filters, retention cleanup |
| `ui.py` | `BaseHTTPRequestHandler` with inline HTML/CSS/JS SPA, REST API endpoints under `/api/` |
| `__main__.py` | argparse CLI dispatching to serve/ui/list/set-password/logs |

### MCP Tools

| Tool | Purpose |
|------|---------|
| `list_connections()` | Show all configured connections with permissions and password status |
| `list_tables(connection)` | List database tables |
| `describe_table(connection, table)` | Column definitions, types, keys |
| `query(connection, sql)` | Execute SQL with permission check, row limit, audit log |
| `query_log(connection?, limit?)` | Read recent audit entries |

### Permission Model

Permissions can be a preset string or a granular list of allowed operations:

```yaml
permissions: read                    # preset: select, show, describe, explain, with
permissions: write                   # preset: read + insert, update, delete, replace
permissions: admin                   # preset: write + create, alter, drop, truncate, grant, revoke, rename
permissions: [select, insert]        # custom: only these operations
```

Resolution: `config.py:resolve_permissions()` expands presets via `PERMISSION_PRESETS` dict. Check: `db.py:check_permission()` compares detected query type against `ConnectionConfig.is_operation_allowed()`.

### Query Execution Pipeline (db.py:execute_query)

1. `check_permission()` - parse SQL with sqlparse, reject multi-statement, check operation against allowed list
2. `apply_row_limit()` - auto-add LIMIT to SELECT/WITH if missing
3. `get_connection()` - create driver-specific connection (PyMySQL DictCursor / psycopg2 RealDictCursor / sqlite3 Row)
4. Execute, fetch results as list[dict], close connection
5. Return standardized result dict with status/rows/columns/execution_ms

### Runtime Files

```
~/.mcp-query/
  config.yaml                    # Connection definitions (no passwords)
  logs/queries-YYYY-MM-DD.jsonl  # Daily audit log
```

Keychain entries: service=`mcp-query`, account=`<connection-name>`

## Key Design Decisions

- **Connections are not pooled**: each query opens and closes a connection. This is intentional since the server is idle most of the time.
- **Config is re-read from disk on every tool call** (`load_config()`), so changes via UI or manual edits are picked up immediately without restart.
- **PostgreSQL connections use autocommit=True**; MySQL/SQLite commit after DML explicitly.
- **Multi-statement queries are always blocked** regardless of permissions (sqlparse.split check).
- **Table name validation** uses regex `^[a-zA-Z_][a-zA-Z0-9_.]*$` to prevent injection in describe_table.
- **Log cleanup** runs probabilistically (1 in 100 queries) inside the `query` tool to avoid startup cost.
- **The Web UI is a single embedded HTML string** in `ui.py` - no build step, no external assets.
- **stdout must never be written to** in server mode (corrupts MCP stdio protocol). Use stderr for debug output.