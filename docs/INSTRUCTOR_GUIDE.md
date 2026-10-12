# BrowseBias — Instructor & Research Administrator Guide

This guide is designed for course instructors, teaching assistants, and researchers deploying **BrowseBias** for university courses, student seminars, or large-scale web audit studies.

---

## 📋 Table of Contents
1. [Server Setup & Configuration](#1-server-setup--configuration)
2. [TH Köln KI Connect Models Configuration](#2-th-k%C3%B6ln-ki-connect-models-configuration)
3. [Orchestrating the Bias Rating Pipeline](#3-orchestrating-the-bias-rating-pipeline)
4. [Auditing Student Cohorts & Pseudonyms](#4-auditing-student-cohorts--pseudonyms)
5. [Exporting & Distributing Datasets](#5-exporting--distributing-datasets)

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
- Dashboard: `http://localhost:8765`
- Standalone Viewer: `http://localhost:8765/viewer`
- Bundle Download: `http://localhost:8765/api/download/bundle`

### Deploying for Student Access
To allow students in your local network or university VPN to upload data:
- Set environment variable `PORT=8765` (or desired port).
- Provide students with your server IP (e.g. `http://192.168.1.100:8765/api/upload`) or domain in their extension settings.

---

## 2. TH Köln KI Connect Models Configuration

The LLM pipeline uses **TH Köln KI Connect** (`chat.kiconnect.nrw`), providing zero-cost, compliant AI models for all course participants.

### Setting your API Key
Add your key to the project `.env` file:
```bash
THKI_KEY=your_key_here
```
*(BrowseBias automatically detects and loads `.env` on startup).*

### Multi-Model Fallback Cascade (`thki-cascade`)
The default primary provider in `bias_engine/config.py` is configured to `thki-cascade`. It automatically cycles across 4 top models:

| Model ID | Strengths | Role |
| :--- | :--- | :--- |
| `openai-gpt5.4-mini` | Blazing fast, top reasoning, uses `max_completion_tokens` | **Primary Model** |
| `mistralai-mistral-small-4-119b-2603` | Open weights, high throughput, robust instruction following | **First Fallback** |
| `qwen3-omni-30b-a3b-instruct` | Compact, fast latency, lightweight | **Second Fallback** |
| `openai-gpt-oss-120b` | 120B parameter reasoning model | **Deep Fallback** |

### Automated Circuit Breaker
If the primary model hits **HTTP 429 (rate/usage limit)** or **HTTP 503 (temporary unavailability)**:
- It enters a **60-second cooldown**.
- Subsequent requests automatically route to the next active model in the pool without failing the batch job.
- When the cooldown expires, the primary model is restored.

---

## 3. Orchestrating the Bias Rating Pipeline

On the research server dashboard (`http://localhost:8765`), open the **⭐ Bias Rating Engine** tab.

```
+───────────────────────────────────────────────────────────+
| ⭐ Bias Rating Engine Pipeline                            |
| Current LLM Model: thki-cascade [openai-gpt5.4-mini]       |
+───────────────────────────────────────────────────────────+
|  [ ⚡ Run Incremental Rating ]   [ 🔄 Run Full Initial Rating ] |
+───────────────────────────────────────────────────────────+
|  Pipeline Progress:                                       |
|  [██████████████████████████████░░] 85% — Fitting Bradley-Terry |
+───────────────────────────────────────────────────────────+
```

### Modes:
1. **Incremental Rating (`incremental`)**:
   - Only processes new, unrated suggestions uploaded since the last run.
   - Ideal for daily or hourly maintenance.
2. **Full Initial Rating (`initial`)**:
   - Re-evaluates all captured suggestions across all categories.
   - Re-fits Bradley-Terry pairwise preference matrices and writes a fresh `lexicon.json`.

---

## 4. Auditing Student Cohorts & Pseudonyms

In the **🔍 Recent Searches** and **🚩 User Reports** dashboard tabs:

1. **User / Tag Column:** Each search entry displays the pseudonym tag (e.g. `Curious-Fox-42` or `GroupA-Student1`).
2. **Filter by User / Tag Dropdown:** In the toolbar, select any student tag to isolate their submissions.
3. **Cohort Audit Experiments:**
   - **Group A (Control):** Default vanilla Chrome profiles searching political terms.
   - **Group B (Logged-in / Tailored):** Profiles with specific search histories.
   - Instructors can compare whether Group A and Group B receive distinct autocomplete suggestions for identical root queries.

---

## 5. Exporting & Distributing Datasets

Under the **⚡ Data & Downloads** tab:

- **📦 dataset_bundle.zip (`/api/download/bundle`)**: Generates a clean archive containing:
  - `dataset/suggestions.jsonl`
  - `dataset/uploads.jsonl`
  - `dataset/reports.jsonl`
  - `dataset/lexicon.json`
  - `dataset_viewer.html` (Standalone offline HTML viewer for students)
  - `README.txt`
- Students can download this ZIP bundle and perform exploratory data analysis locally without needing server access.
