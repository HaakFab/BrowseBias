"""
Autocomplete Bias — Research & Test Server
============================================
Backend server for autocomplete bias data collection, live reporting,
bias quantification engine orchestration, and web dashboard.

Features:
  1. Receiving scraped data uploads (POST /api/upload)
  2. Receiving user feedback & suggestion reports (POST /api/report)
  3. Serving numerical bias scores & lexicon (GET /api/lexicon, POST /api/score)
  4. Bias Rating Engine orchestration (POST /api/ratings/start, GET /api/ratings/status, GET /api/ratings/history)
  5. Interactive research dashboard with live rating monitor and category bias scores explorer (GET /)

Usage:
  pip install flask flask-cors
  python app.py
"""

import json
import os
import re
import sys
import threading
from datetime import datetime
import functools
from pathlib import Path

from flask import Flask, jsonify, request, render_template_string, send_from_directory, send_file, Response
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Allow cross-origin requests from the Chrome extension

# ─── Storage & Paths ────────────────────────────────────────────────
# Support Hugging Face Spaces persistent storage mount at /data
if os.path.isdir('/data') and os.access('/data', os.W_OK):
    DATA_DIR = '/data'
else:
    DATA_DIR = os.environ.get('DATA_DIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data'))

UPLOAD_FILE = os.path.join(DATA_DIR, 'uploads.jsonl')
SUGGESTIONS_FILE = os.path.join(DATA_DIR, 'suggestions.jsonl')
REPORTS_FILE = os.path.join(DATA_DIR, 'reports.jsonl')
LEXICON_FILE = os.path.join(DATA_DIR, 'lexicon.json')
ENGINE_STATE_DIR = os.path.join(DATA_DIR, 'engine_state')
TASK_JOURNAL_FILE = os.path.join(ENGINE_STATE_DIR, 'task_journal.jsonl')

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(ENGINE_STATE_DIR, exist_ok=True)

# ─── Admin Authentication ──────────────────────────────────────────
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '').strip()

def check_admin_auth():
    if not ADMIN_PASSWORD:
        return True  # If no ADMIN_PASSWORD set (e.g. local dev), allow open access
    auth = request.authorization
    if auth and (auth.password == ADMIN_PASSWORD or auth.username == ADMIN_PASSWORD):
        return True
    if request.headers.get('X-Admin-Key') == ADMIN_PASSWORD or request.args.get('admin_key') == ADMIN_PASSWORD:
        return True
    return False

def require_admin(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not check_admin_auth():
            return Response(
                'Admin authentication required for BrowseBias Research Dashboard.\n',
                401,
                {'WWW-Authenticate': 'Basic realm="BrowseBias Admin"'}
            )
        return f(*args, **kwargs)
    return decorated

# ─── Import Bias Engine ─────────────────────────────────────────────
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from bias_engine import BiasEngine
    from bias_engine.config import EngineConfig
    HAS_BIAS_ENGINE = True
except Exception as _e:
    HAS_BIAS_ENGINE = False
    print(f"Notice: BiasEngine module import: {_e}")

# Check THKI models freshness (< 2 weeks) on server startup
try:
    from bias_engine.thki_discovery import check_and_update_thki_models
    check_and_update_thki_models(data_dir=Path(DATA_DIR))
except Exception as _disc_err:
    print(f"Notice: THKI model discovery startup check: {_disc_err}")


def clean_suggestion_text(raw_text: str) -> str:
    """Sanitize suggestion text by removing embedded CSS or trailing UI button text."""
    if not raw_text:
        return ""
    text = str(raw_text)
    # Remove CSS selectors and rules (e.g. .MagqMc .ZFiwCf{...})
    text = re.split(r'\.[A-Za-z0-9_-]+\s*[\.\{\#]', text)[0]
    if '{' in text:
        text = text.split('{')[0]
    # Remove trailing UI artifacts added by Google autocomplete DOM
    text = re.sub(r'(\s*AI Mode|\s*See more|\s*Delete|\s*Feedback geben|\s*Löschen|\s*Melden)+$', '', text, flags=re.IGNORECASE)
    if text.endswith('AI Mode'):
        text = text[:-7].strip()
    return re.sub(r'\s+', ' ', text).strip()


# ─── Default numerical bias lexicon ─────────────────────────────────
DEFAULT_LEXICON = {
    "climate change hoax": {
        "score": 0.85,
        "scores": {"conspiracy": 0.85, "accusation": 0.40},
        "mouseover": "This suggestion is associated with conspiracy theories (score: 0.85)."
    },
    "[PERSON] fraud": {
        "score": 0.62,
        "scores": {"political": 0.62, "accusation": 0.58},
        "mouseover": "This suggestion reflects political ideology bias (score: 0.62)."
    },
    "[PERSON] epstein files": {
        "score": 0.78,
        "scores": {"conspiracy": 0.78, "accusation": 0.65},
        "mouseover": "This suggestion associates individuals with conspiracy or criminal allegations (score: 0.78)."
    },
    "is the earth flat": {
        "score": 0.90,
        "scores": {"conspiracy": 0.90},
        "mouseover": "This suggestion is associated with conspiracy theories (score: 0.90)."
    },
    "vaccines cause autism": {
        "score": 0.88,
        "scores": {"conspiracy": 0.88, "accusation": 0.50},
        "mouseover": "This suggestion is associated with conspiracy theories (score: 0.88)."
    },
    "vaccine safety studies": {
        "score": 0.0,
        "scores": {},
        "mouseover": "This suggestion appears neutral."
    },
    "election fraud": {
        "score": 0.55,
        "scores": {"political": 0.55, "conspiracy": 0.45},
        "mouseover": "This suggestion reflects political ideology bias (score: 0.55)."
    },
    "[PERSON] corrupt": {
        "score": 0.75,
        "scores": {"political": 0.75, "accusation": 0.70},
        "mouseover": "This suggestion contains accusatory or defamatory language (score: 0.70)."
    },
}


def init_lexicon():
    """Create the lexicon file with defaults if it doesn't exist."""
    if not os.path.exists(LEXICON_FILE):
        with open(LEXICON_FILE, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT_LEXICON, f, indent=2)


def load_lexicon():
    """Load the bias lexicon from disk."""
    if not os.path.exists(LEXICON_FILE):
        init_lexicon()
    with open(LEXICON_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


# ─── Rating Job Management ──────────────────────────────────────────
RATING_STATE_LOCK = threading.Lock()

def _get_initial_model():
    if os.environ.get("THKI_KEY"):
        return "openai-gpt5.4-mini"
    if os.environ.get("GOOGLE_API_KEY"):
        return "gemini-3.5-flash-lite"
    return "openai-gpt5.4-mini"

RATING_STATE = {
    "is_running": False,
    "mode": "incremental",
    "stage": "idle",
    "progress": 0,
    "message": "Ready to run ratings.",
    "started_at": None,
    "completed_at": None,
    "elapsed_seconds": 0,
    "error": None,
    "result": None,
    "provider": "thki" if os.environ.get("THKI_KEY") else "gemini",
    "model": _get_initial_model(),
    "logs": []
}


def on_rating_progress(event: dict):
    with RATING_STATE_LOCK:
        RATING_STATE["stage"] = event.get("stage", RATING_STATE["stage"])
        RATING_STATE["progress"] = event.get("progress", RATING_STATE["progress"])
        RATING_STATE["message"] = event.get("message", RATING_STATE["message"])
        if event.get("model"):
            RATING_STATE["model"] = event["model"]
        if event.get("error"):
            RATING_STATE["error"] = event["error"]

        log_entry = {
            "timestamp": event.get("timestamp", datetime.utcnow().isoformat() + "Z")[:19],
            "stage": event.get("stage", ""),
            "progress": event.get("progress", 0),
            "message": event.get("message", "")
        }
        RATING_STATE["logs"].append(log_entry)
        if len(RATING_STATE["logs"]) > 300:
            RATING_STATE["logs"] = RATING_STATE["logs"][-300:]


def run_rating_job_thread(mode: str, provider: str = None, model: str = None):
    global RATING_STATE
    start_ts = datetime.utcnow()
    with RATING_STATE_LOCK:
        RATING_STATE["is_running"] = True
        RATING_STATE["mode"] = mode
        if provider:
            RATING_STATE["provider"] = provider
        if model:
            RATING_STATE["model"] = model
        RATING_STATE["stage"] = "normalizing"
        RATING_STATE["progress"] = 5
        RATING_STATE["message"] = f"Starting {mode} rating pipeline ({RATING_STATE['model']})..."
        RATING_STATE["started_at"] = start_ts.isoformat() + "Z"
        RATING_STATE["completed_at"] = None
        RATING_STATE["elapsed_seconds"] = 0
        RATING_STATE["error"] = None
        RATING_STATE["result"] = None
        RATING_STATE["logs"] = [{
            "timestamp": start_ts.isoformat() + "Z"[:19],
            "stage": "starting",
            "progress": 5,
            "message": f"🚀 Initializing {mode} rating pipeline with model: {RATING_STATE['model']} (Provider: {RATING_STATE['provider']})..."
        }]

    try:
        if not HAS_BIAS_ENGINE:
            raise RuntimeError("BiasEngine module is not available in Python environment.")

        cfg = EngineConfig(data_dir=DATA_DIR)
        engine = BiasEngine(config=cfg, provider=provider, model=model)

        with RATING_STATE_LOCK:
            RATING_STATE["model"] = engine.primary_llm.model
            RATING_STATE["provider"] = provider or getattr(engine.primary_llm, "name", "")

        res = engine.run_pipeline(
            mode=mode,
            force_all=(mode == "initial"),
            progress_callback=on_rating_progress
        )

        with RATING_STATE_LOCK:
            RATING_STATE["is_running"] = False
            RATING_STATE["stage"] = "completed"
            RATING_STATE["progress"] = 100
            RATING_STATE["completed_at"] = datetime.utcnow().isoformat() + "Z"
            RATING_STATE["elapsed_seconds"] = res.get("elapsed_seconds", 0)
            RATING_STATE["result"] = res
            RATING_STATE["message"] = f"✅ {mode.capitalize()} rating completed in {res.get('elapsed_seconds', 0)}s ({RATING_STATE['model']})!"
    except Exception as e:
        with RATING_STATE_LOCK:
            RATING_STATE["is_running"] = False
            RATING_STATE["stage"] = "failed"
            RATING_STATE["error"] = str(e)
            RATING_STATE["message"] = f"❌ Rating failed: {str(e)}"
            RATING_STATE["completed_at"] = datetime.utcnow().isoformat() + "Z"


def load_rating_history(limit: int = 50) -> list:
    """Read task_journal.jsonl and return completed / started / failed rating runs in reverse order."""
    if not os.path.exists(TASK_JOURNAL_FILE):
        return []

    runs = []
    try:
        with open(TASK_JOURNAL_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    runs.append(entry)
                except Exception:
                    continue
    except Exception as e:
        print(f"Error reading journal: {e}")

    runs.reverse()
    return runs[:limit]


# ─── Routes ─────────────────────────────────────────────────────────


@app.route('/')
@require_admin
def dashboard():
    """Dashboard showing collected data, feedback reports, rating engine, bias scores explorer, and server status."""
    entries = []
    if os.path.exists(UPLOAD_FILE):
        with open(UPLOAD_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

    total_suggestions = 0
    all_entries = []
    unique_queries = set()
    bias_counts = {
        'high': 0, 'medium': 0, 'low': 0, 'unbiased': 0
    }
    version_counts = {}
    vtag_counts = {}
    domain_counts = {}

    for upload in entries:
        up_version = upload.get('version') or upload.get('extensionVersion', '') or '1.1.0'
        up_vtag = upload.get('v_tag') or upload.get('versionTag', '') or 'Silurian'
        up_user = upload.get('user_pseudonym') or upload.get('user_tag') or 'anonymous'
        up_received = upload.get('receivedAt', '')
        version_counts[up_version] = version_counts.get(up_version, 0) + 1
        vtag_counts[up_vtag] = vtag_counts.get(up_vtag, 0) + 1

        for entry in upload.get('entries', []):
            suggs = entry.get('suggestions', [])
            total_suggestions += len(suggs)
            q = entry.get('query', '').strip()
            if q:
                unique_queries.add(q.lower())
            tld = entry.get('googleTld', '')
            if tld:
                domain_counts[tld] = domain_counts.get(tld, 0) + 1

            for s in suggs:
                score = s.get('score', s.get('bias_score')) if isinstance(s, dict) else None
                if score is not None and isinstance(score, (int, float)):
                    if score >= 0.65:
                        bias_counts['high'] += 1
                    elif score >= 0.35:
                        bias_counts['medium'] += 1
                    elif score > 0:
                        bias_counts['low'] += 1
                    else:
                        bias_counts['unbiased'] += 1
                else:
                    bias_counts['unbiased'] += 1

            entry_copy = dict(entry)
            entry_user = entry.get('user_pseudonym') or entry.get('user_tag') or up_user
            entry_copy['user_pseudonym'] = entry_user
            if not entry_copy.get('version'):
                entry_copy['version'] = up_version
            if not entry_copy.get('v_tag'):
                entry_copy['v_tag'] = up_vtag
            if not entry_copy.get('receivedAt'):
                entry_copy['receivedAt'] = up_received
            all_entries.append(entry_copy)

    recent_entries = list(reversed(all_entries[-250:]))

    pseudonym_counts = {}
    for e in all_entries:
        p_tag = e.get('user_pseudonym') or 'anonymous'
        pseudonym_counts[p_tag] = pseudonym_counts.get(p_tag, 0) + 1
    unique_pseudonyms = sorted(pseudonym_counts.keys())

    reports = []
    if os.path.exists(REPORTS_FILE):
        with open(REPORTS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        reports.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

    recent_reports = list(reversed(reports[-150:]))
    lexicon = load_lexicon()
    rating_history = load_rating_history(limit=50)

    # ── Category Processing for Bias Scores Tab ─────────────────────
    category_meta = {
        'political': {'name': 'Political Ideology', 'short': 'POL', 'color': 'badge-blue'},
        'accusation': {'name': 'Accusation / Defamation', 'short': 'ACC', 'color': 'badge-yellow'},
        'conspiracy': {'name': 'Conspiracy Theory', 'short': 'CON', 'color': 'badge-red'},
        'sexism': {'name': 'Sexism / Gender Bias', 'short': 'SEX', 'color': 'badge-purple'},
        'racism': {'name': 'Racism / Ethnic Bias', 'short': 'RAC', 'color': 'badge-red'},
        'religious': {'name': 'Religious Bias', 'short': 'REL', 'color': 'badge-yellow'},
    }

    category_summary = {
        k: {'key': k, 'name': meta['name'], 'short': meta['short'], 'color': meta['color'], 'count': 0, 'max_score': 0.0, 'top_term': '—'}
        for k, meta in category_meta.items()
    }

    categorized_scores = []
    for term, val in lexicon.items():
        if isinstance(val, dict):
            overall_score = float(val.get('score', val.get('maxScore', 0.0)))
            sub_scores = val.get('scores', {})
            mouseover = val.get('mouseover', '')
        elif isinstance(val, (int, float)):
            overall_score = float(val)
            sub_scores = {}
            mouseover = ''
        else:
            overall_score = 0.0
            sub_scores = {}
            mouseover = ''

        primary_cat = 'unbiased'
        max_sub = 0.0
        for cat_k, cat_s in sub_scores.items():
            cat_s_float = float(cat_s)
            if cat_s_float > max_sub:
                max_sub = cat_s_float
                primary_cat = cat_k

            if cat_k in category_summary and cat_s_float > 0:
                category_summary[cat_k]['count'] += 1
                if cat_s_float > category_summary[cat_k]['max_score']:
                    category_summary[cat_k]['max_score'] = cat_s_float
                    category_summary[cat_k]['top_term'] = term

        categorized_scores.append({
            'term': term,
            'score': overall_score,
            'scores': sub_scores,
            'primary_category': primary_cat,
            'mouseover': mouseover
        })

    # Sort descending by overall score by default
    categorized_scores.sort(key=lambda x: x['score'], reverse=True)

    with RATING_STATE_LOCK:
        rating_state = dict(RATING_STATE)
        rating_state["logs"] = list(RATING_STATE["logs"])

    top_domains = sorted(domain_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    sorted_versions = sorted(version_counts.items(), key=lambda x: x[1], reverse=True)
    sorted_vtags = sorted(vtag_counts.items(), key=lambda x: x[1], reverse=True)

    return render_template_string(DASHBOARD_HTML,
        upload_count=len(entries),
        total_suggestions=total_suggestions,
        entry_count=len(all_entries),
        unique_queries_count=len(unique_queries),
        recent_entries=recent_entries,
        report_count=len(reports),
        recent_reports=recent_reports,
        lexicon=lexicon,
        lexicon_size=len(lexicon),
        categorized_scores=categorized_scores,
        category_summary=category_summary,
        category_meta=category_meta,
        bias_counts=bias_counts,
        top_domains=top_domains,
        sorted_versions=sorted_versions,
        sorted_vtags=sorted_vtags,
        uploads_file_path=UPLOAD_FILE,
        suggestions_file_path=SUGGESTIONS_FILE,
        rating_history=rating_history,
        rating_state=rating_state,
        has_bias_engine=HAS_BIAS_ENGINE,
        pseudonym_counts=pseudonym_counts,
        unique_pseudonyms=unique_pseudonyms
    )


# ─── Dashboard HTML ─────────────────────────────────────────────────

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Autocomplete Bias — Research Server Console</title>
    <style>
        :root {
            --bg-base: #0d1117;
            --bg-surface: #161b22;
            --bg-elevated: #21262d;
            --bg-subtle: #1c2128;
            --border-default: #30363d;
            --border-muted: #21262d;
            --text-primary: #f0f6fc;
            --text-secondary: #8b949e;
            --text-muted: #6e7681;
            --accent-blue: #58a6ff;
            --accent-blue-bg: rgba(56, 139, 253, 0.15);
            --accent-green: #3fb950;
            --accent-green-bg: rgba(63, 185, 80, 0.15);
            --accent-red: #f85149;
            --accent-red-bg: rgba(248, 81, 73, 0.15);
            --accent-yellow: #d29922;
            --accent-yellow-bg: rgba(210, 153, 34, 0.15);
            --accent-purple: #bc8cff;
            --font-mono: 'SF Mono', 'Cascadia Code', 'Fira Code', Consolas, monospace;
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            background: var(--bg-base);
            color: var(--text-primary);
            padding: 16px 24px 40px;
            font-size: 13px;
            line-height: 1.5;
        }

        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border-default);
            padding-bottom: 14px;
            margin-bottom: 16px;
        }
        .header-title-group {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .header-title-group h1 {
            font-size: 18px;
            font-weight: 700;
            letter-spacing: -0.3px;
        }
        .header-right {
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .tag-badge {
            font-size: 11px;
            font-weight: 700;
            padding: 3px 8px;
            border-radius: 6px;
            background: rgba(188, 140, 255, 0.15);
            color: var(--accent-purple);
            border: 1px solid rgba(188, 140, 255, 0.4);
            font-family: var(--font-mono);
        }

        .tab-nav {
            display: flex;
            gap: 4px;
            border-bottom: 1px solid var(--border-default);
            margin-bottom: 16px;
        }
        .tab-btn {
            background: none;
            border: none;
            border-bottom: 2px solid transparent;
            color: var(--text-secondary);
            padding: 8px 16px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 6px;
            transition: all 0.15s ease;
        }
        .tab-btn:hover {
            color: var(--text-primary);
            background: rgba(255,255,255,0.02);
        }
        .tab-btn.active {
            color: var(--accent-blue);
            border-bottom-color: var(--accent-blue);
        }

        .tab-pane {
            display: none;
        }
        .tab-pane.active {
            display: block;
        }

        .card-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 12px;
            margin-bottom: 16px;
        }
        .card {
            background: var(--bg-surface);
            border: 1px solid var(--border-default);
            border-radius: 8px;
            padding: 12px 14px;
        }
        .card-value {
            font-size: 20px;
            font-weight: 700;
            color: var(--text-primary);
            font-family: var(--font-mono);
        }
        .card-label {
            font-size: 11px;
            color: var(--text-secondary);
            margin-top: 2px;
            text-transform: uppercase;
            letter-spacing: 0.3px;
        }

        .toolbar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 12px;
        }
        .toolbar-left, .toolbar-right {
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
        }

        .search-input {
            background: var(--bg-surface);
            border: 1px solid var(--border-default);
            border-radius: 6px;
            color: var(--text-primary);
            padding: 5px 10px;
            font-size: 12px;
            outline: none;
            min-width: 240px;
        }
        .search-input:focus {
            border-color: var(--accent-blue);
        }
        .select-input {
            background: var(--bg-surface);
            border: 1px solid var(--border-default);
            border-radius: 6px;
            color: var(--text-primary);
            padding: 5px 8px;
            font-size: 12px;
            outline: none;
            cursor: pointer;
        }

        .btn {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
            cursor: pointer;
            border: 1px solid transparent;
            text-decoration: none;
            transition: all 0.15s ease;
        }
        .btn-primary {
            background: var(--accent-green);
            color: #fff;
        }
        .btn-primary:hover {
            background: #2ea043;
        }
        .btn-secondary {
            background: var(--bg-elevated);
            color: var(--text-primary);
            border-color: var(--border-default);
        }
        .btn-secondary:hover {
            background: #282e37;
            border-color: #484f58;
        }
        .btn-blue {
            background: var(--accent-blue);
            color: #fff;
        }
        .btn-blue:hover {
            background: #388bfd;
        }

        .table-responsive {
            overflow-x: auto;
            border: 1px solid var(--border-default);
            border-radius: 8px;
            background: var(--bg-surface);
        }
        table {
            width: 100%;
            border-collapse: collapse;
            text-align: left;
            font-size: 12px;
        }
        th, td {
            padding: 7px 10px;
            border-bottom: 1px solid var(--border-muted);
            vertical-align: middle;
        }
        th {
            background: var(--bg-elevated);
            color: var(--text-secondary);
            font-weight: 600;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.4px;
            position: sticky;
            top: 0;
            user-select: none;
        }
        th.sortable { cursor: pointer; }
        th.sortable:hover { color: var(--text-primary); background: #282e37; }

        .mono {
            font-family: var(--font-mono);
            font-size: 11px;
            color: var(--text-secondary);
        }

        .badge {
            display: inline-block;
            padding: 2px 7px;
            border-radius: 12px;
            font-size: 10.5px;
            font-weight: 600;
            white-space: nowrap;
        }
        .badge-red {
            background: var(--accent-red-bg);
            color: var(--accent-red);
            border: 1px solid rgba(248, 81, 73, 0.35);
        }
        .badge-blue {
            background: var(--accent-blue-bg);
            color: var(--accent-blue);
            border: 1px solid rgba(88, 166, 255, 0.35);
        }
        .badge-yellow {
            background: var(--accent-yellow-bg);
            color: var(--accent-yellow);
            border: 1px solid rgba(210, 153, 34, 0.35);
        }
        .badge-gray {
            background: var(--bg-elevated);
            color: var(--text-secondary);
            border: 1px solid var(--border-default);
        }
        .badge-green {
            background: var(--accent-green-bg);
            color: var(--accent-green);
            border: 1px solid rgba(63, 185, 80, 0.35);
        }
        .badge-purple {
            background: rgba(188, 140, 255, 0.15);
            color: var(--accent-purple);
            border: 1px solid rgba(188, 140, 255, 0.35);
        }

        .sugg-container {
            display: flex;
            flex-wrap: wrap;
            gap: 4px;
            align-items: center;
        }
        .sugg-chip {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 11px;
            line-height: 1.3;
            background: var(--bg-subtle);
            border: 1px solid var(--border-muted);
            color: var(--text-primary);
        }
        .sugg-red {
            background: rgba(220, 38, 38, 0.22);
            border-color: rgba(220, 38, 38, 0.7);
            color: #ff7b72;
        }
        .sugg-num {
            font-size: 9.5px;
            color: var(--text-muted);
            font-family: var(--font-mono);
        }

        /* ─── Bias Scores & Category Filter Grid ───────────────── */
        .category-filter-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 10px;
            margin-bottom: 16px;
        }
        .cat-filter-card {
            background: var(--bg-surface);
            border: 1px solid var(--border-default);
            border-radius: 8px;
            padding: 10px 12px;
            cursor: pointer;
            transition: all 0.15s ease;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            user-select: none;
        }
        .cat-filter-card:hover {
            border-color: var(--accent-blue);
            background: var(--bg-elevated);
        }
        .cat-filter-card.active {
            border-color: var(--accent-blue);
            background: rgba(88, 166, 255, 0.12);
            box-shadow: 0 0 8px rgba(88, 166, 255, 0.2);
        }
        .cat-filter-title {
            font-size: 11px;
            font-weight: 600;
            color: var(--text-secondary);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .cat-filter-count {
            font-size: 18px;
            font-weight: 700;
            font-family: var(--font-mono);
            color: var(--text-primary);
            margin-top: 4px;
        }
        .cat-filter-top {
            font-size: 10px;
            color: var(--text-muted);
            margin-top: 2px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .cat-breakdown-tag {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            padding: 1px 6px;
            border-radius: 4px;
            font-size: 10.5px;
            font-family: var(--font-mono);
            background: var(--bg-subtle);
            border: 1px solid var(--border-muted);
        }

        /* ─── Rating Engine UI ─────────────────────────────────── */
        .rating-card-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
            margin-bottom: 16px;
        }
        @media (max-width: 900px) {
            .rating-card-grid { grid-template-columns: 1fr; }
        }
        .rating-action-card {
            background: var(--bg-surface);
            border: 1px solid var(--border-default);
            border-radius: 8px;
            padding: 16px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            gap: 12px;
        }
        .rating-action-card:hover {
            border-color: var(--border-muted);
        }
        .rating-action-title {
            font-size: 15px;
            font-weight: 600;
            color: #fff;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .rating-action-desc {
            font-size: 12px;
            color: var(--text-secondary);
            line-height: 1.4;
        }
        .progress-card {
            background: var(--bg-surface);
            border: 1px solid var(--border-default);
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 16px;
        }
        .progress-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }
        .progress-bar-wrap {
            height: 10px;
            background: var(--bg-base);
            border-radius: 5px;
            overflow: hidden;
            border: 1px solid var(--border-default);
            margin-bottom: 12px;
        }
        .progress-bar-fill {
            height: 100%;
            width: 0%;
            background: linear-gradient(90deg, #238636, #2ea043);
            transition: width 0.3s ease-out;
        }
        .progress-bar-fill.active-stripes {
            background-size: 20px 20px;
            background-image: linear-gradient(45deg, rgba(255, 255, 255, 0.15) 25%, transparent 25%, transparent 50%, rgba(255, 255, 255, 0.15) 50%, rgba(255, 255, 255, 0.15) 75%, transparent 75%, transparent);
            animation: move-stripes 1.5s linear infinite;
        }
        @keyframes move-stripes {
            0% { background-position: 0 0; }
            100% { background-position: 40px 0; }
        }

        .stage-pipeline {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            margin: 10px 0 14px;
        }
        .stage-chip {
            display: flex;
            align-items: center;
            gap: 5px;
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 600;
            background: var(--bg-elevated);
            border: 1px solid var(--border-default);
            color: var(--text-muted);
            transition: all 0.2s ease;
        }
        .stage-chip.active {
            background: rgba(88, 166, 255, 0.18);
            border-color: var(--accent-blue);
            color: var(--accent-blue);
            box-shadow: 0 0 8px rgba(88, 166, 255, 0.25);
        }
        .stage-chip.done {
            background: rgba(63, 185, 80, 0.15);
            border-color: rgba(63, 185, 80, 0.4);
            color: var(--accent-green);
        }

        .live-console {
            background: #090d13;
            border: 1px solid var(--border-default);
            border-radius: 6px;
            padding: 10px 12px;
            font-family: var(--font-mono);
            font-size: 11px;
            color: #a5d6ff;
            max-height: 160px;
            overflow-y: auto;
            line-height: 1.45;
        }
        .live-console-line {
            display: flex;
            gap: 8px;
            word-break: break-all;
        }
        .live-console-time {
            color: var(--text-muted);
            flex-shrink: 0;
        }

        .section-box {
            background: var(--bg-surface);
            border: 1px solid var(--border-default);
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 16px;
        }
        .section-title {
            font-size: 14px;
            font-weight: 600;
            color: #fff;
            margin-bottom: 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .alert-box {
            padding: 10px 14px;
            border-radius: 6px;
            font-size: 12px;
            margin-bottom: 14px;
            display: none;
        }
        .alert-success {
            background: rgba(63, 185, 80, 0.15);
            border: 1px solid rgba(63, 185, 80, 0.4);
            color: var(--accent-green);
        }
        .alert-error {
            background: rgba(248, 81, 73, 0.15);
            border: 1px solid rgba(248, 81, 73, 0.4);
            color: var(--accent-red);
        }
    </style>
</head>
<body>

    <!-- Header -->
    <div class="header">
        <div class="header-title-group">
            <h1>Autocomplete Bias</h1>
            <span class="tag-badge">Research Server · v1.1.0 [Silurian]</span>
        </div>
        <div class="header-right">
            <span class="badge badge-green">● Server Online</span>
            <span class="mono" style="color: var(--text-muted);">Port 8765</span>
        </div>
    </div>

    <!-- Navigation Tabs -->
    <div class="tab-nav">
        <button class="tab-btn active" onclick="switchTab('tab-searches', this)">
            🔍 Recent Searches ({{ entry_count }})
        </button>
        <button class="tab-btn" onclick="switchTab('tab-reports', this)">
            🚩 User Reports ({{ report_count }})
        </button>
        <button class="tab-btn" onclick="switchTab('tab-scores', this)">
            📊 Bias Scores ({{ lexicon_size }})
        </button>
        <button class="tab-btn" onclick="switchTab('tab-ratings', this)">
            ⭐ Bias Rating Engine
        </button>
        <button class="tab-btn" onclick="switchTab('tab-data', this)">
            ⚡ Data &amp; Downloads
        </button>
        <button class="tab-btn" onclick="switchTab('tab-stats', this)">
            📈 Statistics
        </button>
    </div>

    <!-- ════════════════════════════════════════════════════════════════ -->
    <!-- TAB 1: RECENT SEARCHES                                           -->
    <!-- ════════════════════════════════════════════════════════════════ -->
    <div id="tab-searches" class="tab-pane active">
        <div class="toolbar">
            <div class="toolbar-left">
                <input type="text" id="search-filter" class="search-input" placeholder="🔍 Filter queries, suggestions, tag, version..." onkeyup="filterMainTable()">
                <select id="user-filter" class="select-input" onchange="filterByUserTag(this.value)">
                    <option value="">All Users / Tags</option>
                    {% for tag in unique_pseudonyms %}
                    <option value="{{ tag }}">{{ tag }}</option>
                    {% endfor %}
                </select>
                <select id="limit-select" class="select-input" onchange="changeLimit(this.value)">
                    <option value="50">Show 50</option>
                    <option value="100" selected>Show 100</option>
                    <option value="250">Show 250</option>
                    <option value="all">Show All</option>
                </select>
            </div>
            <div class="toolbar-right">
                <span id="rows-indicator" class="mono">Showing {{ recent_entries|length }} queries</span>
                <button class="btn btn-secondary" onclick="location.reload()">🔄 Refresh</button>
                <a href="/api/download/bundle" class="btn btn-primary" title="Download all datasets & offline viewer bundle">📦 Dataset Bundle (.zip)</a>
                <a href="/api/download/suggestions.jsonl" class="btn btn-secondary">📥 suggestions.jsonl</a>
            </div>
        </div>

        <div class="table-responsive">
            <table id="main-table">
                <thead>
                    <tr>
                        <th class="sortable" onclick="sortTable('main-table', 0)">Timestamp ⇅</th>
                        <th class="sortable" onclick="sortTable('main-table', 1)">User / Tag ⇅</th>
                        <th class="sortable" onclick="sortTable('main-table', 2)">Query ⇅</th>
                        <th>Suggestions (Captured)</th>
                        <th class="sortable" onclick="sortTable('main-table', 4)">Domain ⇅</th>
                        <th class="sortable" onclick="sortTable('main-table', 5)">Lang ⇅</th>
                        <th class="sortable" onclick="sortTable('main-table', 6)">Version ⇅</th>
                        <th class="sortable" onclick="sortTable('main-table', 7)">Tag ⇅</th>
                    </tr>
                </thead>
                <tbody>
                    {% if recent_entries %}
                        {% for entry in recent_entries %}
                        <tr class="data-row" data-user="{{ entry.get('user_pseudonym', 'anonymous') }}">
                            <td class="mono">{{ entry.get('timestamp', entry.get('receivedAt', ''))[:19] }}</td>
                            <td class="mono"><span class="badge badge-blue" style="font-weight: 600;">{{ entry.get('user_pseudonym', 'anonymous') }}</span></td>
                            <td><strong style="color: #fff;">{{ entry.get('query', '—') }}</strong></td>
                            <td>
                                <div class="sugg-container">
                                    {% for s in entry.get('suggestions', []) %}
                                        {% set score = s.get('score', s.get('bias_score')) if s is mapping else None %}
                                        {% set s_text = s.get('text', '') if s is mapping else s|string %}
                                        <div class="sugg-chip {% if score and score >= 0.35 %}sugg-red{% endif %}" title="{{ s_text }}{% if score is not none %} (score: {{ score }}){% endif %}">
                                            <span class="sugg-num">#{{ loop.index }}</span>
                                            <span class="sugg-txt">{{ s_text }}</span>
                                        </div>
                                    {% else %}
                                        <span style="color: var(--text-muted); font-size: 11px;">(no suggestions)</span>
                                    {% endfor %}
                                </div>
                            </td>
                            <td class="mono">{{ entry.get('googleTld', '—') }}</td>
                            <td class="mono">{{ entry.get('language', '—') }}</td>
                            <td class="mono"><span class="badge badge-purple">v{{ entry.get('version', '1.1.0') }}</span></td>
                            <td class="mono"><span class="badge badge-gray">{{ entry.get('v_tag', 'Silurian') }}</span></td>
                        </tr>
                        {% endfor %}
                    {% else %}
                        <tr><td colspan="8" class="empty-state" style="text-align: center; padding: 24px; color: var(--text-muted);">No search entries collected yet.</td></tr>
                    {% endif %}
                </tbody>
            </table>
        </div>
    </div>

    <!-- ════════════════════════════════════════════════════════════════ -->
    <!-- TAB 2: USER REPORTS & FEEDBACK                                   -->
    <!-- ════════════════════════════════════════════════════════════════ -->
    <div id="tab-reports" class="tab-pane">
        <div class="toolbar">
            <div class="toolbar-left">
                <input type="text" id="report-filter" class="search-input" placeholder="🔍 Filter user reports &amp; feedback..." onkeyup="filterReportsTable()">
                <select id="report-type-select" class="select-input" onchange="filterReportsByType(this.value)">
                    <option value="">All Report Types</option>
                    <option value="problematic_suggestions">Problematic Suggestions</option>
                    <option value="wrong_bias_label">Wrong Bias Label</option>
                    <option value="feedback">General Feedback</option>
                </select>
            </div>
            <div class="toolbar-right">
                <a href="/api/download/reports.jsonl" class="btn btn-secondary">📥 Download reports.jsonl</a>
            </div>
        </div>

        <div class="table-responsive">
            <table id="reports-table">
                <thead>
                    <tr>
                        <th class="sortable" onclick="sortTable('reports-table', 0)">Time ⇅</th>
                        <th class="sortable" onclick="sortTable('reports-table', 1)">User / Tag ⇅</th>
                        <th class="sortable" onclick="sortTable('reports-table', 2)">Type ⇅</th>
                        <th class="sortable" onclick="sortTable('reports-table', 3)">Query ⇅</th>
                        <th>Flagged Suggestions</th>
                        <th>User Comment</th>
                        <th class="sortable" onclick="sortTable('reports-table', 6)">Version ⇅</th>
                        <th class="sortable" onclick="sortTable('reports-table', 7)">Tag ⇅</th>
                    </tr>
                </thead>
                <tbody>
                    {% if recent_reports %}
                        {% for r in recent_reports %}
                        <tr class="report-row" data-type="{{ r.get('reportType', '') }}" data-user="{{ r.get('user_pseudonym', 'anonymous') }}">
                            <td class="mono">{{ r.get('receivedAt', r.get('timestamp', 'N/A'))[:19] }}</td>
                            <td class="mono"><span class="badge badge-blue">{{ r.get('user_pseudonym', 'anonymous') }}</span></td>
                            <td>
                                {% if r.get('reportType') == 'problematic_suggestions' %}
                                    <span class="badge badge-red">Problematic</span>
                                {% elif r.get('reportType') == 'wrong_bias_label' %}
                                    <span class="badge badge-yellow">Wrong Label</span>
                                {% else %}
                                    <span class="badge badge-gray">{{ r.get('reportType', 'Feedback') }}</span>
                                {% endif %}
                            </td>
                            <td><strong style="color: #fff;">{{ r.get('query', 'N/A') }}</strong></td>
                            <td>
                                <div class="sugg-container">
                                    {% for s in r.get('suggestions', []) %}
                                        <span class="badge badge-gray">{{ s.get('text', 'N/A') if s is mapping else s }}</span>
                                    {% else %}
                                        <span style="color: var(--text-muted);">—</span>
                                    {% endfor %}
                                </div>
                            </td>
                            <td>{{ r.get('comment', '—') }}</td>
                            <td class="mono"><span class="badge badge-purple">v{{ r.get('version', '1.1.0') }}</span></td>
                            <td class="mono"><span class="badge badge-gray">{{ r.get('v_tag', 'Silurian') }}</span></td>
                        </tr>
                        {% endfor %}
                    {% else %}
                        <tr><td colspan="8" class="empty-state" style="text-align: center; padding: 24px; color: var(--text-muted);">No user feedback received yet.</td></tr>
                    {% endif %}
                </tbody>
            </table>
        </div>
    </div>

    <!-- ════════════════════════════════════════════════════════════════ -->
    <!-- TAB 3: BIAS SCORES EXPLORER (BY CATEGORY & SORTABLE) (NEW)       -->
    <!-- ════════════════════════════════════════════════════════════════ -->
    <div id="tab-scores" class="tab-pane">
        
        <!-- Category Summary & Fast Filter Cards -->
        <div class="category-filter-grid">
            <div class="cat-filter-card active" id="cat-card-all" onclick="selectCategoryCard('all')">
                <div class="cat-filter-title">
                    <span>🌟 All Categories</span>
                    <span class="badge badge-gray">All</span>
                </div>
                <div class="cat-filter-count" id="count-all">{{ lexicon_size }}</div>
                <div class="cat-filter-top">Complete bias lexicon</div>
            </div>

            {% for cat_k, cat in category_summary.items() %}
            <div class="cat-filter-card" id="cat-card-{{ cat_k }}" onclick="selectCategoryCard('{{ cat_k }}')">
                <div class="cat-filter-title">
                    <span>{{ cat.name }}</span>
                    <span class="badge {{ cat.color }}">{{ cat.short }}</span>
                </div>
                <div class="cat-filter-count">{{ cat.count }}</div>
                <div class="cat-filter-top" title="Top: {{ cat.top_term }} ({{ cat.max_score }})">
                    {% if cat.count > 0 %}Top: {{ cat.top_term }}{% else %}No entries yet{% endif %}
                </div>
            </div>
            {% endfor %}
        </div>

        <!-- Scores Toolbar -->
        <div class="toolbar">
            <div class="toolbar-left">
                <input type="text" id="scores-filter" class="search-input" placeholder="🔍 Search suggestion terms or mouseover..." onkeyup="filterScoresTable()">
                
                <select id="scores-category-select" class="select-input" onchange="onCategorySelectChange(this.value)">
                    <option value="all">All Bias Dimensions</option>
                    <option value="political">Political Ideology Bias</option>
                    <option value="accusation">Accusation / Defamation</option>
                    <option value="conspiracy">Conspiracy Theory</option>
                    <option value="sexism">Sexism / Gender Bias</option>
                    <option value="racism">Racism / Ethnic Bias</option>
                    <option value="religious">Religious Bias</option>
                </select>

                <select id="scores-threshold-select" class="select-input" onchange="filterScoresTable()">
                    <option value="0.0">All Continuous Scores (>= 0.00)</option>
                    <option value="0.01">Flagged / Biased Only (> 0.00)</option>
                    <option value="0.35">Medium &amp; High (>= 0.35)</option>
                    <option value="0.65">High Bias (>= 0.65)</option>
                </select>

                <select id="scores-sort-select" class="select-input" onchange="onSortSelectChange(this.value)">
                    <option value="score-desc">Sort: Highest Score First ▾</option>
                    <option value="score-asc">Sort: Lowest Score First ▴</option>
                    <option value="term-asc">Sort: Term A → Z</option>
                    <option value="term-desc">Sort: Term Z → A</option>
                    <option value="cat-political">Sort by: Political Score ▾</option>
                    <option value="cat-conspiracy">Sort by: Conspiracy Score ▾</option>
                    <option value="cat-accusation">Sort by: Accusation Score ▾</option>
                    <option value="cat-sexism">Sort by: Sexism Score ▾</option>
                    <option value="cat-racism">Sort by: Racism Score ▾</option>
                    <option value="cat-religious">Sort by: Religious Score ▾</option>
                </select>
            </div>

            <div class="toolbar-right">
                <span id="scores-count-indicator" class="mono">Showing {{ categorized_scores|length }} of {{ lexicon_size }} entries</span>
                <a href="/api/download/lexicon.json" class="btn btn-secondary">📥 Export lexicon.json</a>
            </div>
        </div>

        <!-- Scores Table -->
        <div class="table-responsive">
            <table id="scores-table">
                <thead>
                    <tr>
                        <th class="sortable" onclick="sortScoresByColumn(0, false)">Term / Template ⇅</th>
                        <th class="sortable" onclick="sortScoresByColumn(1, true)" style="width: 140px;">Max Score ⇅</th>
                        <th class="sortable" onclick="sortScoresByColumn(2, false)" style="width: 160px;">Primary Category ⇅</th>
                        <th>Category Scores Breakdown</th>
                        <th>Mouseover / Explanation Tooltip</th>
                    </tr>
                </thead>
                <tbody id="scores-table-body">
                    {% if categorized_scores %}
                        {% for item in categorized_scores %}
                        <tr class="score-row" 
                            data-term="{{ item.term|lower }}" 
                            data-score="{{ item.score }}"
                            data-primary="{{ item.primary_category }}"
                            data-political="{{ item.scores.get('political', 0.0) }}"
                            data-accusation="{{ item.scores.get('accusation', 0.0) }}"
                            data-conspiracy="{{ item.scores.get('conspiracy', 0.0) }}"
                            data-sexism="{{ item.scores.get('sexism', 0.0) }}"
                            data-racism="{{ item.scores.get('racism', 0.0) }}"
                            data-religious="{{ item.scores.get('religious', 0.0) }}">
                            
                            <!-- Term -->
                            <td style="color: #fff; font-weight: 600;">
                                <code>{{ item.term }}</code>
                            </td>

                            <!-- Continuous Score Badge -->
                            <td data-sort="{{ item.score }}">
                                {% if item.score >= 0.65 %}
                                    <span class="badge badge-red" style="font-size: 11.5px;">{{ "%.2f"|format(item.score) }} (High)</span>
                                {% elif item.score >= 0.35 %}
                                    <span class="badge badge-yellow" style="font-size: 11.5px;">{{ "%.2f"|format(item.score) }} (Medium)</span>
                                {% elif item.score > 0 %}
                                    <span class="badge badge-blue" style="font-size: 11.5px;">{{ "%.2f"|format(item.score) }} (Low)</span>
                                {% else %}
                                    <span class="badge badge-gray" style="font-size: 11.5px;">0.00 (Neutral)</span>
                                {% endif %}
                            </td>

                            <!-- Primary Category -->
                            <td>
                                {% set p_cat = item.primary_category %}
                                {% if p_cat in category_meta %}
                                    <span class="badge {{ category_meta[p_cat]['color'] }}">{{ category_meta[p_cat]['name'] }}</span>
                                {% else %}
                                    <span class="badge badge-gray">Neutral / General</span>
                                {% endif %}
                            </td>

                            <!-- Category Scores Breakdown -->
                            <td>
                                <div style="display: flex; flex-wrap: wrap; gap: 4px;">
                                    {% for ck, cs in item.scores.items() %}
                                        {% if cs > 0 %}
                                            <span class="cat-breakdown-tag" title="{{ category_meta.get(ck, {}).get('name', ck) }}: {{ cs }}">
                                                <strong style="color: var(--accent-blue);">{{ ck[:4]|upper }}:</strong> {{ "%.2f"|format(cs) }}
                                            </span>
                                        {% endif %}
                                    {% else %}
                                        <span style="color: var(--text-muted); font-size: 11px;">—</span>
                                    {% endfor %}
                                </div>
                            </td>

                            <!-- Mouseover Tooltip Text -->
                            <td style="color: var(--text-secondary); font-size: 12px;">
                                {{ item.mouseover if item.mouseover else '—' }}
                            </td>
                        </tr>
                        {% endfor %}
                    {% else %}
                        <tr><td colspan="5" class="empty-state" style="text-align: center; padding: 24px; color: var(--text-muted);">No lexicon entries scored yet.</td></tr>
                    {% endif %}
                </tbody>
            </table>
        </div>
    </div>

    <!-- ════════════════════════════════════════════════════════════════ -->
    <!-- TAB 4: BIAS RATING ENGINE & MODELS                               -->
    <!-- ════════════════════════════════════════════════════════════════ -->
    <div id="tab-ratings" class="tab-pane">
        
        <!-- Scientific Two-Stage Model Selector -->
        <div class="section-box" style="margin-bottom: 16px; border: 1px solid rgba(88, 166, 255, 0.3); background: rgba(22, 27, 34, 0.95);">
            <div class="section-title" style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 14px;">🔬 <strong>Scientific Model Selector</strong> (Single Model Provenance)</span>
                    <span class="badge badge-purple" style="font-size: 10px;">Two-Stage</span>
                </div>
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span id="model-status-indicator" class="badge badge-green" style="font-size: 11px;">✓ Ready</span>
                    <button class="btn btn-secondary" style="padding: 3px 8px; font-size: 11px;" onclick="loadModelCatalog(true)">
                        🔄 Check / Refresh Models
                    </button>
                </div>
            </div>
            
            <p style="color: var(--text-secondary); font-size: 12px; margin-bottom: 12px;">
                To guarantee scientific reproducibility, each rating run strictly attributes all suggestion tags, matchmaking matrices, and Bradley-Terry pairwise comparisons to <strong>one chosen model</strong>. Providers configured in your <code>.env</code> file are highlighted below.
            </p>

            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px; align-items: start;">
                <!-- Stage 1: Family / Provider -->
                <div style="background: var(--bg-base); padding: 12px; border-radius: 6px; border: 1px solid var(--border-default);">
                    <label style="display: block; font-size: 11px; text-transform: uppercase; color: var(--text-secondary); font-weight: 600; margin-bottom: 6px;">
                        Stage 1: Provider Family
                    </label>
                    <select id="selector-provider" class="select-input" style="width: 100%; padding: 8px; font-size: 12.5px;" onchange="onProviderChange()">
                        <option value="thki">🎓 TH Köln KI Connect (Free Campus LLM) [Loading...]</option>
                        <option value="gemini">🌐 Google Gemini [Loading...]</option>
                        <option value="openai">🤖 OpenAI Cloud</option>
                        <option value="local">💻 Local / Ollama (Self-Hosted)</option>
                    </select>
                    <div id="provider-env-note" style="margin-top: 6px; font-size: 11px; color: var(--accent-green); display: flex; align-items: center; gap: 4px;">
                        <span>Loading provider details...</span>
                    </div>
                </div>

                <!-- Stage 2: Specific Model -->
                <div style="background: var(--bg-base); padding: 12px; border-radius: 6px; border: 1px solid var(--border-default);">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                        <label style="font-size: 11px; text-transform: uppercase; color: var(--text-secondary); font-weight: 600;">
                            Stage 2: Target Model
                        </label>
                        <span id="model-last-checked-label" class="mono" style="font-size: 10.5px; color: var(--text-muted);">Last checked: —</span>
                    </div>
                    <select id="selector-model" class="select-input" style="width: 100%; padding: 8px; font-size: 12.5px; font-family: var(--font-mono);" onchange="onModelChange()">
                        <!-- Populated dynamically via JS -->
                    </select>
                    <div id="model-custom-wrap" style="display: none; margin-top: 8px;">
                        <input type="text" id="selector-custom-model" class="search-input" style="width: 100%;" placeholder="Enter model name (e.g. llama3.2)...">
                    </div>
                    <div id="model-desc-note" style="margin-top: 6px; font-size: 11px; color: var(--text-secondary);">
                        Model ready for scientific rating execution.
                    </div>
                </div>
            </div>
        </div>

        <!-- Action Cards Grid -->
        <div class="rating-card-grid">
            <div class="rating-action-card">
                <div>
                    <div class="rating-action-title">
                        <span>⚡ Incremental Bias Rating</span>
                        <span class="badge badge-green">Fast Path</span>
                    </div>
                    <div class="rating-action-desc" style="margin-top: 6px;">
                        Ingests new raw suggestions, applies spaCy entity normalization (<code>[PERSON]</code>), identifies candidate bias across 6 dimensions via LLM, generates stratified comparison groups, executes listwise rankings, updates PCMs, and fits regularized Bradley-Terry models.
                    </div>
                </div>
                <div>
                    <button id="btn-run-incremental" class="btn btn-primary" style="width: 100%; justify-content: center; padding: 9px;" onclick="triggerRating('incremental')">
                        ▶️ Run Incremental Rating Now
                    </button>
                </div>
            </div>

            <div class="rating-action-card">
                <div>
                    <div class="rating-action-title">
                        <span>🚀 Full Initial Rating</span>
                        <span class="badge badge-purple">Baseline Fit</span>
                    </div>
                    <div class="rating-action-desc" style="margin-top: 6px;">
                        Re-evaluates all collected suggestions from baseline. Ideal for testing updated taxonomy definitions, recalibrating global Bradley-Terry scale anchors, or generating a complete new <code>lexicon.json</code> from scratch.
                    </div>
                </div>
                <div>
                    <button id="btn-run-initial" class="btn btn-secondary" style="width: 100%; justify-content: center; padding: 9px;" onclick="triggerRating('initial')">
                        🚀 Run Full Initial Rating Now
                    </button>
                </div>
            </div>
        </div>

        <!-- Live Progress & Monitor Card -->
        <div class="progress-card">
            <div class="progress-header">
                <div>
                    <strong id="rating-job-title" style="font-size: 14px; color: #fff;">
                        {% if rating_state.is_running %}
                            ⏳ Rating Engine Running ({{ rating_state.mode|capitalize }})
                        {% else %}
                            ⭐ Rating Engine Status: Idle
                        {% endif %}
                    </strong>
                    <div id="rating-job-subtitle" style="font-size: 11.5px; color: var(--text-secondary); margin-top: 2px;">
                        {{ rating_state.message }}
                    </div>
                </div>
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span id="rating-model-badge" class="badge badge-blue">Model: {{ rating_state.model }}</span>
                    <span id="rating-progress-percent" class="badge badge-purple" style="font-size: 12px;">{{ rating_state.progress }}%</span>
                </div>
            </div>

            <!-- Progress Bar -->
            <div class="progress-bar-wrap">
                <div id="rating-progress-bar" class="progress-bar-fill {% if rating_state.is_running %}active-stripes{% endif %}" style="width: {{ rating_state.progress }}%;"></div>
            </div>

            <!-- Stage Pipeline Indicators -->
            <div class="stage-pipeline">
                <div id="stage-normalizing" class="stage-chip {% if rating_state.stage == 'normalizing' %}active{% elif rating_state.progress > 20 %}done{% endif %}">
                    <span>1. Normalization</span>
                </div>
                <div id="stage-identification" class="stage-chip {% if rating_state.stage == 'identification' %}active{% elif rating_state.progress > 40 %}done{% endif %}">
                    <span>2. LLM Identification</span>
                </div>
                <div id="stage-matchmaking" class="stage-chip {% if rating_state.stage == 'matchmaking' %}active{% elif rating_state.progress > 60 %}done{% endif %}">
                    <span>3. Matchmaking</span>
                </div>
                <div id="stage-ranking" class="stage-chip {% if rating_state.stage == 'ranking' %}active{% elif rating_state.progress > 80 %}done{% endif %}">
                    <span>4. Listwise Ranking</span>
                </div>
                <div id="stage-bt_fitting" class="stage-chip {% if rating_state.stage == 'bt_fitting' %}active{% elif rating_state.progress > 90 %}done{% endif %}">
                    <span>5. BT Model Fitting</span>
                </div>
                <div id="stage-saving" class="stage-chip {% if rating_state.stage == 'saving' %}active{% elif rating_state.progress == 100 %}done{% endif %}">
                    <span>6. Lexicon Export</span>
                </div>
            </div>

            <!-- Live Streaming Console Output -->
            <div class="live-console" id="rating-live-console">
                {% if rating_state.logs %}
                    {% for l in rating_state.logs %}
                        <div class="live-console-line">
                            <span class="live-console-time">[{{ l.timestamp }}]</span>
                            <span>{{ l.message }}</span>
                        </div>
                    {% endfor %}
                {% else %}
                    <div class="live-console-line" style="color: var(--text-muted);">
                        <span>[Ready] Click "Run Incremental Rating" or "Run Full Initial Rating" to start execution.</span>
                    </div>
                {% endif %}
            </div>
        </div>

        <!-- Rating Runs History Table -->
        <div class="section-box">
            <div class="section-title">
                <span>📜 Historical Rating Runs &amp; Comparisons</span>
                <div style="display: flex; gap: 8px;">
                    <select id="history-type-filter" class="select-input" onchange="filterHistoryTable(this.value)">
                        <option value="">All Task Types</option>
                        <option value="incremental_pipeline">Incremental Pipeline</option>
                        <option value="initial_pipeline">Initial Pipeline</option>
                        <option value="daily_pipeline">Daily Schedule</option>
                        <option value="weekly_reranking">Weekly Re-ranking</option>
                    </select>
                    <button class="btn btn-secondary" onclick="refreshHistoryTable()">🔄 Refresh History</button>
                </div>
            </div>

            <div class="table-responsive" style="max-height: 400px;">
                <table id="history-table">
                    <thead>
                        <tr>
                            <th>Timestamp</th>
                            <th>Run Type</th>
                            <th>Status</th>
                            <th>LLM Model</th>
                            <th>Comparisons Added</th>
                            <th>Templates</th>
                            <th>Total Scored</th>
                            <th>Elapsed</th>
                        </tr>
                    </thead>
                    <tbody id="history-table-body">
                        {% if rating_history %}
                            {% for run in rating_history %}
                            <tr class="history-row" data-task="{{ run.get('task', '') }}">
                                <td class="mono">{{ run.get('timestamp', '')[:19] }}</td>
                                <td>
                                    {% if 'initial' in run.get('task', '') %}
                                        <span class="badge badge-purple">Initial Baseline</span>
                                    {% elif 'incremental' in run.get('task', '') %}
                                        <span class="badge badge-green">Incremental</span>
                                    {% elif 'daily' in run.get('task', '') %}
                                        <span class="badge badge-blue">Daily Auto</span>
                                    {% elif 'weekly' in run.get('task', '') %}
                                        <span class="badge badge-yellow">Weekly Re-rank</span>
                                    {% else %}
                                        <span class="badge badge-gray">{{ run.get('task', 'Task') }}</span>
                                    {% endif %}
                                </td>
                                <td>
                                    {% if run.get('status') == 'completed' %}
                                        <span class="badge badge-green">Completed</span>
                                    {% elif run.get('status') == 'started' %}
                                        <span class="badge badge-yellow">Running...</span>
                                    {% elif run.get('status') == 'failed' %}
                                        <span class="badge badge-red">Failed</span>
                                    {% else %}
                                        <span class="badge badge-gray">{{ run.get('status', 'N/A') }}</span>
                                    {% endif %}
                                </td>
                                <td class="mono" style="color: #fff;">{{ run.get('model', 'gemini-3.5-flash-lite') }}</td>
                                <td class="mono" style="font-weight: 600; color: var(--accent-blue);">
                                    {% if run.get('comparisons_added') is defined %}
                                        +{{ run.get('comparisons_added') }} comparisons
                                    {% elif run.get('cross_comparisons_added') is defined %}
                                        +{{ run.get('cross_comparisons_added') }} comparisons
                                    {% elif run.get('items_recompared') is defined %}
                                        {{ run.get('items_recompared') }} items re-ranked
                                    {% else %}
                                        —
                                    {% endif %}
                                </td>
                                <td class="mono">
                                    {% if run.get('new_templates') is defined %}
                                        {{ run.get('new_templates') }} templates
                                    {% else %}
                                        —
                                    {% endif %}
                                </td>
                                <td class="mono">{{ run.get('total_scored', '—') }}</td>
                                <td class="mono">
                                    {% if run.get('elapsed_seconds') is defined %}
                                        {{ run.get('elapsed_seconds') }}s
                                    {% else %}
                                        —
                                    {% endif %}
                                </td>
                            </tr>
                            {% endfor %}
                        {% else %}
                            <tr><td colspan="8" style="text-align: center; padding: 20px; color: var(--text-muted);">No rating runs logged yet. Click "Run Incremental Rating" to execute the first run.</td></tr>
                        {% endif %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- ════════════════════════════════════════════════════════════════ -->
    <!-- TAB 5: DATA MANAGEMENT & DOWNLOADS                               -->
    <!-- ════════════════════════════════════════════════════════════════ -->
    <div id="tab-data" class="tab-pane">
        <div id="alert-box" class="alert-box"></div>

        <div class="section-box">
            <div class="section-title">
                <span>🔄 Data File Synchronization &amp; Storage Maintenance</span>
            </div>
            <p style="color: var(--text-secondary); margin-bottom: 14px;">
                Flush, re-index, and synchronize raw batches into clean datasets for academic analysis.
            </p>
            <button id="btn-update" class="btn btn-primary" onclick="triggerUpdateUploads()">
                🔄 Update Uploads File
            </button>
        </div>

        <div class="section-box">
            <div class="section-title"><span>📥 Raw Research Datasets &amp; Downloads</span></div>
            <p style="color: var(--text-secondary); margin-bottom: 14px; font-size: 12.5px;">
                Download complete annotated datasets or grab the bundled ZIP package containing all files and the standalone offline viewer.
            </p>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-bottom: 14px;">
                <a href="/api/download/bundle" class="btn btn-primary" style="justify-content: space-between; padding: 12px;">
                    <span>📦 <strong>dataset_bundle.zip</strong></span>
                    <span class="mono">All + Viewer</span>
                </a>
                <a href="/viewer" target="_blank" class="btn btn-secondary" style="justify-content: space-between; padding: 12px;">
                    <span>🌐 <strong>Open Offline Viewer</strong></span>
                    <span class="mono">HTML</span>
                </a>
                <a href="/api/download/suggestions.jsonl" class="btn btn-secondary" style="justify-content: space-between; padding: 12px;">
                    <span>📄 <strong>suggestions.jsonl</strong></span>
                    <span class="mono">Flat</span>
                </a>
                <a href="/api/download/uploads.jsonl" class="btn btn-secondary" style="justify-content: space-between; padding: 12px;">
                    <span>📦 <strong>uploads.jsonl</strong></span>
                    <span class="mono">Batches</span>
                </a>
                <a href="/api/download/reports.jsonl" class="btn btn-secondary" style="justify-content: space-between; padding: 12px;">
                    <span>🚩 <strong>reports.jsonl</strong></span>
                    <span class="mono">Feedback</span>
                </a>
                <a href="/api/download/lexicon.json" class="btn btn-secondary" style="justify-content: space-between; padding: 12px;">
                    <span>📚 <strong>lexicon.json</strong></span>
                    <span class="mono">Lexicon</span>
                </a>
            </div>
        </div>

        <!-- Raw Bias Lexicon Table -->
        <div class="section-box">
            <div class="section-title">
                <span>📚 Raw Bias Lexicon Dictionary ({{ lexicon_size }})</span>
                <input type="text" id="lexicon-filter" class="search-input" style="min-width: 200px;" placeholder="Filter lexicon..." onkeyup="filterLexiconTable()">
            </div>
            <div class="table-responsive" style="max-height: 380px;">
                <table id="lexicon-table">
                    <thead><tr><th>Term / Suggestion</th><th>Continuous Score</th><th>Details / Mouseover Tooltip</th></tr></thead>
                    <tbody>
                        {% for suggestion, val in lexicon.items() %}
                        {% set score_val = val.score if val is mapping and val.score is defined else (val.maxScore if val is mapping and val.maxScore is defined else (val if val is number else 0.0)) %}
                        <tr class="lexicon-row">
                            <td style="color: #fff; font-weight: 500;">{{ suggestion }}</td>
                            <td>
                                {% if score_val is not none and score_val > 0 %}
                                    <span class="badge {% if score_val >= 0.65 %}badge-red{% elif score_val >= 0.35 %}badge-yellow{% else %}badge-gray{% endif %}">
                                        {{ "%.2f"|format(score_val) }}
                                    </span>
                                {% else %}
                                    <span class="badge badge-gray">0.00 (Neutral)</span>
                                {% endif %}
                            </td>
                            <td style="color: var(--text-secondary); font-size: 12.5px;">
                                {% if val is mapping and val.mouseover %}
                                    {{ val.mouseover }}
                                {% else %}
                                    —
                                {% endif %}
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- ════════════════════════════════════════════════════════════════ -->
    <!-- TAB 6: STATISTICS & NUMBERS                                      -->
    <!-- ════════════════════════════════════════════════════════════════ -->
    <div id="tab-stats" class="tab-pane">
        <div class="card-grid">
            <div class="card">
                <div class="card-value" id="val-uploads">{{ upload_count }}</div>
                <div class="card-label">Total Upload Batches</div>
            </div>
            <div class="card">
                <div class="card-value" id="val-entries">{{ entry_count }}</div>
                <div class="card-label">Search Queries</div>
            </div>
            <div class="card">
                <div class="card-value" id="val-suggestions">{{ total_suggestions }}</div>
                <div class="card-label">Suggestions Captured</div>
            </div>
            <div class="card">
                <div class="card-value" id="val-unique">{{ unique_queries_count }}</div>
                <div class="card-label">Unique Query Terms</div>
            </div>
            <div class="card">
                <div class="card-value">{{ report_count }}</div>
                <div class="card-label">User Feedback Reports</div>
            </div>
            <div class="card">
                <div class="card-value">{{ lexicon_size }}</div>
                <div class="card-label">Lexicon Entries</div>
            </div>
        </div>
    </div>

<script>
// Tab Switching
function switchTab(tabId, btnEl) {
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.getElementById(tabId).classList.add('active');
    btnEl.classList.add('active');
}

// Main Table Search Filter
function filterMainTable() {
    const filter = (document.getElementById('search-filter').value || '').toLowerCase();
    const userFilter = document.getElementById('user-filter') ? document.getElementById('user-filter').value : '';
    const rows = document.querySelectorAll('#main-table tbody tr.data-row');
    let visible = 0;
    rows.forEach(row => {
        const text = row.innerText.toLowerCase();
        const user = row.getAttribute('data-user') || '';
        const matchText = !filter || text.includes(filter);
        const matchUser = !userFilter || user === userFilter;
        const show = matchText && matchUser;
        row.style.display = show ? '' : 'none';
        if (show) visible++;
    });
    const ind = document.getElementById('rows-indicator');
    if (ind) ind.textContent = `Showing ${visible} queries`;
}

function filterByUserTag() {
    filterMainTable();
}

// Reports Filter
function filterReportsTable() {
    const filter = (document.getElementById('report-filter').value || '').toLowerCase();
    const selectedType = document.getElementById('report-type-select').value;
    const rows = document.querySelectorAll('#reports-table tbody tr.report-row');
    rows.forEach(row => {
        const text = row.innerText.toLowerCase();
        const type = row.getAttribute('data-type') || '';
        const matchText = !filter || text.includes(filter);
        const matchType = !selectedType || type === selectedType;
        row.style.display = (matchText && matchType) ? '' : 'none';
    });
}
function filterReportsByType() { filterReportsTable(); }

// Lexicon Filter
function filterLexiconTable() {
    const filter = (document.getElementById('lexicon-filter').value || '').toLowerCase();
    const rows = document.querySelectorAll('#lexicon-table tbody tr.lexicon-row');
    rows.forEach(row => {
        const text = row.innerText.toLowerCase();
        row.style.display = (!filter || text.includes(filter)) ? '' : 'none';
    });
}

// Limit Selector
function changeLimit(limit) {
    const rows = document.querySelectorAll('#main-table tbody tr.data-row');
    const max = limit === 'all' ? rows.length : parseInt(limit, 10);
    rows.forEach((row, idx) => {
        row.style.display = idx < max ? '' : 'none';
    });
    document.getElementById('rows-indicator').textContent = `Showing ${Math.min(rows.length, max)} entries`;
}

// Table Sorter
function sortTable(tableId, colIndex) {
    const table = document.getElementById(tableId);
    const tbody = table.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    const isAsc = table.getAttribute('data-sort-col') == colIndex && table.getAttribute('data-sort-dir') === 'asc';
    const dir = isAsc ? 'desc' : 'asc';
    table.setAttribute('data-sort-col', colIndex);
    table.setAttribute('data-sort-dir', dir);

    rows.sort((a, b) => {
        const valA = a.children[colIndex]?.getAttribute('data-sort') || a.children[colIndex]?.innerText.trim() || '';
        const valB = b.children[colIndex]?.getAttribute('data-sort') || b.children[colIndex]?.innerText.trim() || '';
        return dir === 'asc' ? valA.localeCompare(valB) : valB.localeCompare(valA);
    });
    rows.forEach(r => tbody.appendChild(r));
}

// ─── Bias Scores Explorer Logic ─────────────────────────────────────
let currentScoreCategory = 'all';

function selectCategoryCard(catKey) {
    currentScoreCategory = catKey;
    document.querySelectorAll('.cat-filter-card').forEach(card => card.classList.remove('active'));
    const targetCard = document.getElementById('cat-card-' + catKey);
    if (targetCard) targetCard.classList.add('active');

    const selectEl = document.getElementById('scores-category-select');
    if (selectEl) selectEl.value = catKey;

    filterScoresTable();
}

function onCategorySelectChange(catKey) {
    selectCategoryCard(catKey);
}

function filterScoresTable() {
    const textFilter = (document.getElementById('scores-filter').value || '').toLowerCase();
    const catFilter = currentScoreCategory || 'all';
    const threshold = parseFloat(document.getElementById('scores-threshold-select').value || '0.0');

    const rows = document.querySelectorAll('#scores-table tbody tr.score-row');
    let visibleCount = 0;

    rows.forEach(row => {
        const term = row.getAttribute('data-term') || '';
        const rowText = row.innerText.toLowerCase();
        const score = parseFloat(row.getAttribute('data-score') || '0.0');
        const primary = row.getAttribute('data-primary') || '';
        const catScore = catFilter !== 'all' ? parseFloat(row.getAttribute('data-' + catFilter) || '0.0') : score;

        const matchText = !textFilter || term.includes(textFilter) || rowText.includes(textFilter);
        const matchCategory = (catFilter === 'all') || (catScore > 0) || (primary === catFilter);
        const matchScore = catFilter === 'all' ? (score >= threshold) : (catScore >= threshold);

        if (matchText && matchCategory && matchScore) {
            row.style.display = '';
            visibleCount++;
        } else {
            row.style.display = 'none';
        }
    });

    const ind = document.getElementById('scores-count-indicator');
    if (ind) ind.textContent = `Showing ${visibleCount} of ${rows.length} entries`;
}

function onSortSelectChange(sortVal) {
    const table = document.getElementById('scores-table');
    const tbody = document.getElementById('scores-table-body');
    const rows = Array.from(tbody.querySelectorAll('tr.score-row'));

    if (sortVal === 'score-desc') {
        rows.sort((a, b) => parseFloat(b.getAttribute('data-score') || '0') - parseFloat(a.getAttribute('data-score') || '0'));
    } else if (sortVal === 'score-asc') {
        rows.sort((a, b) => parseFloat(a.getAttribute('data-score') || '0') - parseFloat(b.getAttribute('data-score') || '0'));
    } else if (sortVal === 'term-asc') {
        rows.sort((a, b) => (a.getAttribute('data-term') || '').localeCompare(b.getAttribute('data-term') || ''));
    } else if (sortVal === 'term-desc') {
        rows.sort((a, b) => (b.getAttribute('data-term') || '').localeCompare(a.getAttribute('data-term') || ''));
    } else if (sortVal.startsWith('cat-')) {
        const cat = sortVal.replace('cat-', '');
        rows.sort((a, b) => parseFloat(b.getAttribute('data-' + cat) || '0') - parseFloat(a.getAttribute('data-' + cat) || '0'));
    }

    rows.forEach(r => tbody.appendChild(r));
}

function sortScoresByColumn(colIndex, isNumeric) {
    const table = document.getElementById('scores-table');
    const tbody = document.getElementById('scores-table-body');
    const rows = Array.from(tbody.querySelectorAll('tr.score-row'));
    const isAsc = table.getAttribute('data-sort-col') == colIndex && table.getAttribute('data-sort-dir') === 'asc';
    const dir = isAsc ? 'desc' : 'asc';
    table.setAttribute('data-sort-col', colIndex);
    table.setAttribute('data-sort-dir', dir);

    rows.sort((a, b) => {
        let valA = a.children[colIndex]?.getAttribute('data-sort') || a.children[colIndex]?.innerText.trim() || '';
        let valB = b.children[colIndex]?.getAttribute('data-sort') || b.children[colIndex]?.innerText.trim() || '';
        if (isNumeric) {
            valA = parseFloat(valA) || 0;
            valB = parseFloat(valB) || 0;
            return dir === 'asc' ? valA - valB : valB - valA;
        }
        return dir === 'asc' ? valA.localeCompare(valB) : valB.localeCompare(valA);
    });
    rows.forEach(r => tbody.appendChild(r));
}

// History Filter
function filterHistoryTable(selectedTask) {
    const rows = document.querySelectorAll('#history-table tbody tr.history-row');
    rows.forEach(row => {
        const task = row.getAttribute('data-task') || '';
        row.style.display = (!selectedTask || task === selectedTask) ? '' : 'none';
    });
}

// Async Uploads Synchronization Trigger
async function triggerUpdateUploads() {
    const btn = document.getElementById('btn-update');
    const alertBox = document.getElementById('alert-box');
    btn.disabled = true;
    btn.textContent = '⏳ Updating & Synchronizing...';
    alertBox.style.display = 'none';

    try {
        const res = await fetch('/api/update-uploads', { method: 'POST' });
        const data = await res.json();

        if (res.ok && data.status === 'ok') {
            alertBox.className = 'alert-box alert-success';
            alertBox.innerHTML = '✅ <strong>Uploads file updated successfully!</strong><br>' +
                '• Batches: ' + data.uploadCount + ' (' + (data.uploadsSizeBytes / 1024).toFixed(1) + ' KB)<br>' +
                '• Flat suggestions: ' + data.totalSuggestions + ' (' + (data.suggestionsSizeBytes / 1024).toFixed(1) + ' KB)<br>' +
                '• Saved at: <code>' + data.uploadsPath + '</code>';
            alertBox.style.display = 'block';
        } else {
            throw new Error(data.message || 'Update failed');
        }
    } catch (err) {
        alertBox.className = 'alert-box alert-error';
        alertBox.innerHTML = '❌ <strong>Error updating uploads file:</strong> ' + err.message;
        alertBox.style.display = 'block';
    } finally {
        btn.disabled = false;
        btn.textContent = '🔄 Update Uploads File';
    }
}

// ─── Two-Stage Model Selector Management ─────────────────────────────
let modelCatalogData = null;

async function loadModelCatalog(forceRefresh = false) {
    const statusEl = document.getElementById('model-status-indicator');
    if (statusEl) {
        statusEl.className = 'badge badge-yellow';
        statusEl.textContent = forceRefresh ? '⏳ Refreshing...' : '⏳ Loading...';
    }

    try {
        const url = forceRefresh ? '/api/models/refresh' : '/api/models/available';
        const method = forceRefresh ? 'POST' : 'GET';
        const res = await fetch(url, { method });
        const data = await res.json();
        
        if (forceRefresh) {
            const catRes = await fetch('/api/models/available');
            modelCatalogData = await catRes.json();
        } else {
            modelCatalogData = data;
        }

        renderModelSelector();
        if (statusEl) {
            statusEl.className = 'badge badge-green';
            statusEl.textContent = '✓ Ready';
        }
    } catch (err) {
        console.error('Failed to load model catalog:', err);
        if (statusEl) {
            statusEl.className = 'badge badge-red';
            statusEl.textContent = '⚠️ Check Failed';
        }
    }
}

function renderModelSelector() {
    if (!modelCatalogData || !modelCatalogData.providers) return;

    const providerSelect = document.getElementById('selector-provider');
    if (!providerSelect) return;

    const currentVal = providerSelect.value || modelCatalogData.default_provider;
    providerSelect.innerHTML = modelCatalogData.providers.map(p => {
        const keyTag = p.has_key ? ' [✓ Key Active]' : ' [No key in .env]';
        let icon = '🤖';
        if (p.id === 'thki') icon = '🎓';
        else if (p.id === 'gemini') icon = '🌐';
        else if (p.id === 'local') icon = '💻';

        return `<option value="${p.id}" ${p.id === currentVal ? 'selected' : ''}>
            ${icon} ${p.name} (${p.badge})${keyTag}
        </option>`;
    }).join('');

    onProviderChange();
}

function onProviderChange() {
    const providerSelect = document.getElementById('selector-provider');
    const modelSelect = document.getElementById('selector-model');
    const envNote = document.getElementById('provider-env-note');
    const lastCheckedLabel = document.getElementById('model-last-checked-label');
    const customWrap = document.getElementById('model-custom-wrap');

    if (!modelCatalogData || !providerSelect || !modelSelect) return;

    const pId = providerSelect.value;
    const provider = modelCatalogData.providers.find(p => p.id === pId);
    if (!provider) return;

    // Update env note
    if (provider.has_key) {
        envNote.style.color = 'var(--accent-green)';
        envNote.innerHTML = `<span>✓ Key active: <code>${provider.key_env}</code> configured in environment.</span>`;
    } else if (pId === 'local') {
        envNote.style.color = 'var(--accent-blue)';
        envNote.innerHTML = `<span>💻 Local inference via OpenAI-compatible endpoint (e.g. Ollama / vLLM).</span>`;
    } else {
        envNote.style.color = 'var(--accent-yellow)';
        envNote.innerHTML = `<span>⚠️ <code>${provider.key_env}</code> not configured in <code>.env</code>.</span>`;
    }

    // Update last checked
    if (pId === 'thki' && modelCatalogData.thki_last_checked) {
        const days = modelCatalogData.thki_days_old !== undefined ? `${modelCatalogData.thki_days_old}d ago` : '';
        lastCheckedLabel.textContent = `Checked: ${modelCatalogData.thki_last_checked} (${days})`;
    } else {
        lastCheckedLabel.textContent = 'Provider: ' + provider.name;
    }

    // Populate models
    modelSelect.innerHTML = (provider.models || []).map(m => {
        const recTag = m.recommended ? ' ⭐ [Recommended]' : '';
        return `<option value="${m.id}">${m.name || m.id}${recTag}</option>`;
    }).join('');

    if (pId === 'local') {
        customWrap.style.display = 'block';
    } else {
        customWrap.style.display = 'none';
    }

    onModelChange();
}

function onModelChange() {
    const providerSelect = document.getElementById('selector-provider');
    const modelSelect = document.getElementById('selector-model');
    const descNote = document.getElementById('model-desc-note');

    if (!modelCatalogData || !providerSelect || !modelSelect || !descNote) return;

    const pId = providerSelect.value;
    const mId = modelSelect.value;
    const provider = modelCatalogData.providers.find(p => p.id === pId);
    if (!provider) return;

    const modelObj = (provider.models || []).find(m => m.id === mId);
    if (modelObj && modelObj.note) {
        descNote.textContent = modelObj.note;
    } else if (modelObj && modelObj.recommended) {
        descNote.textContent = 'Recommended high-performance model for research ratings.';
    } else {
        descNote.textContent = `Target model: ${mId}. Strictly attributed for this rating run.`;
    }
}

function getSelectedProvider() {
    const el = document.getElementById('selector-provider');
    return el ? el.value : 'thki';
}

function getSelectedModel() {
    const p = getSelectedProvider();
    if (p === 'local') {
        const customEl = document.getElementById('selector-custom-model');
        if (customEl && customEl.value.trim()) return customEl.value.trim();
    }
    const el = document.getElementById('selector-model');
    return el ? el.value : 'openai-gpt5.4-mini';
}

// ─── Rating Engine Trigger & Live Polling ───────────────────────────
let pollInterval = null;

async function triggerRating(mode) {
    const btnInc = document.getElementById('btn-run-incremental');
    const btnInit = document.getElementById('btn-run-initial');
    btnInc.disabled = true;
    btnInit.disabled = true;

    try {
        const res = await fetch('/api/ratings/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                type: mode,
                provider: getSelectedProvider(),
                model: getSelectedModel()
            })
        });
        const data = await res.json();
        if (res.ok) {
            startPollingRating();
        } else {
            alert('Rating start failed: ' + (data.error || res.statusText));
            btnInc.disabled = false;
            btnInit.disabled = false;
        }
    } catch (e) {
        alert('Request failed: ' + e.message);
        btnInc.disabled = false;
        btnInit.disabled = false;
    }
}

function startPollingRating() {
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(pollRatingStatus, 1000);
    pollRatingStatus();
}

async function pollRatingStatus() {
    try {
        const res = await fetch('/api/ratings/status');
        const state = await res.json();

        const titleEl = document.getElementById('rating-job-title');
        const subtitleEl = document.getElementById('rating-job-subtitle');
        const percentEl = document.getElementById('rating-progress-percent');
        const barEl = document.getElementById('rating-progress-bar');
        const modelBadge = document.getElementById('rating-model-badge');

        if (modelBadge && state.model) modelBadge.textContent = 'Model: ' + state.model;
        if (percentEl) percentEl.textContent = state.progress + '%';
        if (barEl) {
            barEl.style.width = state.progress + '%';
            if (state.is_running) barEl.classList.add('active-stripes');
            else barEl.classList.remove('active-stripes');
        }

        if (state.is_running) {
            titleEl.textContent = `⏳ Rating Engine Running (${state.mode.toUpperCase()})`;
            subtitleEl.textContent = state.message;
        } else {
            titleEl.textContent = state.stage === 'completed' ? `✅ Rating Completed (${state.mode.toUpperCase()})` : (state.stage === 'failed' ? '❌ Rating Failed' : '⭐ Rating Engine Status: Idle');
            subtitleEl.textContent = state.message;
            document.getElementById('btn-run-incremental').disabled = false;
            document.getElementById('btn-run-initial').disabled = false;
            if (!state.is_running && pollInterval) {
                clearInterval(pollInterval);
                pollInterval = null;
                refreshHistoryTable();
            }
        }

        // Update stage chips
        const stages = ['normalizing', 'identification', 'matchmaking', 'ranking', 'bt_fitting', 'saving'];
        const currentIdx = stages.indexOf(state.stage);

        stages.forEach((stg, idx) => {
            const chip = document.getElementById('stage-' + stg);
            if (!chip) return;
            chip.classList.remove('active', 'done');
            if (stg === state.stage && state.is_running) {
                chip.classList.add('active');
            } else if (state.stage === 'completed' || (currentIdx > idx && currentIdx !== -1)) {
                chip.classList.add('done');
            }
        });

        // Update live console
        const consoleEl = document.getElementById('rating-live-console');
        if (consoleEl && state.logs && state.logs.length > 0) {
            consoleEl.innerHTML = state.logs.map(l => `
                <div class="live-console-line">
                    <span class="live-console-time">[${l.timestamp}]</span>
                    <span>${l.message}</span>
                </div>
            `).join('');
            consoleEl.scrollTop = consoleEl.scrollHeight;
        }
    } catch (err) {
        console.error('Polling error:', err);
    }
}

async function refreshHistoryTable() {
    try {
        const res = await fetch('/api/ratings/history?limit=50');
        const data = await res.json();
        const tbody = document.getElementById('history-table-body');
        if (!tbody || !data.history) return;

        if (data.history.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; padding: 20px; color: var(--text-muted);">No rating runs logged yet.</td></tr>';
            return;
        }

        tbody.innerHTML = data.history.map(run => {
            let taskBadge = '<span class="badge badge-gray">' + (run.task || 'Task') + '</span>';
            if (run.task?.includes('initial')) taskBadge = '<span class="badge badge-purple">Initial Baseline</span>';
            else if (run.task?.includes('incremental')) taskBadge = '<span class="badge badge-green">Incremental</span>';
            else if (run.task?.includes('daily')) taskBadge = '<span class="badge badge-blue">Daily Auto</span>';
            else if (run.task?.includes('weekly')) taskBadge = '<span class="badge badge-yellow">Weekly Re-rank</span>';

            let statusBadge = '<span class="badge badge-gray">' + (run.status || 'N/A') + '</span>';
            if (run.status === 'completed') statusBadge = '<span class="badge badge-green">Completed</span>';
            else if (run.status === 'started') statusBadge = '<span class="badge badge-yellow">Running...</span>';
            else if (run.status === 'failed') statusBadge = '<span class="badge badge-red">Failed</span>';

            let comps = '—';
            if (run.comparisons_added !== undefined) comps = `+${run.comparisons_added} comparisons`;
            else if (run.cross_comparisons_added !== undefined) comps = `+${run.cross_comparisons_added} comparisons`;
            else if (run.items_recompared !== undefined) comps = `${run.items_recompared} items re-ranked`;

            const templates = run.new_templates !== undefined ? `${run.new_templates} templates` : '—';
            const total = run.total_scored !== undefined ? run.total_scored : '—';
            const elapsed = run.elapsed_seconds !== undefined ? `${run.elapsed_seconds}s` : '—';

            return `
                <tr class="history-row" data-task="${run.task || ''}">
                    <td class="mono">${(run.timestamp || '').slice(0, 19)}</td>
                    <td>${taskBadge}</td>
                    <td>${statusBadge}</td>
                    <td class="mono" style="color: #fff;">${run.model || 'gemini-3.5-flash-lite'}</td>
                    <td class="mono" style="font-weight: 600; color: var(--accent-blue);">${comps}</td>
                    <td class="mono">${templates}</td>
                    <td class="mono">${total}</td>
                    <td class="mono">${elapsed}</td>
                </tr>
            `;
        }).join('');
    } catch (e) {
        console.error('Failed to refresh history:', e);
    }
}

// Auto-start polling if server is currently running a rating
{% if rating_state.is_running %}
startPollingRating();
{% endif %}

// Initialize model catalog on load
loadModelCatalog();
</script>
</body>
</html>
"""


# ─── API Endpoints ───────────────────────────────────────────────────


@app.route('/api/models/available', methods=['GET'])
@app.route('/models/available', methods=['GET'])
def get_available_models():
    """Return catalog of available models grouped by provider with env key status."""
    has_thki_key = bool(os.environ.get("THKI_KEY"))
    has_gemini_key = bool(os.environ.get("GOOGLE_API_KEY"))
    has_openai_key = bool(os.environ.get("OPENAI_API_KEY"))

    # Discover / retrieve THKI models
    thki_info = {"last_checked": "unknown", "models": []}
    try:
        from bias_engine.thki_discovery import check_and_update_thki_models
        thki_info = check_and_update_thki_models(data_dir=Path(DATA_DIR))
    except Exception as e:
        thki_info = {"error": str(e), "models": []}

    thki_models = thki_info.get("models", [])
    if not thki_models:
        thki_models = [
            {"id": "openai-gpt5.4-mini", "name": "OpenAI GPT-5.4 Mini", "recommended": True},
            {"id": "mistralai-mistral-small-4-119b-2603", "name": "Mistral Small 4 119B", "recommended": True},
            {"id": "qwen3-omni-30b-a3b-instruct", "name": "Qwen 3 Omni 30B", "recommended": True},
        ]

    providers = [
        {
            "id": "thki",
            "name": "TH Köln KI Connect",
            "badge": "Free Campus LLM",
            "has_key": has_thki_key,
            "key_env": "THKI_KEY",
            "last_checked": thki_info.get("last_checked", "unknown"),
            "models": thki_models
        },
        {
            "id": "gemini",
            "name": "Google Gemini",
            "badge": "Google Cloud",
            "has_key": has_gemini_key,
            "key_env": "GOOGLE_API_KEY",
            "models": [
                {"id": "gemini-3.5-flash-lite", "name": "Gemini 3.5 Flash Lite", "recommended": True, "note": "Latest fast lite model"},
                {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "recommended": False},
                {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro", "recommended": False}
            ]
        },
        {
            "id": "openai",
            "name": "OpenAI Cloud",
            "badge": "Commercial API",
            "has_key": has_openai_key,
            "key_env": "OPENAI_API_KEY",
            "models": [
                {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "recommended": True},
                {"id": "gpt-4o", "name": "GPT-4o", "recommended": False}
            ]
        },
        {
            "id": "local",
            "name": "Local / Ollama",
            "badge": "Self-Hosted",
            "has_key": bool(os.environ.get("LOCAL_LLM_BASE_URL")),
            "key_env": "LOCAL_LLM_BASE_URL",
            "models": [
                {"id": "llama3.2", "name": "Llama 3.2", "recommended": True},
                {"id": "mistral", "name": "Mistral 7B", "recommended": False},
                {"id": "custom", "name": "Custom Model (via LOCAL_LLM_BASE_URL)", "recommended": False}
            ]
        }
    ]

    default_provider = "thki" if has_thki_key else ("gemini" if has_gemini_key else "local")
    default_model = "openai-gpt5.4-mini" if has_thki_key else ("gemini-3.5-flash-lite" if has_gemini_key else "llama3.2")

    return jsonify({
        "providers": providers,
        "default_provider": default_provider,
        "default_model": default_model,
        "thki_last_checked": thki_info.get("last_checked", "unknown"),
        "thki_days_old": thki_info.get("days_old", 0)
    })


@app.route('/api/models/refresh', methods=['POST'])
@app.route('/models/refresh', methods=['POST'])
@require_admin
def refresh_models():
    """Force fresh check of THKI models from API."""
    try:
        from bias_engine.thki_discovery import check_and_update_thki_models
        res = check_and_update_thki_models(data_dir=Path(DATA_DIR), force=True)
        return jsonify({
            "status": "ok",
            "message": f"Successfully updated THKI models ({len(res.get('models', []))} models found).",
            "data": res
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


@app.route('/api/ratings/start', methods=['POST'])
@app.route('/ratings/start', methods=['POST'])
@require_admin
def start_rating_job():
    """Trigger an initial or incremental rating run in background."""
    with RATING_STATE_LOCK:
        if RATING_STATE["is_running"]:
            return jsonify({
                "status": "busy",
                "error": "A rating job is already running in background.",
                "job": RATING_STATE
            }), 409

    data = request.get_json() or {}
    mode = data.get("type", data.get("mode", "incremental")).lower()
    if mode not in ["initial", "incremental"]:
        mode = "incremental"

    provider = data.get("provider")
    model = data.get("model")

    thread = threading.Thread(target=run_rating_job_thread, args=(mode, provider, model), daemon=True)
    thread.start()

    with RATING_STATE_LOCK:
        current_job = dict(RATING_STATE)

    return jsonify({
        "status": "started",
        "mode": mode,
        "provider": provider,
        "model": model,
        "message": f"Started {mode} rating job in background with {model or current_job['model']}.",
        "job": current_job
    }), 200


@app.route('/api/ratings/status', methods=['GET'])
@app.route('/ratings/status', methods=['GET'])
@require_admin
def get_rating_status():
    """Get current rating job status and logs."""
    with RATING_STATE_LOCK:
        state = dict(RATING_STATE)
        state["logs"] = list(RATING_STATE["logs"])
    return jsonify(state)


@app.route('/api/ratings/history', methods=['GET'])
@app.route('/ratings/history', methods=['GET'])
@require_admin
def get_rating_history():
    """Get historical rating runs from task_journal.jsonl."""
    limit = request.args.get("limit", 50, type=int)
    history = load_rating_history(limit=limit)
    return jsonify({
        "total": len(history),
        "history": history
    })


@app.route('/api/upload', methods=['POST'])
@app.route('/upload', methods=['POST'])
def upload_data():
    """Receive scraped data from the Chrome extension."""
    data = request.get_json()
    if not data or 'entries' not in data:
        return jsonify({'error': 'Invalid payload: missing "entries" field'}), 400

    entries = data.get('entries', [])
    if not entries:
        return jsonify({'message': 'No entries to process'}), 200

    received_at = datetime.utcnow().isoformat() + 'Z'
    version = data.get('version') or data.get('extensionVersion', '1.1.0')
    v_tag = data.get('v_tag') or data.get('versionTag', 'Silurian')
    batch_user_pseudonym = data.get('user_pseudonym') or data.get('user_tag') or 'anonymous'

    cleaned_entries = []
    flat_suggestions = []

    for entry in entries:
        query = entry.get('query', '')
        tld = entry.get('googleTld', '')
        lang = entry.get('language', '')
        ts = entry.get('timestamp', received_at)
        entry_user_pseudonym = entry.get('user_pseudonym') or entry.get('user_tag') or batch_user_pseudonym

        cleaned_suggs = []
        for s in entry.get('suggestions', []):
            raw_s_text = s.get('text', '') if isinstance(s, dict) else str(s)
            score_val = s.get('score', s.get('bias_score')) if isinstance(s, dict) else None
            cleaned_s_text = clean_suggestion_text(raw_s_text)

            if cleaned_s_text:
                cleaned_suggs.append({
                    'text': cleaned_s_text,
                    'score': score_val
                })
                flat_suggestions.append({
                    'timestamp': ts,
                    'query': query,
                    'suggestion': cleaned_s_text,
                    'score': score_val,
                    'googleTld': tld,
                    'language': lang,
                    'user_pseudonym': entry_user_pseudonym,
                    'user_tag': entry_user_pseudonym,
                    'version': version,
                    'v_tag': v_tag,
                    'receivedAt': received_at
                })

        if cleaned_suggs:
            cleaned_entry = dict(entry)
            cleaned_entry['suggestions'] = cleaned_suggs
            cleaned_entry['user_pseudonym'] = entry_user_pseudonym
            cleaned_entry['user_tag'] = entry_user_pseudonym
            cleaned_entries.append(cleaned_entry)

    if not cleaned_entries:
        return jsonify({'message': 'No valid suggestions after cleaning'}), 200

    record = {
        'receivedAt': received_at,
        'extensionVersion': version,
        'version': version,
        'versionTag': v_tag,
        'v_tag': v_tag,
        'user_pseudonym': batch_user_pseudonym,
        'user_tag': batch_user_pseudonym,
        'entryCount': len(cleaned_entries),
        'entries': cleaned_entries
    }

    with open(UPLOAD_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')

    with open(SUGGESTIONS_FILE, 'a', encoding='utf-8') as f:
        for s_rec in flat_suggestions:
            f.write(json.dumps(s_rec, ensure_ascii=False) + '\n')

    print(f"[{received_at}] Received {len(cleaned_entries)} entries ({len(flat_suggestions)} suggestions) from [{batch_user_pseudonym}] [v{version} - {v_tag}]")

    return jsonify({
        'status': 'ok',
        'received': len(cleaned_entries),
        'suggestionsSaved': len(flat_suggestions),
        'user_pseudonym': batch_user_pseudonym,
        'version': version,
        'v_tag': v_tag,
        'message': f'Successfully received {len(cleaned_entries)} entries with {len(flat_suggestions)} suggestions.'
    }), 200


@app.route('/api/report', methods=['POST'])
@app.route('/report', methods=['POST'])
@app.route('/api/feedback', methods=['POST'])
@app.route('/feedback', methods=['POST'])
def report_feedback():
    """Receive user reports or feedback regarding autocomplete suggestions or bias labels."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid payload: JSON body required'}), 400

    received_at = datetime.utcnow().isoformat() + 'Z'
    report_type = data.get('reportType', 'feedback')
    query = data.get('query', '')
    raw_suggs = data.get('suggestions', [])
    comment = data.get('comment', '').strip()
    google_tld = data.get('googleTld', '')
    language = data.get('language', '')
    user_pseudonym = data.get('user_pseudonym') or data.get('user_tag') or 'anonymous'
    version = data.get('version') or data.get('extensionVersion', '1.1.0')
    v_tag = data.get('v_tag') or data.get('versionTag', 'Silurian')

    cleaned_suggs = []
    for s in raw_suggs:
        if isinstance(s, dict):
            raw_text = s.get('text', '')
            score = s.get('score', s.get('bias_score'))
        else:
            raw_text = str(s)
            score = None
        cleaned_text = clean_suggestion_text(raw_text)
        if cleaned_text:
            cleaned_suggs.append({
                'text': cleaned_text,
                'score': score
            })

    report_record = {
        'receivedAt': received_at,
        'timestamp': data.get('timestamp', received_at),
        'reportType': report_type,
        'query': query,
        'suggestions': cleaned_suggs,
        'comment': comment,
        'googleTld': google_tld,
        'language': language,
        'user_pseudonym': user_pseudonym,
        'user_tag': user_pseudonym,
        'version': version,
        'v_tag': v_tag
    }

    with open(REPORTS_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(report_record, ensure_ascii=False) + '\n')

    print(f"[{received_at}] Feedback report logged from [{user_pseudonym}]: type={report_type}, query='{query}', comment='{comment[:40]}'")

    return jsonify({
        'status': 'ok',
        'receivedAt': received_at,
        'user_pseudonym': user_pseudonym,
        'version': version,
        'v_tag': v_tag,
        'message': 'Report received and saved successfully.',
        'report': report_record
    }), 200


@app.route('/api/reports', methods=['GET'])
@app.route('/reports', methods=['GET'])
def get_reports():
    """Retrieve submitted reports (supports pagination and filtering)."""
    limit = request.args.get('limit', 50, type=int)
    report_type = request.args.get('type')
    query_filter = request.args.get('query')

    reports = []
    if os.path.exists(REPORTS_FILE):
        with open(REPORTS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        reports.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

    if report_type:
        reports = [r for r in reports if r.get('reportType') == report_type]
    if query_filter:
        reports = [r for r in reports if query_filter.lower() in r.get('query', '').lower()]

    reports.reverse()
    paged = reports[:limit]

    return jsonify({
        'total': len(reports),
        'limit': limit,
        'reports': paged
    })


@app.route('/api/suggestions', methods=['GET'])
@app.route('/suggestions', methods=['GET'])
def get_suggestions():
    """Query collected flat suggestions."""
    limit = request.args.get('limit', 100, type=int)
    query_filter = request.args.get('query', '').strip().lower()

    suggestions = []
    if os.path.exists(SUGGESTIONS_FILE):
        with open(SUGGESTIONS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rec = json.loads(line)
                        if query_filter and query_filter not in rec.get('query', '').lower():
                            continue
                        suggestions.append(rec)
                    except json.JSONDecodeError:
                        continue

    suggestions.reverse()
    return jsonify({
        'total': len(suggestions),
        'limit': limit,
        'suggestions': suggestions[:limit]
    })


@app.route('/api/viewer-data', methods=['GET'])
@app.route('/viewer-data', methods=['GET'])
def get_viewer_data():
    """Return consolidated live research data (lexicon, recent searches, reports) for the viewer."""
    limit_searches = request.args.get('limit_searches', 1000, type=int)
    limit_reports = request.args.get('limit_reports', 500, type=int)

    lexicon = load_lexicon()

    all_searches = []
    total_suggestions = 0
    if os.path.exists(UPLOAD_FILE):
        with open(UPLOAD_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    upload = json.loads(line)
                    up_user = upload.get('user_pseudonym') or upload.get('user_tag') or 'anonymous'
                    up_version = upload.get('version') or upload.get('extensionVersion', '')
                    up_vtag = upload.get('v_tag') or upload.get('versionTag', '')
                    up_received = upload.get('receivedAt', '')

                    for entry in upload.get('entries', []):
                        suggs = entry.get('suggestions', [])
                        total_suggestions += len(suggs)
                        entry_copy = dict(entry)
                        entry_user = entry.get('user_pseudonym') or entry.get('user_tag') or up_user
                        entry_copy['user_pseudonym'] = entry_user
                        if not entry_copy.get('version'):
                            entry_copy['version'] = up_version
                        if not entry_copy.get('v_tag'):
                            entry_copy['v_tag'] = up_vtag
                        if not entry_copy.get('receivedAt'):
                            entry_copy['receivedAt'] = up_received
                        all_searches.append(entry_copy)
                except json.JSONDecodeError:
                    continue

    reports = []
    if os.path.exists(REPORTS_FILE):
        with open(REPORTS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        reports.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

    recent_searches = list(reversed(all_searches[-limit_searches:]))
    recent_reports = list(reversed(reports[-limit_reports:]))

    return jsonify({
        'status': 'ok',
        'lexicon': lexicon,
        'lexiconSize': len(lexicon),
        'searches': recent_searches,
        'totalSearches': len(all_searches),
        'totalSuggestions': total_suggestions,
        'reports': recent_reports,
        'totalReports': len(reports),
        'server': 'BrowseBias Server'
    })


@app.route('/api/score', methods=['POST'])
@app.route('/score', methods=['POST'])
def score_suggestion():
    """Score a single suggestion in real time against the bias lexicon."""
    data = request.get_json()
    if not data or 'suggestion' not in data:
        return jsonify({'error': 'Missing suggestion in request body'}), 400

    lexicon = load_lexicon()
    s_text = data['suggestion'].strip()
    s_lower = s_text.lower()

    if s_lower in lexicon:
        entry = lexicon[s_lower]
        if isinstance(entry, dict):
            return jsonify({
                'suggestion': s_text,
                'score': float(entry.get('score', entry.get('maxScore', 0.0))),
                'scores': entry.get('scores', {}),
                'mouseover': entry.get('mouseover', ''),
                'source': 'lexicon'
            })
        else:
            return jsonify({
                'suggestion': s_text,
                'score': float(entry) if isinstance(entry, (int, float)) else 0.0,
                'scores': {},
                'mouseover': '',
                'source': 'lexicon'
            })
    else:
        return jsonify({
            'suggestion': s_text,
            'score': 0.0,
            'scores': {},
            'mouseover': 'This suggestion appears neutral.',
            'source': 'unknown'
        })


@app.route('/privacy', methods=['GET'])
@app.route('/legal/privacy_policy.html', methods=['GET'])
def get_privacy_policy():
    """Serve the legal privacy policy page."""
    policy_path = os.path.join(os.path.dirname(__file__), '..', 'plugin', 'legal', 'privacy_policy.html')
    if os.path.exists(policy_path):
        with open(policy_path, 'r', encoding='utf-8') as f:
            return f.read(), 200, {'Content-Type': 'text/html; charset=utf-8'}
    return "Privacy Policy not found.", 404


@app.route('/api/lexicon', methods=['GET'])
@app.route('/lexicon', methods=['GET'])
def get_lexicon():
    """Return the full bias lexicon."""
    lexicon = load_lexicon()
    return jsonify({
        'lexicon': lexicon,
        'updatedAt': datetime.utcnow().isoformat() + 'Z',
        'size': len(lexicon)
    })


@app.route('/api/lexicon', methods=['POST'])
@app.route('/lexicon', methods=['POST'])
@require_admin
def update_lexicon():
    """Update the bias lexicon (admin endpoint)."""
    data = request.get_json()
    if not data or 'lexicon' not in data:
        return jsonify({'error': 'Invalid payload: missing "lexicon" field'}), 400

    new_entries = data['lexicon']
    lexicon = load_lexicon()
    lexicon.update(new_entries)

    with open(LEXICON_FILE, 'w', encoding='utf-8') as f:
        json.dump(lexicon, f, indent=2)

    return jsonify({
        'status': 'ok',
        'updated': len(new_entries),
        'total': len(lexicon)
    })


@app.route('/api/update-uploads', methods=['POST', 'GET'])
@app.route('/update-uploads', methods=['POST', 'GET'])
@require_admin
def update_uploads():
    """Force-sync / update the uploads.jsonl and suggestions.jsonl files on disk."""
    entries = []
    source_file = UPLOAD_FILE
    if not os.path.exists(UPLOAD_FILE) or os.path.getsize(UPLOAD_FILE) == 0:
        backup = UPLOAD_FILE + '.bak'
        if os.path.exists(backup):
            source_file = backup

    if os.path.exists(source_file):
        with open(source_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

    cleaned_uploads = []
    flat_suggestions = []

    for batch in entries:
        received_at = batch.get('receivedAt', datetime.utcnow().isoformat() + 'Z')
        ext_version = batch.get('version') or batch.get('extensionVersion', '1.0.3')
        v_tag = batch.get('v_tag') or batch.get('versionTag', 'Ordovician')
        cleaned_entries = []

        for entry in batch.get('entries', []):
            query = entry.get('query', '')
            tld = entry.get('googleTld', '')
            lang = entry.get('language', '')
            ts = entry.get('timestamp', received_at)

            cleaned_suggs = []
            for s in entry.get('suggestions', []):
                raw_s_text = s.get('text', '') if isinstance(s, dict) else str(s)
                score_val = s.get('score', s.get('bias_score')) if isinstance(s, dict) else None
                cleaned_s_text = clean_suggestion_text(raw_s_text)

                if cleaned_s_text:
                    cleaned_suggs.append({
                        'text': cleaned_s_text,
                        'score': score_val
                    })
                    flat_suggestions.append({
                        'timestamp': ts,
                        'query': query,
                        'suggestion': cleaned_s_text,
                        'score': score_val,
                        'googleTld': tld,
                        'language': lang,
                        'version': ext_version,
                        'v_tag': v_tag,
                        'receivedAt': received_at
                    })

            if cleaned_suggs:
                cleaned_entry = dict(entry)
                cleaned_entry['suggestions'] = cleaned_suggs
                cleaned_entries.append(cleaned_entry)

        if cleaned_entries:
            cleaned_uploads.append({
                'receivedAt': received_at,
                'extensionVersion': ext_version,
                'version': ext_version,
                'versionTag': v_tag,
                'v_tag': v_tag,
                'entryCount': len(cleaned_entries),
                'entries': cleaned_entries
            })

    with open(UPLOAD_FILE, 'w', encoding='utf-8') as f:
        for b in cleaned_uploads:
            f.write(json.dumps(b, ensure_ascii=False) + '\n')
        f.flush()
        os.fsync(f.fileno())

    with open(SUGGESTIONS_FILE, 'a', encoding='utf-8') as f:
        for s in flat_suggestions:
            f.write(json.dumps(s, ensure_ascii=False) + '\n')
        f.flush()
        os.fsync(f.fileno())

    uploads_size = os.path.getsize(UPLOAD_FILE) if os.path.exists(UPLOAD_FILE) else 0
    suggestions_size = os.path.getsize(SUGGESTIONS_FILE) if os.path.exists(SUGGESTIONS_FILE) else 0

    return jsonify({
        'status': 'ok',
        'message': 'Successfully updated and synchronized uploads file on disk.',
        'uploadsPath': UPLOAD_FILE,
        'suggestionsPath': SUGGESTIONS_FILE,
        'uploadCount': len(cleaned_uploads),
        'totalSuggestions': len(flat_suggestions),
        'uploadsSizeBytes': uploads_size,
        'suggestionsSizeBytes': suggestions_size
    })


@app.route('/api/download/<filename>', methods=['GET'])
@app.route('/download/<filename>', methods=['GET'])
def download_file(filename):
    """Download data files."""
    allowed_files = {'uploads.jsonl', 'suggestions.jsonl', 'reports.jsonl', 'lexicon.json', 'task_journal.jsonl'}
    if filename not in allowed_files:
        return jsonify({'error': 'File not allowed'}), 404

    target_path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(target_path):
        target_path = os.path.join(ENGINE_STATE_DIR, filename)
        if not os.path.exists(target_path):
            if filename == 'lexicon.json':
                with open(LEXICON_FILE, 'w', encoding='utf-8') as f:
                    json.dump(DEFAULT_LEXICON, f, indent=2)
            else:
                return jsonify({'error': 'File not found'}), 404

    return send_from_directory(os.path.dirname(target_path), os.path.basename(target_path), as_attachment=True)


@app.route('/api/download/bundle', methods=['GET'])
@app.route('/download/bundle', methods=['GET'])
@app.route('/api/download/dataset_bundle.zip', methods=['GET'])
@app.route('/download/dataset_bundle.zip', methods=['GET'])
def download_bundle():
    """Package current dataset into a clean zip archive including the offline HTML viewer."""
    import zipfile
    import io

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for fname in ['suggestions.jsonl', 'uploads.jsonl', 'reports.jsonl', 'lexicon.json']:
            fpath = os.path.join(DATA_DIR, fname)
            if os.path.exists(fpath):
                zip_file.write(fpath, arcname=f"dataset/{fname}")

        # Include standalone HTML viewer in the bundle
        viewer_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'viewer', 'dataset_viewer.html')
        if os.path.exists(viewer_path):
            zip_file.write(viewer_path, arcname="dataset_viewer.html")

        readme_txt = (
            "BrowseBias Research Dataset Bundle (v1.1.0 Silurian)\n"
            "====================================================\n\n"
            "This bundle contains collected search autocomplete data, reports, and lexicons.\n\n"
            "Quickstart:\n"
            "1. Double-click `dataset_viewer.html` to open the offline viewer in your browser.\n"
            "2. Drag and drop `dataset/suggestions.jsonl` into the viewer window.\n"
            "3. Filter by query, bias score, cohort pseudonym, or category.\n"
        )
        zip_file.writestr("README.txt", readme_txt)

    zip_buffer.seek(0)
    return send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name='browsebias_dataset_bundle.zip'
    )


@app.route('/viewer', methods=['GET'])
def serve_viewer():
    """Serve the standalone dataset viewer directly from the browser."""
    viewer_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'viewer', 'dataset_viewer.html')
    if os.path.exists(viewer_path):
        return send_file(viewer_path)
    return "Standalone viewer file not found at " + viewer_path, 404


if __name__ == '__main__':
    init_lexicon()
    port = int(os.environ.get('PORT', 8765))
    print("=" * 60)
    print("  Autocomplete Bias — Research & Test Server")
    print(f"  http://localhost:{port}")
    print("=" * 60)
    print(f"  Data directory: {DATA_DIR}")
    print(f"  Lexicon entries: {len(load_lexicon())}")
    print("=" * 60)
    app.run(host='0.0.0.0', port=port, debug=True)
