"""CLI entry point for mcp-query."""

from __future__ import annotations

import argparse
import getpass
import sys


def cmd_serve(args: argparse.Namespace) -> None:
    from .server import run_server
    run_server()


def cmd_ui(args: argparse.Namespace) -> None:
    from .ui import run_ui
    run_ui(port=args.port, open_browser=not args.no_browser)


def cmd_list(args: argparse.Namespace) -> None:
    from .config import load_config

    config = load_config()
    if not config.connections:
        print("No connections configured.")
        print(f"Add connections to ~/.mcp-query/config.yaml or use: mcp-query ui")
        return

    for name, conn in config.connections.items():
        pw = "password set" if conn.has_password() else "NO PASSWORD"
        perms = conn.permissions_display()
        if conn.driver == "sqlite":
            print(f"  {name}: {conn.driver} | {conn.database} | "
                  f"permissions=[{perms}] | max_rows={conn.max_rows}")
        else:
            print(f"  {name}: {conn.driver} | {conn.user}@{conn.host}:{conn.effective_port()}/{conn.database} | "
                  f"permissions=[{perms}] | max_rows={conn.max_rows} | {pw}")


def cmd_set_password(args: argparse.Namespace) -> None:
    from .config import load_config

    config = load_config()
    try:
        conn = config.get_connection(args.connection)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    password = getpass.getpass(f"Password for '{args.connection}': ")
    if not password:
        print("Empty password, aborting.")
        sys.exit(1)

    conn.set_password(password)
    print(f"Password saved in Keychain for '{args.connection}'.")


def cmd_logs(args: argparse.Namespace) -> None:
    from . import audit

    entries = audit.read_logs(
        connection=args.connection,
        limit=args.limit,
    )

    if not entries:
        print("No log entries found.")
        return

    for e in entries:
        status = {"ok": "OK ", "denied": "DEN", "error": "ERR"}.get(e["status"], "???")
        ts = e["ts"][:19]
        sql_preview = e["sql"][:100] + ("..." if len(e["sql"]) > 100 else "")
        error_part = f" | {e['error']}" if e.get("error") else ""
        print(f"[{ts}] {status} | {e['connection']} | {e['query_type']} | "
              f"{e['rows_affected']} rows | {e['execution_ms']}ms | {sql_preview}{error_part}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mcp-query",
        description="Local MCP server for secure database queries",
    )
    sub = parser.add_subparsers(dest="command")

    # serve
    sub.add_parser("serve", help="Start MCP server (stdio transport)")

    # ui
    ui_parser = sub.add_parser("ui", help="Open web management UI")
    ui_parser.add_argument("--port", type=int, default=9847, help="UI port (default: 9847)")
    ui_parser.add_argument("--no-browser", action="store_true", help="Don't open browser")

    # list
    sub.add_parser("list", help="List configured connections")

    # set-password
    pw_parser = sub.add_parser("set-password", help="Set connection password in Keychain")
    pw_parser.add_argument("connection", help="Connection name")

    # logs
    logs_parser = sub.add_parser("logs", help="View query audit log")
    logs_parser.add_argument("-c", "--connection", default=None, help="Filter by connection")
    logs_parser.add_argument("-n", "--limit", type=int, default=20, help="Number of entries")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    commands = {
        "serve": cmd_serve,
        "ui": cmd_ui,
        "list": cmd_list,
        "set-password": cmd_set_password,
        "logs": cmd_logs,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
