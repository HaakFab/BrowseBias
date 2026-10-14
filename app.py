#!/usr/bin/env python3
"""
BrowseBias Server — Entrypoint for Hugging Face Spaces (Gradio SDK) & Cloud Deployments.
Combines a native Gradio interface for browser visitors with full WSGI Flask API routing
for Chrome Extension synchronization (/api/upload, /api/lexicon, /api/report, /viewer).
"""
import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ─── Hugging Face ZeroGPU Compatibility ───────────────────────────────
try:
    import spaces
    HAS_SPACES_GPU = True
except ImportError:
    spaces = None
    HAS_SPACES_GPU = False

def gpu_fn(func):
    """Decorator applying @spaces.GPU when running on Hugging Face ZeroGPU."""
    if spaces is not None and hasattr(spaces, "GPU"):
        return spaces.GPU(func)
    return func

# Import the core Flask application
from server.app import (
    app as flask_app,
    DATA_DIR,
    SUGGESTIONS_FILE,
    UPLOAD_FILE,
    REPORTS_FILE,
    LEXICON_FILE,
    RATING_STATE,
    RATING_STATE_LOCK,
    run_rating_job_thread,
    check_admin_auth,
    ADMIN_PASSWORD,
    load_lexicon
)

def get_server_stats():
    """Get live summary metrics from files on disk."""
    total_suggestions = 0
    total_uploads = 0
    total_reports = 0

    if os.path.exists(SUGGESTIONS_FILE):
        try:
            with open(SUGGESTIONS_FILE, "r", encoding="utf-8") as f:
                total_suggestions = sum(1 for line in f if line.strip())
        except Exception:
            pass

    if os.path.exists(UPLOAD_FILE):
        try:
            with open(UPLOAD_FILE, "r", encoding="utf-8") as f:
                total_uploads = sum(1 for line in f if line.strip())
        except Exception:
            pass

    if os.path.exists(REPORTS_FILE):
        try:
            with open(REPORTS_FILE, "r", encoding="utf-8") as f:
                total_reports = sum(1 for line in f if line.strip())
        except Exception:
            pass

    lexicon = load_lexicon()
    return total_suggestions, total_uploads, total_reports, len(lexicon)

# Try importing Gradio + FastAPI + a2wsgi for Hugging Face Spaces
try:
    import gradio as gr
    from fastapi import FastAPI
    from a2wsgi import WSGIMiddleware
    import uvicorn
    HAS_GRADIO = True
except ImportError:
    HAS_GRADIO = False

if HAS_GRADIO:
    # ─── FastAPI Parent Application ─────────────────────────────────
    app = FastAPI(title="BrowseBias Server API")

    # Mount Flask app for all Chrome extension API endpoints, dataset viewer, and legal pages
    app.mount("/api", WSGIMiddleware(flask_app))
    app.mount("/viewer", WSGIMiddleware(flask_app))
    app.mount("/privacy", WSGIMiddleware(flask_app))
    app.mount("/legal", WSGIMiddleware(flask_app))

    # ─── Gradio Web Interface (Served at root for web visitors) ─────
    @gpu_fn
    def refresh_dashboard():
        suggs, uploads, reports, lex_size = get_server_stats()
        return (
            f"**{suggs:,}** suggestions",
            f"**{uploads:,}** batches",
            f"**{reports:,}** reports",
            f"**{lex_size:,}** entries in lexicon"
        )

    def trigger_rating_job(password, mode):
        if ADMIN_PASSWORD and password != ADMIN_PASSWORD:
            return "❌ Error: Invalid Admin Password. Rating jobs require instructor authentication."
        with RATING_STATE_LOCK:
            if RATING_STATE["is_running"]:
                return "⚠️ A rating job is already running in background."
        import threading
        thread = threading.Thread(target=run_rating_job_thread, args=(mode,), daemon=True)
        thread.start()
        return f"🚀 Successfully started {mode} rating job in background!"

    @gpu_fn
    def trigger_rating_incremental(password):
        return trigger_rating_job(password, "incremental")

    @gpu_fn
    def trigger_rating_initial(password):
        return trigger_rating_job(password, "initial")

    @gpu_fn
    def get_rating_logs(password):
        if ADMIN_PASSWORD and password != ADMIN_PASSWORD:
            return "Enter valid Admin Password to view real-time pipeline execution logs."
        with RATING_STATE_LOCK:
            logs = "\n".join(RATING_STATE["logs"][-25:])
            status = RATING_STATE["status"]
            progress = RATING_STATE["progress"]
        return f"Status: {status} ({progress}%)\n\n--- Recent Logs ---\n{logs}"

    with gr.Blocks(title="BrowseBias Research Server", theme=gr.themes.Soft()) as demo:
        gr.Markdown(
            """
            # ⚖️ BrowseBias — Empirical Algorithmic Auditing Platform
            ### Live Research Server & Suggestion Ingestion Hub
            Welcome to the BrowseBias university research server. This instance securely ingests anonymized Google autocomplete suggestions captured by study participants and course auditors.
            """
        )

        with gr.Row():
            status_box = gr.Markdown("🟢 **Server Status:** Active & Ingesting Data · Compatible with Chrome Extension MV3")

        with gr.Tabs():
            with gr.Tab("📊 Live Research Metrics & Datasets"):
                with gr.Row():
                    metric_suggs = gr.Markdown("**Loading...** suggestions")
                    metric_batches = gr.Markdown("**Loading...** batches")
                    metric_reports = gr.Markdown("**Loading...** reports")
                    metric_lex = gr.Markdown("**Loading...** lexicon")

                btn_refresh = gr.Button("🔄 Refresh Metrics", variant="secondary")
                btn_refresh.click(
                    fn=refresh_dashboard,
                    inputs=[],
                    outputs=[metric_suggs, metric_batches, metric_reports, metric_lex]
                )

                gr.Markdown("### 📥 Download Research Datasets")
                with gr.Row():
                    gr.Markdown("- [📥 Download suggestions.jsonl](/api/download/suggestions.jsonl)")
                    gr.Markdown("- [📦 Download Complete Dataset Bundle (.zip)](/api/download/bundle)")
                    gr.Markdown("- [🔍 Open Multi-Tab Standalone Dataset Viewer](/viewer)")

            with gr.Tab("🎓 Student & Auditor Guide"):
                gr.Markdown(
                    """
                    ### How to Connect Your Chrome Extension
                    1. **Install Extension:** Open `chrome://extensions`, enable **Developer mode**, click **Load unpacked**, and select the `plugin/` folder.
                    2. **Default Server Target:** The extension defaults to **Online Server (Hugging Face)**. You are already connected!
                    3. **Privacy & Pseudonym:** In the extension popup, you can randomize your animal pseudonym (e.g. `Curious-Fox-42`) or set an assigned cohort tag (e.g. `CohortA-Group1`).
                    4. **Audit Google Search:** Visit Google Search and start typing queries. Autocomplete suggestions will be highlighted in real-time and securely logged for research.
                    5. **Offline/Local Option:** If you prefer running a local server on your own machine, start `python server/app.py` and switch **Server Target** in the plugin popup to `Local Server (localhost:8765)`.
                    """
                )

            with gr.Tab("🔒 Admin & Rating Pipeline"):
                gr.Markdown("Trigger and inspect the Bradley-Terry bias quantification engine (requires admin authentication).")
                admin_pw = gr.Textbox(label="Admin Password", type="password", placeholder="Enter ADMIN_PASSWORD...")
                with gr.Row():
                    btn_incremental = gr.Button("⚡ Run Incremental Rating", variant="primary")
                    btn_initial = gr.Button("🚀 Run Full Initial Rating", variant="secondary")

                action_output = gr.Textbox(label="Action Result", interactive=False)
                btn_incremental.click(
                    fn=trigger_rating_incremental,
                    inputs=[admin_pw],
                    outputs=[action_output]
                )
                btn_initial.click(
                    fn=trigger_rating_initial,
                    inputs=[admin_pw],
                    outputs=[action_output]
                )

                btn_logs = gr.Button("📋 Check Pipeline Progress & Logs")
                logs_display = gr.Textbox(label="Rating Engine Logs", lines=10, interactive=False)
                btn_logs.click(
                    fn=get_rating_logs,
                    inputs=[admin_pw],
                    outputs=[logs_display]
                )

        # Initialize metrics on load
        demo.load(fn=refresh_dashboard, inputs=[], outputs=[metric_suggs, metric_batches, metric_reports, metric_lex])

    # Mount Gradio app at the root of FastAPI
    app = gr.mount_gradio_app(app, demo, path="/")

else:
    # Fallback to standard Flask app if Gradio / FastAPI are not installed
    app = flask_app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    if HAS_GRADIO:
        print(f"[*] Starting BrowseBias Server with Gradio UI & FastAPI/WSGI routing on port {port}...")
        uvicorn.run("app:app", host="0.0.0.0", port=port, proxy_headers=True)
    else:
        print(f"[*] Starting BrowseBias Server with Flask WSGI on port {port}...")
        flask_app.run(host="0.0.0.0", port=port)
