"""Web UI for managing connections, passwords, and viewing logs."""

from __future__ import annotations

import json
import threading
import webbrowser
from functools import partial
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import audit, db
from .config import (
    PERMISSION_PRESETS,
    AppConfig,
    ConnectionConfig,
    add_connection,
    load_config,
    remove_connection,
    save_config,
)

UI_PORT = 9847

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MCP Query - Database Manager</title>
<style>
  :root {
    --bg: #1a1b26; --bg2: #24283b; --bg3: #2f3346;
    --fg: #c0caf5; --fg2: #a9b1d6; --fg3: #565f89;
    --accent: #7aa2f7; --accent2: #bb9af7;
    --green: #9ece6a; --red: #f7768e; --orange: #e0af68;
    --border: #3b4261; --radius: 8px;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'SF Pro', system-ui, sans-serif;
    background: var(--bg); color: var(--fg); line-height: 1.6; }
  .container { max-width: 960px; margin: 0 auto; padding: 20px; }
  h1 { color: var(--accent); font-size: 1.5rem; margin-bottom: 4px; }
  .subtitle { color: var(--fg3); font-size: 0.85rem; margin-bottom: 24px; }
  .tabs { display: flex; gap: 8px; margin-bottom: 20px; }
  .tab { padding: 8px 18px; background: var(--bg2); color: var(--fg3); border: 1px solid var(--border);
    border-radius: var(--radius); cursor: pointer; font-size: 0.9rem; transition: all 0.2s; }
  .tab:hover { color: var(--fg); border-color: var(--accent); }
  .tab.active { background: var(--accent); color: var(--bg); border-color: var(--accent); font-weight: 600; }
  .panel { display: none; }
  .panel.active { display: block; }
  .card { background: var(--bg2); border: 1px solid var(--border); border-radius: var(--radius);
    padding: 16px; margin-bottom: 12px; }
  .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
  .card-title { font-weight: 600; color: var(--accent); }
  .card-meta { font-size: 0.82rem; color: var(--fg3); }
  .badge { padding: 2px 8px; border-radius: 12px; font-size: 0.75rem; font-weight: 600; }
  .badge-read { background: rgba(158,206,106,0.15); color: var(--green); }
  .badge-write { background: rgba(224,175,104,0.15); color: var(--orange); }
  .badge-admin { background: rgba(247,118,142,0.15); color: var(--red); }
  .badge-ok { background: rgba(158,206,106,0.15); color: var(--green); }
  .badge-denied { background: rgba(247,118,142,0.15); color: var(--red); }
  .badge-error { background: rgba(224,175,104,0.15); color: var(--orange); }
  .btn { padding: 6px 14px; border-radius: var(--radius); border: 1px solid var(--border);
    background: var(--bg3); color: var(--fg); cursor: pointer; font-size: 0.85rem; transition: all 0.2s; }
  .btn:hover { border-color: var(--accent); color: var(--accent); }
  .btn-primary { background: var(--accent); color: var(--bg); border-color: var(--accent); }
  .btn-primary:hover { opacity: 0.85; }
  .btn-danger { color: var(--red); border-color: var(--red); }
  .btn-danger:hover { background: var(--red); color: var(--bg); }
  .btn-sm { padding: 4px 10px; font-size: 0.8rem; }
  .btn-group { display: flex; gap: 6px; }
  input, select { padding: 8px 12px; background: var(--bg); color: var(--fg); border: 1px solid var(--border);
    border-radius: var(--radius); font-size: 0.9rem; width: 100%; }
  input:focus, select:focus { outline: none; border-color: var(--accent); }
  .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 16px; }
  .form-group { display: flex; flex-direction: column; gap: 4px; }
  .form-group label { font-size: 0.8rem; color: var(--fg3); text-transform: uppercase; letter-spacing: 0.5px; }
  .form-group.full { grid-column: 1 / -1; }
  .toast { position: fixed; bottom: 20px; right: 20px; padding: 12px 20px; border-radius: var(--radius);
    color: #fff; font-size: 0.9rem; opacity: 0; transition: opacity 0.3s; pointer-events: none; z-index: 100; }
  .toast.show { opacity: 1; }
  .toast-ok { background: #2d6a3d; }
  .toast-err { background: #8b2030; }
  .log-entry { font-family: 'SF Mono', Menlo, monospace; font-size: 0.8rem; padding: 8px 12px;
    background: var(--bg); border-radius: 4px; margin-bottom: 4px; border-left: 3px solid var(--border); }
  .log-entry.denied { border-left-color: var(--red); }
  .log-entry.error { border-left-color: var(--orange); }
  .log-sql { color: var(--fg2); margin-top: 4px; white-space: pre-wrap; word-break: break-all; }
  .log-meta { color: var(--fg3); }
  .filter-bar { display: flex; gap: 8px; margin-bottom: 16px; align-items: center; }
  .filter-bar select, .filter-bar input { width: auto; min-width: 160px; }
  .empty { text-align: center; color: var(--fg3); padding: 40px; }
  .pw-indicator { font-size: 0.8rem; }
  .pw-set { color: var(--green); }
  .pw-missing { color: var(--red); }
  .modal-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.6);
    z-index: 50; justify-content: center; align-items: center; }
  .modal-overlay.show { display: flex; }
  .modal { background: var(--bg2); border: 1px solid var(--border); border-radius: 12px;
    padding: 24px; width: 90%; max-width: 520px; }
  .modal h2 { color: var(--accent); font-size: 1.1rem; margin-bottom: 16px; }
</style>
</head>
<body>
<div class="container">
  <h1>MCP Query</h1>
  <p class="subtitle">Database connection manager &amp; query audit log</p>

  <div class="tabs">
    <div class="tab active" data-panel="connections">Connections</div>
    <div class="tab" data-panel="logs">Query Log</div>
  </div>

  <div id="connections" class="panel active">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <span id="conn-count" style="color:var(--fg3);font-size:0.85rem"></span>
      <button class="btn btn-primary" onclick="showAddModal()">+ Add Connection</button>
    </div>
    <div id="conn-list"></div>
  </div>

  <div id="logs" class="panel">
    <div class="filter-bar">
      <select id="log-conn-filter"><option value="">All connections</option></select>
      <select id="log-limit">
        <option value="20">Last 20</option>
        <option value="50">Last 50</option>
        <option value="100">Last 100</option>
      </select>
      <button class="btn btn-sm" onclick="loadLogs()">Refresh</button>
    </div>
    <div id="log-list"></div>
  </div>
</div>

<!-- Add/Edit Connection Modal -->
<div class="modal-overlay" id="conn-modal">
  <div class="modal">
    <h2 id="modal-title">Add Connection</h2>
    <input type="hidden" id="edit-original-name">
    <div class="form-grid">
      <div class="form-group">
        <label>Connection Name</label>
        <input id="f-name" placeholder="my-database">
      </div>
      <div class="form-group">
        <label>Driver</label>
        <select id="f-driver">
          <option value="mysql">MySQL</option>
          <option value="pgsql">PostgreSQL</option>
          <option value="sqlite">SQLite</option>
        </select>
      </div>
      <div class="form-group" id="g-host">
        <label>Host</label>
        <input id="f-host" value="localhost">
      </div>
      <div class="form-group" id="g-port">
        <label>Port</label>
        <input id="f-port" type="number" placeholder="auto">
      </div>
      <div class="form-group">
        <label>Database</label>
        <input id="f-database" placeholder="mydb">
      </div>
      <div class="form-group" id="g-user">
        <label>User</label>
        <input id="f-user" placeholder="root">
      </div>
      <div class="form-group">
        <label>Preset</label>
        <select id="f-preset" onchange="applyPreset()">
          <option value="read">Read</option>
          <option value="write">Write</option>
          <option value="admin">Admin</option>
          <option value="custom">Custom</option>
        </select>
      </div>
      <div class="form-group">
        <label>Max Rows</label>
        <input id="f-maxrows" type="number" value="500">
      </div>
      <div class="form-group full" id="g-operations">
        <label>Allowed Operations</label>
        <div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:4px" id="ops-grid"></div>
      </div>
      <div class="form-group full" id="g-password">
        <label>Password <span style="color:var(--fg3)">(saved in Apple Keychain)</span></label>
        <input id="f-password" type="password" placeholder="Leave empty to keep current">
      </div>
    </div>
    <div style="display:flex;gap:8px;justify-content:flex-end">
      <button class="btn" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="saveConnection()">Save</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
const API = '';

// Tabs
document.querySelectorAll('.tab').forEach(t => {
  t.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    document.getElementById(t.dataset.panel).classList.add('active');
    if (t.dataset.panel === 'logs') loadLogs();
  });
});

// Toast
function toast(msg, ok = true) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'toast show ' + (ok ? 'toast-ok' : 'toast-err');
  setTimeout(() => el.classList.remove('show'), 3000);
}

// API helper
async function api(path, opts = {}) {
  const res = await fetch(API + path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  return res.json();
}

// All available operations
const ALL_OPS = ['select','show','describe','explain','with','insert','update','delete','replace','create','alter','drop','truncate','grant','revoke','rename'];
const PRESETS = {
  read: ['select','show','describe','explain','with'],
  write: ['select','show','describe','explain','with','insert','update','delete','replace'],
  admin: ALL_OPS.slice(),
};
const OP_GROUPS = [
  { label: 'Read', ops: ['select','show','describe','explain','with'] },
  { label: 'Write', ops: ['insert','update','delete','replace'] },
  { label: 'DDL', ops: ['create','alter','drop','truncate','grant','revoke','rename'] },
];

// Build checkboxes
function buildOpsGrid() {
  const grid = document.getElementById('ops-grid');
  grid.innerHTML = OP_GROUPS.map(g =>
    `<div style="display:flex;flex-direction:column;gap:2px;min-width:120px;background:var(--bg);padding:8px;border-radius:6px">
      <strong style="font-size:0.75rem;color:var(--fg3);margin-bottom:2px">${g.label}</strong>
      ${g.ops.map(op => `<label style="display:flex;align-items:center;gap:4px;font-size:0.85rem;cursor:pointer">
        <input type="checkbox" class="op-check" value="${op}" onchange="onOpChange()"> ${op.toUpperCase()}
      </label>`).join('')}
    </div>`
  ).join('');
}
buildOpsGrid();

function getCheckedOps() {
  return [...document.querySelectorAll('.op-check:checked')].map(c => c.value);
}

function setCheckedOps(ops) {
  document.querySelectorAll('.op-check').forEach(c => {
    c.checked = ops.includes(c.value);
  });
}

function applyPreset() {
  const preset = document.getElementById('f-preset').value;
  if (preset !== 'custom') {
    setCheckedOps(PRESETS[preset]);
  }
}

function onOpChange() {
  // Check if current selection matches a preset
  const checked = getCheckedOps().sort().join(',');
  let matched = 'custom';
  for (const [name, ops] of Object.entries(PRESETS)) {
    if (ops.slice().sort().join(',') === checked) { matched = name; break; }
  }
  document.getElementById('f-preset').value = matched;
}

// Driver change handler
document.getElementById('f-driver').addEventListener('change', () => {
  const isSqlite = document.getElementById('f-driver').value === 'sqlite';
  ['g-host', 'g-port', 'g-user', 'g-password'].forEach(id => {
    document.getElementById(id).style.display = isSqlite ? 'none' : '';
  });
});

// Load connections
async function loadConnections() {
  const data = await api('/api/connections');
  const list = document.getElementById('conn-list');
  const filter = document.getElementById('log-conn-filter');

  filter.innerHTML = '<option value="">All connections</option>';

  if (!data.connections || data.connections.length === 0) {
    list.innerHTML = '<div class="empty">No connections configured yet.</div>';
    document.getElementById('conn-count').textContent = '';
    return;
  }

  document.getElementById('conn-count').textContent = `${data.connections.length} connection(s)`;

  list.innerHTML = data.connections.map(c => {
    const permLabel = Array.isArray(c.permissions) ? c.permissions.join(', ') : c.permissions;
    const permClass = typeof c.permissions === 'string' && PRESETS[c.permissions] ? 'badge-' + c.permissions : 'badge-write';
    const pwHtml = c.driver === 'sqlite' ? '' :
      (c.has_password
        ? '<span class="pw-indicator pw-set">Password set</span>'
        : '<span class="pw-indicator pw-missing">No password</span>');
    const connStr = c.driver === 'sqlite'
      ? c.database
      : `${c.user}@${c.host}:${c.port || 'auto'}/${c.database}`;

    return `<div class="card">
      <div class="card-header">
        <span class="card-title">${c.name}</span>
        <div class="btn-group">
          <button class="btn btn-sm" onclick="copyClaudeMd('${c.name}')" title="Copy CLAUDE.md snippet">Copy for CLAUDE.md</button>
          <button class="btn btn-sm" onclick="testConn('${c.name}')">Test</button>
          <button class="btn btn-sm" onclick="editConn('${c.name}')">Edit</button>
          <button class="btn btn-sm btn-danger" onclick="deleteConn('${c.name}')">Delete</button>
        </div>
      </div>
      <div class="card-meta">
        ${c.driver.toUpperCase()} &middot; ${connStr} &middot;
        <span class="badge ${permClass}">${permLabel}</span> &middot;
        max ${c.max_rows} rows &middot; ${pwHtml}
      </div>
    </div>`;
  }).join('');

  data.connections.forEach(c => {
    filter.innerHTML += `<option value="${c.name}">${c.name}</option>`;
  });
}

// Modal
function showAddModal() {
  document.getElementById('modal-title').textContent = 'Add Connection';
  document.getElementById('edit-original-name').value = '';
  ['f-name', 'f-database', 'f-user', 'f-password'].forEach(id =>
    document.getElementById(id).value = '');
  document.getElementById('f-host').value = 'localhost';
  document.getElementById('f-port').value = '';
  document.getElementById('f-driver').value = 'mysql';
  document.getElementById('f-preset').value = 'read';
  document.getElementById('f-maxrows').value = '500';
  applyPreset();
  document.getElementById('f-name').disabled = false;
  document.getElementById('f-driver').dispatchEvent(new Event('change'));
  document.getElementById('conn-modal').classList.add('show');
}

function closeModal() {
  document.getElementById('conn-modal').classList.remove('show');
}

async function editConn(name) {
  const data = await api('/api/connections');
  const c = data.connections.find(x => x.name === name);
  if (!c) return;

  document.getElementById('modal-title').textContent = 'Edit Connection';
  document.getElementById('edit-original-name').value = name;
  document.getElementById('f-name').value = c.name;
  document.getElementById('f-name').disabled = true;
  document.getElementById('f-driver').value = c.driver;
  document.getElementById('f-host').value = c.host || 'localhost';
  document.getElementById('f-port').value = c.port || '';
  document.getElementById('f-database').value = c.database;
  document.getElementById('f-user').value = c.user || '';
  // Set permissions: could be a preset string or a custom list
  if (typeof c.permissions === 'string' && PRESETS[c.permissions]) {
    document.getElementById('f-preset').value = c.permissions;
    setCheckedOps(PRESETS[c.permissions]);
  } else {
    const ops = Array.isArray(c.permissions) ? c.permissions : [c.permissions];
    setCheckedOps(ops);
    onOpChange();
  }
  document.getElementById('f-maxrows').value = c.max_rows;
  document.getElementById('f-password').value = '';
  document.getElementById('f-driver').dispatchEvent(new Event('change'));
  document.getElementById('conn-modal').classList.add('show');
}

async function saveConnection() {
  const name = document.getElementById('f-name').value.trim();
  if (!name) { toast('Name is required', false); return; }

  // Build permissions: use preset name if it matches, otherwise the list
  const preset = document.getElementById('f-preset').value;
  const checkedOps = getCheckedOps();
  let permissions;
  if (preset !== 'custom' && PRESETS[preset]) {
    const presetOps = PRESETS[preset].slice().sort().join(',');
    permissions = (checkedOps.sort().join(',') === presetOps) ? preset : checkedOps;
  } else {
    permissions = checkedOps;
  }

  const body = {
    name,
    driver: document.getElementById('f-driver').value,
    host: document.getElementById('f-host').value,
    port: parseInt(document.getElementById('f-port').value) || null,
    database: document.getElementById('f-database').value,
    user: document.getElementById('f-user').value,
    permissions,
    max_rows: parseInt(document.getElementById('f-maxrows').value) || 500,
    password: document.getElementById('f-password').value || null,
  };

  const res = await api('/api/connections', {
    method: 'POST',
    body: JSON.stringify(body),
  });

  if (res.status === 'ok') {
    toast('Connection saved');
    closeModal();
    loadConnections();
  } else {
    toast(res.error || 'Error saving', false);
  }
}

async function deleteConn(name) {
  if (!confirm(`Delete connection "${name}"? Password will also be removed from Keychain.`)) return;
  const res = await api(`/api/connections/${name}`, { method: 'DELETE' });
  if (res.status === 'ok') {
    toast('Connection deleted');
    loadConnections();
  } else {
    toast(res.error || 'Error', false);
  }
}

async function testConn(name) {
  toast('Testing...');
  const res = await api(`/api/test/${name}`, { method: 'POST' });
  toast(res.message, res.status === 'ok');
}

// Logs
async function loadLogs() {
  const conn = document.getElementById('log-conn-filter').value;
  const limit = document.getElementById('log-limit').value;
  const params = new URLSearchParams({ limit });
  if (conn) params.set('connection', conn);

  const data = await api(`/api/logs?${params}`);
  const list = document.getElementById('log-list');

  if (!data.entries || data.entries.length === 0) {
    list.innerHTML = '<div class="empty">No log entries found.</div>';
    return;
  }

  list.innerHTML = data.entries.map(e => {
    const statusClass = e.status === 'ok' ? '' : e.status;
    const ts = e.ts ? e.ts.substring(0, 19).replace('T', ' ') : '';
    const errHtml = e.error ? `<span style="color:var(--red)"> | ${e.error}</span>` : '';

    return `<div class="log-entry ${statusClass}">
      <div>
        <span class="log-meta">${ts}</span> &middot;
        <span class="badge badge-${e.status}">${e.status.toUpperCase()}</span> &middot;
        <strong>${e.connection}</strong> &middot;
        ${e.query_type} &middot;
        ${e.rows_affected} rows &middot;
        ${e.execution_ms}ms${errHtml}
      </div>
      <div class="log-sql">${escHtml(e.sql)}</div>
    </div>`;
  }).join('');
}

function escHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// Copy CLAUDE.md snippet
function copyClaudeMd(name) {
  const snippet = `## Database\nPer le query al database usare il tool MCP \`query\` con connessione \`${name}\`.`;
  navigator.clipboard.writeText(snippet).then(() => {
    toast('Copied to clipboard');
  }, () => {
    // Fallback for non-HTTPS contexts
    const ta = document.createElement('textarea');
    ta.value = snippet;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    toast('Copied to clipboard');
  });
}

// ESC to close modal
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeModal();
});

// Init
loadConnections();
</script>
</body>
</html>"""


class UIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the management UI."""

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress default logging
        pass

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "":
            self._send_html(HTML_PAGE)

        elif path == "/api/connections":
            config = load_config()
            connections = []
            for name, conn in config.connections.items():
                connections.append({
                    "name": name,
                    "driver": conn.driver,
                    "host": conn.host,
                    "port": conn.port,
                    "database": conn.database,
                    "user": conn.user,
                    "permissions": conn.permissions,
                    "max_rows": conn.max_rows,
                    "timeout": conn.timeout,
                    "has_password": conn.has_password(),
                })
            self._send_json({"connections": connections})

        elif path == "/api/logs":
            qs = parse_qs(parsed.query)
            connection = qs.get("connection", [None])[0]
            limit = int(qs.get("limit", [20])[0])
            date = qs.get("date", [None])[0]
            entries = audit.read_logs(connection=connection, limit=limit, date=date)
            self._send_json({"entries": entries})

        else:
            self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/connections":
            body = self._read_body()
            name = body.get("name", "").strip()
            if not name:
                self._send_json({"status": "error", "error": "Name required"}, 400)
                return

            config = load_config()

            kwargs: dict[str, Any] = {
                "driver": body.get("driver", "mysql"),
                "host": body.get("host", "localhost"),
                "port": body.get("port"),
                "database": body.get("database", ""),
                "user": body.get("user", ""),
                "permissions": body.get("permissions", config.default_permissions),
                "max_rows": body.get("max_rows", config.default_max_rows),
            }

            conn = add_connection(config, name, **kwargs)

            password = body.get("password")
            if password:
                conn.set_password(password)

            self._send_json({"status": "ok"})

        elif path.startswith("/api/test/"):
            conn_name = path.split("/api/test/", 1)[1]
            config = load_config()
            try:
                conn_config = config.get_connection(conn_name)
                result = db.test_connection(conn_config)
                self._send_json(result)
            except ValueError as e:
                self._send_json({"status": "error", "message": str(e)})

        else:
            self.send_error(404)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/connections/"):
            conn_name = path.split("/api/connections/", 1)[1]
            config = load_config()
            try:
                remove_connection(config, conn_name)
                self._send_json({"status": "ok"})
            except Exception as e:
                self._send_json({"status": "error", "error": str(e)}, 400)
        else:
            self.send_error(404)


def run_ui(port: int = UI_PORT, open_browser: bool = True) -> None:
    """Start the management web UI."""
    server = HTTPServer(("127.0.0.1", port), UIHandler)
    url = f"http://localhost:{port}"
    print(f"MCP Query UI running at {url}")

    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nUI server stopped.")
        server.server_close()
