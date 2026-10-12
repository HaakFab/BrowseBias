#!/usr/bin/env python3
"""
BrowseBias — Collector Web GUI Launcher
========================================
A lightweight, zero-dependency, cross-platform local web GUI for running
the Autocomplete Bias user input simulator & collector on macOS, Windows, and Linux.

Automatically launches the user's default browser on start.
"""

import http.server
import json
import os
import signal
import socketserver
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PLUGIN_DIR = (BASE_DIR.parent / "plugin").resolve()
KEYWORDS_DIR = BASE_DIR

# Global State
collector_proc = None
collector_logs = []
collector_state = {
    "status": "idle",  # idle, running, stopped, error
    "current_keyword": "",
    "total_keywords": 0,
    "completed_keywords": 0,
    "pid": None,
    "start_time": None
}
state_lock = threading.Lock()


def append_log(line: str):
    with state_lock:
        collector_logs.append(line)
        if len(collector_logs) > 1000:
            collector_logs.pop(0)

        # Parse simple progress lines from collector output
        # e.g., "[12/50] Typing 'Olaf Scholz'..."
        if "Typing" in line or "Keyword" in line:
            collector_state["current_keyword"] = line.strip()


def run_collector_process(cmd_args: list):
    global collector_proc
    append_log(f"🚀 Starting Collector with: {' '.join(cmd_args)}")

    try:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        collector_proc = subprocess.Popen(
            cmd_args,
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env
        )

        with state_lock:
            collector_state["status"] = "running"
            collector_state["pid"] = collector_proc.pid
            collector_state["start_time"] = time.time()

        for line in iter(collector_proc.stdout.readline, ""):
            if not line:
                break
            append_log(line.rstrip())

        collector_proc.stdout.close()
        return_code = collector_proc.wait()

        with state_lock:
            collector_state["status"] = "idle" if return_code == 0 else "stopped"
            collector_state["pid"] = None
        append_log(f"⏹ Collector process exited with code {return_code}")
    except Exception as e:
        with state_lock:
            collector_state["status"] = "error"
            collector_state["pid"] = None
        append_log(f"❌ Failed to run collector: {e}")


def stop_collector_process():
    global collector_proc
    if collector_proc and collector_proc.poll() is None:
        append_log("🛑 Stopping collector process...")
        try:
            collector_proc.terminate()
            collector_proc.wait(timeout=3)
        except Exception:
            collector_proc.kill()
        with state_lock:
            collector_state["status"] = "idle"
            collector_state["pid"] = None
        append_log("✅ Collector stopped.")


class CollectorHTTPHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(GUI_HTML.encode("utf-8"))
        elif path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            with state_lock:
                resp = {
                    **collector_state,
                    "extension_found": (PLUGIN_DIR / "manifest.json").exists(),
                    "extension_path": str(PLUGIN_DIR),
                    "log_count": len(collector_logs)
                }
            self.wfile.write(json.dumps(resp).encode("utf-8"))
        elif path == "/api/logs":
            params = urllib.parse.parse_qs(parsed.query)
            since = int(params.get("since", [0])[0])
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            with state_lock:
                lines = collector_logs[since:]
                resp = {
                    "logs": lines,
                    "next_idx": len(collector_logs)
                }
            self.wfile.write(json.dumps(resp).encode("utf-8"))
        elif path == "/api/presets":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            presets = []
            for f in BASE_DIR.glob("*.txt"):
                presets.append(f.name)
            self.wfile.write(json.dumps({"presets": sorted(presets)}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        path = self.path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        data = json.loads(body) if body else {}

        if path == "/api/start":
            with state_lock:
                if collector_state["status"] == "running":
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "Collector already running"}).encode("utf-8"))
                    return

            # Build command args
            cmd = [sys.executable, str(BASE_DIR / "collector.py")]

            # Keywords handling
            keyword_mode = data.get("keyword_mode", "preset")
            if keyword_mode == "custom":
                custom_text = data.get("custom_keywords", "").strip()
                custom_file = BASE_DIR / "custom_keywords.txt"
                with open(custom_file, "w", encoding="utf-8") as f:
                    f.write(custom_text)
                cmd.extend(["-k", str(custom_file)])
            else:
                preset_name = data.get("preset_name", "keywords.txt")
                cmd.extend(["-k", str(BASE_DIR / preset_name)])

            # URL
            url = data.get("url", "https://www.google.de")
            cmd.extend(["-u", url])

            # Typos
            typos = int(data.get("typos", 0))
            cmd.extend(["-t", str(typos)])

            # Pause
            pause = str(data.get("pause", 1.5))
            cmd.extend(["--pause", pause])

            # Alphabet
            if not data.get("alphabet", True):
                cmd.append("--no-alphabet")

            # Run in background thread
            t = threading.Thread(target=run_collector_process, args=(cmd,), daemon=True)
            t.start()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "started"}).encode("utf-8"))

        elif path == "/api/stop":
            stop_collector_process()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "stopped"}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Silence access logs to keep terminal quiet
        pass


GUI_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BrowseBias Collector — Easy GUI (v1.1.0 Silurian)</title>
    <style>
        :root {
            --bg-base: #0d1117;
            --bg-surface: #161b22;
            --bg-elevated: #21262d;
            --border-default: #30363d;
            --text-primary: #f0f6fc;
            --text-secondary: #8b949e;
            --accent-blue: #58a6ff;
            --accent-green: #3fb950;
            --accent-red: #f85149;
            --accent-yellow: #d29922;
            --font-main: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            --font-mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace;
        }
        * { margin:0; padding:0; box-sizing:border-box; }
        body {
            background: var(--bg-base);
            color: var(--text-primary);
            font-family: var(--font-main);
            padding: 24px;
            font-size: 13px;
            line-height: 1.5;
            max-width: 900px;
            margin: 0 auto;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border-default);
            padding-bottom: 16px;
            margin-bottom: 20px;
        }
        .title-group h1 {
            font-size: 20px;
            font-weight: 700;
            color: #fff;
        }
        .title-group p {
            color: var(--text-secondary);
            font-size: 12px;
            margin-top: 2px;
        }
        .badge {
            display: inline-block;
            padding: 3px 8px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 600;
            font-family: var(--font-mono);
        }
        .badge-green { background: rgba(63,185,80,0.15); color: var(--accent-green); border: 1px solid rgba(63,185,80,0.3); }
        .badge-gray { background: rgba(139,148,158,0.15); color: var(--text-secondary); border: 1px solid var(--border-default); }
        .badge-red { background: rgba(248,81,73,0.15); color: var(--accent-red); border: 1px solid rgba(248,81,73,0.3); }
        .badge-yellow { background: rgba(210,153,34,0.15); color: var(--accent-yellow); border: 1px solid rgba(210,153,34,0.3); }

        .card {
            background: var(--bg-surface);
            border: 1px solid var(--border-default);
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 16px;
        }
        .card-title {
            font-size: 13px;
            font-weight: 600;
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .form-row {
            display: grid;
            grid-template-columns: 160px 1fr;
            gap: 12px;
            align-items: center;
            margin-bottom: 12px;
        }
        .form-label {
            color: var(--text-secondary);
            font-weight: 500;
        }
        .form-input, .form-select, .form-textarea {
            background: var(--bg-base);
            border: 1px solid var(--border-default);
            border-radius: 6px;
            color: var(--text-primary);
            padding: 7px 10px;
            font-size: 12.5px;
            outline: none;
            width: 100%;
        }
        .form-textarea {
            font-family: var(--font-mono);
            min-height: 80px;
            resize: vertical;
        }
        .form-input:focus, .form-select:focus, .form-textarea:focus {
            border-color: var(--accent-blue);
        }

        .actions-row {
            display: flex;
            gap: 10px;
            align-items: center;
            margin-top: 16px;
        }
        .btn {
            background: var(--bg-elevated);
            color: var(--text-primary);
            border: 1px solid var(--border-default);
            border-radius: 6px;
            padding: 8px 16px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            transition: all 0.15s ease;
        }
        .btn:hover { background: #30363d; }
        .btn-start {
            background: #238636;
            color: #fff;
            border-color: rgba(240,246,252,0.1);
        }
        .btn-start:hover { background: #2ea043; }
        .btn-stop {
            background: #da3633;
            color: #fff;
            border-color: rgba(240,246,252,0.1);
        }
        .btn-stop:hover { background: #f85149; }
        .btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        .console-box {
            background: #090d13;
            border: 1px solid var(--border-default);
            border-radius: 6px;
            font-family: var(--font-mono);
            font-size: 11.5px;
            padding: 12px;
            height: 260px;
            overflow-y: auto;
            color: #c9d1d9;
            white-space: pre-wrap;
            word-break: break-all;
        }

        .status-strip {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 8px 12px;
            background: var(--bg-elevated);
            border-radius: 6px;
            margin-bottom: 12px;
            font-size: 12px;
        }
        .link-row {
            display: flex;
            gap: 16px;
            margin-top: 16px;
            font-size: 12px;
        }
        .link-row a {
            color: var(--accent-blue);
            text-decoration: none;
        }
        .link-row a:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <div class="header">
        <div class="title-group">
            <h1>BrowseBias Collector — Runner GUI</h1>
            <p>Automated typing simulator with Autocomplete Bias Chrome extension</p>
        </div>
        <div>
            <span id="status-badge" class="badge badge-gray">● Idle</span>
        </div>
    </div>

    <!-- Status Strip -->
    <div class="status-strip">
        <div>
            <span>Extension Path: </span>
            <code id="ext-path" class="mono" style="color: var(--accent-blue);">Auto-detecting...</code>
        </div>
        <div id="ext-status">
            <span class="badge badge-gray">Checking...</span>
        </div>
    </div>

    <!-- Configuration Card -->
    <div class="card">
        <div class="card-title">
            <span>⚙️ Simulation Settings</span>
        </div>

        <div class="form-row">
            <label class="form-label">Keyword Source:</label>
            <div>
                <select id="keyword-mode" class="form-select" onchange="toggleKeywordMode(this.value)">
                    <option value="preset">Preset Keyword File</option>
                    <option value="custom">Custom Textarea Input</option>
                </select>
            </div>
        </div>

        <div class="form-row" id="row-preset">
            <label class="form-label">Preset File:</label>
            <div>
                <select id="preset-select" class="form-select">
                    <option value="keywords_bundestag.txt">keywords_bundestag.txt (Bundestag Politicians)</option>
                    <option value="keywords.txt">keywords.txt (General / German Topics)</option>
                </select>
            </div>
        </div>

        <div class="form-row" id="row-custom" style="display: none;">
            <label class="form-label">Custom Keywords:</label>
            <div>
                <textarea id="custom-keywords" class="form-textarea" placeholder="Enter one keyword per line, e.g.:&#10;Olaf Scholz&#10;Friedrich Merz&#10;Robert Habeck"></textarea>
            </div>
        </div>

        <div class="form-row">
            <label class="form-label">Google Domain:</label>
            <div>
                <select id="google-url" class="form-select">
                    <option value="https://www.google.de">https://www.google.de (Germany)</option>
                    <option value="https://www.google.com">https://www.google.com (US / Global)</option>
                    <option value="https://www.google.co.uk">https://www.google.co.uk (United Kingdom)</option>
                </select>
            </div>
        </div>

        <div class="form-row">
            <label class="form-label">Alphabet Cycle:</label>
            <div>
                <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                    <input type="checkbox" id="chk-alphabet" checked>
                    <span>Type trailing ' a'..' z' expansions to trigger exhaustive autocomplete</span>
                </label>
            </div>
        </div>

        <div class="form-row">
            <label class="form-label">Typo Permutations:</label>
            <div>
                <select id="typo-count" class="form-select">
                    <option value="0" selected>0 (Exact keywords only)</option>
                    <option value="1">1 typo per keyword</option>
                    <option value="2">2 typos per keyword</option>
                    <option value="3">3 typos per keyword</option>
                </select>
            </div>
        </div>

        <div class="form-row">
            <label class="form-label">Pause Between Queries:</label>
            <div>
                <select id="pause-seconds" class="form-select">
                    <option value="1.0">1.0 second (Fast)</option>
                    <option value="1.5" selected>1.5 seconds (Standard)</option>
                    <option value="2.5">2.5 seconds (Deliberate / Safe)</option>
                    <option value="4.0">4.0 seconds (Low detection risk)</option>
                </select>
            </div>
        </div>

        <div class="actions-row">
            <button id="btn-start" class="btn btn-start" onclick="startCollector()">
                ▶ Start Collection
            </button>
            <button id="btn-stop" class="btn btn-stop" onclick="stopCollector()" disabled>
                ⏹ Stop Collection
            </button>
        </div>
    </div>

    <!-- Live Console Output -->
    <div class="card">
        <div class="card-title">
            <span>💻 Live Simulator Output</span>
            <button class="btn" style="padding: 3px 8px; font-size: 11px;" onclick="clearConsole()">Clear Logs</button>
        </div>
        <div id="console-box" class="console-box">Waiting for simulation to start...</div>
    </div>

    <div class="link-row">
        <a href="http://localhost:8765" target="_blank">🌐 Open Research Server Console (Port 8765)</a>
        <span>·</span>
        <a href="http://localhost:8765/viewer" target="_blank">📂 Open Standalone Dataset Viewer</a>
    </div>

    <script>
        let logIndex = 0;
        let pollTimer = null;

        function toggleKeywordMode(mode) {
            document.getElementById('row-preset').style.display = (mode === 'preset') ? '' : 'none';
            document.getElementById('row-custom').style.display = (mode === 'custom') ? '' : 'none';
        }

        async function pollStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();

                const badge = document.getElementById('status-badge');
                if (data.status === 'running') {
                    badge.className = 'badge badge-green';
                    badge.textContent = '● Running (PID ' + data.pid + ')';
                    document.getElementById('btn-start').disabled = true;
                    document.getElementById('btn-stop').disabled = false;
                } else if (data.status === 'error') {
                    badge.className = 'badge badge-red';
                    badge.textContent = '● Error';
                    document.getElementById('btn-start').disabled = false;
                    document.getElementById('btn-stop').disabled = true;
                } else {
                    badge.className = 'badge badge-gray';
                    badge.textContent = '● Idle';
                    document.getElementById('btn-start').disabled = false;
                    document.getElementById('btn-stop').disabled = true;
                }

                document.getElementById('ext-path').textContent = data.extension_path || '—';
                const extStatus = document.getElementById('ext-status');
                if (data.extension_found) {
                    extStatus.innerHTML = '<span class="badge badge-green">✓ Extension Ready</span>';
                } else {
                    extStatus.innerHTML = '<span class="badge badge-red">✗ Missing Extension</span>';
                }

                // Poll logs
                pollLogs();
            } catch (e) {
                // Ignore transient network errors during startup
            }
        }

        async function pollLogs() {
            try {
                const res = await fetch('/api/logs?since=' + logIndex);
                const data = await res.json();
                if (data.logs && data.logs.length > 0) {
                    const box = document.getElementById('console-box');
                    if (logIndex === 0) box.textContent = '';
                    box.textContent += data.logs.join('\\n') + '\\n';
                    box.scrollTop = box.scrollHeight;
                    logIndex = data.next_idx;
                }
            } catch (e) {}
        }

        async function startCollector() {
            const mode = document.getElementById('keyword-mode').value;
            const payload = {
                keyword_mode: mode,
                preset_name: document.getElementById('preset-select').value,
                custom_keywords: document.getElementById('custom-keywords').value,
                url: document.getElementById('google-url').value,
                alphabet: document.getElementById('chk-alphabet').checked,
                typos: parseInt(document.getElementById('typo-count').value, 10),
                pause: parseFloat(document.getElementById('pause-seconds').value)
            };

            document.getElementById('btn-start').disabled = true;
            document.getElementById('console-box').textContent = 'Launching Playwright browser with Autocomplete Bias extension...\\n';
            logIndex = 0;

            const res = await fetch('/api/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (!res.ok) {
                const err = await res.json();
                alert('Failed to start: ' + (err.error || res.statusText));
                document.getElementById('btn-start').disabled = false;
            }
        }

        async function stopCollector() {
            document.getElementById('btn-stop').disabled = true;
            await fetch('/api/stop', { method: 'POST' });
        }

        function clearConsole() {
            document.getElementById('console-box').textContent = '';
        }

        // Start polling loop
        setInterval(pollStatus, 1500);
        pollStatus();
    </script>
</body>
</html>
"""

def main():
    port = int(os.environ.get("COLLECTOR_GUI_PORT", 8766))
    server = None
    for p in range(port, port + 10):
        try:
            server = socketserver.TCPServer(("127.0.0.1", p), CollectorHTTPHandler)
            port = p
            break
        except OSError:
            continue

    if not server:
        print("❌ Could not bind to any port between 8766 and 8776.")
        sys.exit(1)

    url = f"http://127.0.0.1:{port}"
    print("=" * 60)
    print("  BrowseBias — Collector Web GUI Launcher")
    print(f"  URL: {url}")
    print("=" * 60)
    print("  Opening browser automatically...")
    print("  Press Ctrl+C to terminate the GUI server.")
    print("=" * 60)

    # Auto-open browser
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nExiting Collector GUI...")
        stop_collector_process()
        server.server_close()


if __name__ == "__main__":
    main()
