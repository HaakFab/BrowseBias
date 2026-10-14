---
title: Browsebias
emoji: ⚖️
colorFrom: indigo
colorTo: blue
sdk: gradio
app_file: app.py
pinned: false
license: mit
---

# BrowseBias — Algorithmic Audit & Autocomplete Bias Research Ecosystem

[![Version](https://img.shields.io/badge/version-1.1.0-blue.svg)](https://github.com/HaakFab/BrowseBias)
[![Tag](https://img.shields.io/badge/release%20tag-Silurian-green.svg)](https://github.com/HaakFab/BrowseBias)
[![License](https://img.shields.io/badge/license-MIT-purple.svg)](LICENSE)
[![Institution](https://img.shields.io/badge/Institution-TH%20K%C3%B6ln-red.svg)](https://www.th-koeln.de)
[![LLM Infrastructure](https://img.shields.io/badge/LLM-TH%20K%C3%B6ln%20KI%20Connect-orange.svg)](https://chat.kiconnect.nrw)
[![Gemini Lite](https://img.shields.io/badge/Gemini-3.5%20flash%20lite-blueviolet.svg)](https://ai.google.dev)

**BrowseBias** is an academic research platform and open-source audit ecosystem designed to systematically capture, quantify, and analyze potential bias, defamatory framing, and ideological slant in Google Search autocomplete recommendations.

Originally developed for empirical research and algorithmic accountability at **TH Köln (University of Applied Sciences)**, BrowseBias provides researchers, auditors, and the public with a reproducible, privacy-preserving infrastructure for large-scale web audits.

---

## 🔌 Browser Extension: Installation & Settings Guide

The **BrowseBias Chrome Extension (v1.1.0 Silurian)** runs directly inside your browser, providing real-time autocomplete analysis, privacy-preserving data collection, and participant feedback tools.

### 📥 Step-by-Step Installation

The extension is compatible with **Google Chrome**, **Brave**, **Microsoft Edge**, and any Chromium-based browser.

```
┌────────────────────────────────────────────────────────────────────────┐
│ 1. Open your browser and go to: chrome://extensions                     │
│ 2. Turn ON the "Developer mode" toggle in the top-right corner.        │
│ 3. Click the "Load unpacked" button in the top-left corner.            │
│ 4. Browse to and select the "plugin" directory in this repository.     │
│ 5. Pin the "Autocomplete Bias" puzzle icon to your browser toolbar!    │
└────────────────────────────────────────────────────────────────────────┘
```

---

### ⚙️ Detailed Extension Settings Reference

Click the extension icon in your browser toolbar to open the settings panel:

```
+───────────────────────────────────────────────────────────+
| [Logo] Autocomplete Bias              v1.1.0 [Silurian]   |
+───────────────────────────────────────────────────────────+
| Server API:  [ http://localhost:8765/api/upload         ] |
+───────────────────────────────────────────────────────────+
| REAL-TIME AUDIT SETTINGS                                  |
| • Data Collection Active              [ ● ON  ]           |
| • Highlight Biased Suggestions        [ ● ON  ]           |
| • Sensitivity Threshold               [ ────●───── 0.35 ] |
| • Auto-Upload Sync Schedule           [ Every 1 hour ▼ ]  |
+───────────────────────────────────────────────────────────+
| RESEARCH PARTICIPANT IDENTITY                             |
| • User Tag / Pseudonym: Auditor cohort or participant tag |
|   [ Curious-Fox-42                ]  [ Save ]  [ 🎲 ]     |
+───────────────────────────────────────────────────────────+
| REPORT & FEEDBACK (ACTIVE SEARCH CONTEXT)                 |
| Detected Query: "olaf scholz skandal"                     |
| [ 🚨 Problematic Suggestions ]   [ 🏷️ Wrong Bias Labels ] |
+───────────────────────────────────────────────────────────+
| [ ☁️ Upload Now (3) ]             [ 🗑️ Clear Cache ]      |
+───────────────────────────────────────────────────────────+
```

| Setting | Type / Range | Default | Purpose & Description |
| :--- | :--- | :--- | :--- |
| **Server API Endpoint** | URL | `http://localhost:8765/api/upload` | Base address of the research backend server where collected audit batches and feedback reports are transmitted. |
| **Data Collection Active** | Toggle (`ON`/`OFF`) | `ON` (Opt-in) | Controls whether root queries and dropdown autocomplete suggestions are buffered for empirical research. |
| **Highlight Biased Suggestions** | Toggle (`ON`/`OFF`) | `ON` | Displays real-time visual color pills next to autocomplete entries whose Bradley-Terry score exceeds the sensitivity threshold. |
| **Sensitivity Threshold** | Slider (`0.00` – `1.00`) | `0.35` | Sets the minimum bias intensity required to display visual badges. Lower values flag subtler nuances; higher values highlight severe or controversial suggestions. |
| **Auto-Upload Sync Schedule** | Dropdown | `Every 1 hour` | Schedules background batch uploads using Chrome Alarms (`Every 1 hour`, `Every 24 hours`, or `Manual only`). |
| **User Tag / Pseudonym** | Text (max 32 chars) | `Adjective-Animal-NN` | A privacy-preserving identifier (e.g. `Curious-Fox-42`). Researchers can assign custom cohort tags (e.g. `CohortA-Group1`, `Audit-DE-Control`) using **Save** or re-roll using **🎲**. |
| **Problematic Suggestions** | Feedback Action | — | Flags suggestions that promote unverified criminal accusations, defamation, conspiracy theories, or hate speech. |
| **Wrong Bias Labels** | Feedback Action | — | Reports misclassified suggestions, providing qualitative feedback for model recalibration. |
| **Upload Now** | Action Button | — | Manually flushes locally buffered search sessions to the server immediately. |
| **Clear Cache** | Action Button | — | Clears all unsent search items from local browser memory. |

---

### 🔍 Real-Time Autocomplete Overlay

When auditing Google Search, suggestions exceeding the threshold display subtle color pills. Hovering over a pill provides an explanatory tooltip:

```
Google Search: [ olaf scholz skandal                     ]
──────────────────────────────────────────────────────────
🔍 olaf scholz skandal cum ex             [ 🔴 High Bias ]
   └── Hover Tooltip: "Score: 0.85 · Defamation / Controversy"
🔍 olaf scholz skandal wirecard           [ 🟡 Moderate  ]
🔍 olaf scholz partei                     [ Neutral      ]
```

---

## 🔬 Scientific Model Selection & Model Provenance

To eliminate unscientific multi-model blending within evaluation runs, BrowseBias features a **Two-Stage Model Selector** that enforces **strict single-model provenance**: every suggestion tag, comparison group, and Bradley-Terry pairwise preference matrix in a run is generated by and attributed to one explicitly chosen model.

```
+─────────────────────────────────────────────────────────────────+
| 🔬 Scientific Model Selector (Two-Stage Provenance)              |
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
1. **🎓 TH Köln KI Connect (`thki`)**: Free campus AI infrastructure (`chat.kiconnect.nrw`).
   - Verified models: `openai-gpt5.4-mini` (recommended fast), `mistralai-mistral-small-4-119b-2603`, `qwen3-omni-30b-a3b-instruct`, `openai-gpt5.5`, `openai-gpt-oss-120b`, `glm-4.7`, `qwen3.5-397b-a17b`.
   - **Automated Discovery (< 14 Days)**: On server startup, if `THKI_MODELS_LAST_CHECKED` in `.env` is older than 2 weeks (or missing), the server queries `GET /api/v1/models`, caches the response in `server/data/thki_models.json`, and records the new date stamp in `.env`.
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

## 📂 Standalone Multi-Tab Dataset Viewer (`viewer/dataset_viewer.html`)

A completely self-contained, portable HTML document that allows researchers and the public to explore audit datasets **offline without running a Python server**:

- **🔍 Autocomplete Searches Tab**: View full search queries with all 10 autocomplete suggestions per row, filter by query keyword, domain, bias level, or auditor cohort tag, and sort dynamically.
- **⚖️ Bias Dimensions & Lexicon Tab**: Dedicated views for the 6 core bias categories:
  - 🏛️ Political Ideology (`POL`)
  - ⚖️ Accusation & Defamation (`ACC`)
  - 👁️ Conspiracy & Esotericism (`CON`)
  - ⚧️ Sexism & Gender Bias (`SEX`)
  - 🌍 Racism & Xenophobia (`RAC`)
  - 🕊️ Religious Bias (`REL`)
  - Continuous Bradley-Terry scores (0.00 – 1.00) displayed with gradient heatbars, severity ratings, and explanatory notes.
- **📋 Participant Reports Tab**: Review flagged suggestions, bias types, and participant qualitative notes.
- **📊 Numbers & Cohort Statistics Tab**: Visual severity distribution bars, dimension frequency breakdowns, and auditor cohort comparison tables.
- **Drag-and-Drop Ingestion**: Accepts `suggestions.jsonl`, `uploads.jsonl`, `reports.jsonl`, or `lexicon.json`.
- **Exporting**: One-click **📥 Export CSV** and **📥 Export JSON** for downstream analysis in Python, R, or Excel.

---

## 🖥️ Cross-Platform Automated Collector GUI

For systematic data collection across large keyword lists without manual entry:

- **macOS:** Double-click `collector/run_collector_gui.command` (or run `python start_collector.py`)
- **Windows:** Double-click `collector/run_collector_gui.bat` (or run `python start_collector.py`)
- **Linux:** Run `./collector/run_collector_gui.sh` (or run `python start_collector.py`)

Launches a zero-dependency web controller on `http://localhost:8766` with Playwright human typing simulation, keyword presets (e.g. 736+ Bundestag MP names), and automated 'a'–'z' alphabet expansions.

---

## ⚡ Server Quickstart

```bash
# 1. Install dependencies
pip install flask flask-cors openai pyyaml

# 2. Configure keys in .env
echo "THKI_KEY=your_key_here" >> .env
echo "GOOGLE_API_KEY=your_gemini_key_here" >> .env

# 3. Start the research server
python server/app.py
```

- **Research Dashboard:** `http://localhost:8765`
- **Offline Viewer Web Route:** `http://localhost:8765/viewer`
- **Dataset Bundle Download:** `http://localhost:8765/api/download/bundle` (Packages all active datasets and the viewer into a `.zip` archive).

---

## 📁 Repository Structure

```
BrowseBias/
├── plugin/                           # Chrome Extension (Manifest V3)
│   ├── manifest.json                 # Permissions, storage, background alarms
│   ├── icons/                        # High-resolution extension icons
│   └── src/                          # Content script, background service worker, popup UI
│
├── server/                           # Backend Research API & Dashboard
│   ├── app.py                        # Flask server (Port 8765), bundle packager, web console
│   ├── requirements.txt              # Server dependencies
│   ├── test_server_storage.py        # Integration test suite
│   └── data/                         # Active data directory (git-ignored)
│
├── bias_engine/                      # Scientific Bias Quantification Pipeline
│   ├── thki_discovery.py             # 14-day periodic THKI model discovery & caching
│   ├── llm_providers.py              # THKI, Gemini, OpenAI, and Local providers
│   ├── config.py                     # Provider config & auto-selection
│   ├── default_framework.yaml        # 6-category bias taxonomy & definitions
│   ├── identification.py             # Multi-category LLM batch tagging
│   ├── quantification.py             # Listwise ranking & Bradley-Terry fitting
│   └── tests/                        # Engine unit and integration tests
│
├── collector/                        # Playwright User Input Simulator
│   ├── gui.py                        # Cross-platform local web GUI launcher (Port 8766)
│   ├── collector.py                  # Human typing simulation engine
│   ├── run_collector_gui.command     # macOS one-click launcher
│   ├── run_collector_gui.bat         # Windows one-click launcher
│   ├── run_collector_gui.sh          # Linux one-click launcher
│   ├── keywords.txt                  # German political topics
│   └── keywords_bundestag.txt        # 736+ Bundestag MP names
│
├── viewer/                           # Standalone Offline Analysis Tool
│   └── dataset_viewer.html           # 4-tab drag-and-drop HTML dataset viewer
│
├── docs/                             # Architectural Specifications & Guides
│   ├── ARCHITECTURE.md               # System architecture & sequence diagrams
│   ├── STUDENT_GUIDE.md              # Auditor & study participant guide
│   ├── INSTRUCTOR_GUIDE.md           # Researcher & server administrator guide
│   └── COLLECTOR_GUIDE.md            # Simulator options & rate limit prevention
│
├── start_collector.py                # Root launcher for Collector GUI
├── README.md                         # Documentation & settings reference
└── .gitignore                        # Excludes .env, raw datasets & backups
```

---

## 🔒 Research Ethics & Privacy Guarantee

- **No Personal Identifiable Information (PII)** is collected or stored.
- **Randomized Pseudonyms** allow cohort-based comparison without tracking individuals.
- **Opt-In Participation**: Real-time logging is strictly opt-in via extension settings.
- **Self-Hosted Infrastructure**: All collected data remains on your self-hosted server with zero third-party telemetry.
