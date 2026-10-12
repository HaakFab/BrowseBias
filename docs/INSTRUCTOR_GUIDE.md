# BrowseBias — Researcher & Server Administrator Guide

This guide is designed for primary investigators, researchers, and administrators deploying **BrowseBias** for empirical algorithmic auditing, university research, and public interest studies.

---

## 📋 Table of Contents
1. [Server Setup & Configuration](#1-server-setup--configuration)
2. [Scientific Model Selection & THKI Discovery](#2-scientific-model-selection--thki-discovery)
3. [Orchestrating the Bias Rating Pipeline](#3-orchestrating-the-bias-rating-pipeline)
4. [Auditing Participant Cohorts & Pseudonyms](#4-auditing-participant-cohorts--pseudonyms)
5. [Exporting & Distributing Research Datasets](#5-exporting--distributing-research-datasets)

---

## 1. Server Setup & Configuration

### Prerequisites
- Python 3.9+
- Dependencies: `pip install flask flask-cors openai pyyaml`

### Starting the Server
From the repository root:
```bash
python server/app.py
```
By default, the server runs on port **8765**:
- Research Dashboard: `http://localhost:8765`
- Standalone Multi-Tab Viewer: `http://localhost:8765/viewer`
- Bundle Download: `http://localhost:8765/api/download/bundle`
- Model Discovery API: `http://localhost:8765/api/models/available`

### Deploying for Participant Access
To allow study participants across local networks, university VPNs, or public domains to upload data:
- Set environment variable `PORT=8765` (or custom port).
- Provide participants with your server IP (e.g. `http://your-server-ip:8765/api/upload`) or reverse-proxied domain to enter in their extension settings.

---

## 2. Scientific Model Selection & THKI Discovery

To ensure rigorous scientific reproducibility, BrowseBias uses a **Two-Stage Model Selector** with strict model provenance: all suggestion tags, comparison groups, and Bradley-Terry pairwise preference matrices in a run are attributed exclusively to the selected model.

```
+─────────────────────────────────────────────────────────────────+
| 🔬 Scientific Model Selector (Two-Stage)                        |
+─────────────────────────────────────────────────────────────────+
| Stage 1: Provider Family                                        |
| [ 🎓 TH Köln KI Connect (Free Campus LLM) [✓ Key Active]  ▼ ]   |
|                                                                 |
| Stage 2: Target Model                                           |
| [ openai-gpt5.4-mini ⭐ [Recommended]                     ▼ ]   |
| Checked: 2026-10-12 (0d ago) · [ 🔄 Check / Refresh Models ]    |
+─────────────────────────────────────────────────────────────────+
```

### Supported Provider Families:
1. **🎓 TH Köln KI Connect (`thki`)**: European campus AI infrastructure (`chat.kiconnect.nrw`).
   - Verified models: `openai-gpt5.4-mini` (recommended fast), `mistralai-mistral-small-4-119b-2603`, `qwen3-omni-30b-a3b-instruct`, `openai-gpt5.5`, `openai-gpt-oss-120b`, `glm-4.7`, `qwen3.5-397b-a17b`.
   - **Automated Discovery (< 14 days)**: On server startup, if `THKI_MODELS_LAST_CHECKED` in `.env` is older than 2 weeks (or missing), the server queries `GET /api/v1/models`, caches the response in `server/data/thki_models.json`, and records the new date stamp in `.env`.
2. **🌐 Google Gemini (`gemini`)**:
   - Default lite model: `gemini-3.5-flash-lite` (most recent high-throughput lite model).
   - Additional models: `gemini-2.5-flash`, `gemini-2.5-pro`.
   - Requires `GOOGLE_API_KEY` in `.env`.
3. **🤖 OpenAI Cloud (`openai`)**:
   - Commercial models: `gpt-4o-mini`, `gpt-4o`.
   - Requires `OPENAI_API_KEY` in `.env`.
4. **💻 Local / OpenAI-Compatible (`local`)**:
   - Self-hosted inference via Ollama, vLLM, or text-generation-inference (`LOCAL_LLM_BASE_URL`).

---

## 3. Orchestrating the Bias Rating Pipeline

On the research server dashboard (`http://localhost:8765`), open the **⭐ Bias Rating Engine** tab.

```
+───────────────────────────────────────────────────────────+
| ⭐ Bias Rating Engine Pipeline                            |
| Model: openai-gpt5.4-mini (Provider: thki)                |
+───────────────────────────────────────────────────────────+
|  [ ⚡ Run Incremental Rating ]   [ 🚀 Run Full Initial Rating ] |
+───────────────────────────────────────────────────────────+
|  Pipeline Progress:                                       |
|  [██████████████████████████████░░] 85% — Fitting Bradley-Terry |
+───────────────────────────────────────────────────────────+
```

### Execution Modes:
1. **Incremental Rating (`incremental`)**:
   - Ingests new unrated suggestions uploaded since the previous run.
   - Normalizes entities via spaCy (`[PERSON]`, `[ORG]`).
   - Identifies candidate bias across 6 dimensions (`POL`, `ACC`, `CON`, `SEX`, `RAC`, `REL`).
   - Generates stratified matchmaking groups and updates Pairwise Comparison Matrices (PCMs).
   - Refits the regularized Bradley-Terry model and updates `lexicon.json`.
2. **Full Initial Rating (`initial`)**:
   - Re-evaluates all captured suggestions from baseline.
   - Re-fits global Bradley-Terry scale anchors across all matrices.

---

## 4. Auditing Participant Cohorts & Pseudonyms

In the **🔍 Recent Searches** and **🚩 User Reports** dashboard tabs:

1. **User / Tag Column:** Each search entry displays the pseudonym tag (e.g. `Curious-Fox-42` or `Audit-Cohort-A`).
2. **Filter by User / Tag Dropdown:** In the toolbar, select any cohort tag to isolate submissions.
3. **Controlled Audit Experiments:**
   - **Control Cohort (Vanilla):** Clean browser profiles without history or cookies.
   - **Treated Cohort (Targeted):** Profiles seeded with specific ideological or commercial browsing patterns.
   - Researchers can evaluate algorithmic variance: whether autocomplete systematically differentiates suggestion rankings for identical root queries based on user signals.

---

## 5. Exporting & Distributing Research Datasets

Under the **⚡ Data & Downloads** tab:

- **📦 dataset_bundle.zip (`/api/download/bundle`)**: Packages all active files into a portable archive:
  - `dataset/suggestions.jsonl` (Full raw search suggestion logs)
  - `dataset/uploads.jsonl` (Batched upload payloads with client metadata)
  - `dataset/reports.jsonl` (Qualitative participant feedback)
  - `dataset/lexicon.json` (Fitted Bradley-Terry continuous scores and tooltips)
  - `dataset_viewer.html` (Standalone 4-tab offline dataset explorer)
  - `README.txt`
- Researchers and participants can download this ZIP bundle and perform exploratory analysis locally in Python, R, or via the included HTML viewer without server dependencies.
