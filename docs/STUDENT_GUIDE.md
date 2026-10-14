# BrowseBias — Auditor & Study Participant Guide

Welcome to the **BrowseBias** empirical audit toolkit. This guide walks you through installing the browser extension, auditing Google autocomplete suggestions, setting your privacy-preserving cohort tag, running the automated collector simulator, and exploring datasets with the offline multi-tab viewer.

---

## 🚀 Quick Navigation
1. [Installing the Chrome Extension](#1-installing-the-chrome-extension)
2. [Setting Your Pseudonym / Cohort Tag](#2-setting-your-pseudonym--cohort-tag)
3. [Configuring Server Target: Online vs. Local Server](#3-configuring-server-target-online-vs-local-server)
4. [Auditing Google Search Autocomplete](#4-auditing-google-search-autocomplete)
5. [Reporting Problematic Suggestions](#5-reporting-problematic-suggestions)
6. [Running the Automated Collector (Easy GUI)](#6-running-the-automated-collector-easy-gui)
7. [Downloading Datasets & Local Fallback Export](#7-downloading-datasets--local-fallback-export)
8. [Offline Dataset Inspection with the Standalone Viewer](#8-offline-dataset-inspection-with-the-standalone-viewer)

---

## 1. Installing the Chrome Extension

The extension runs in **Google Chrome**, **Brave**, **Microsoft Edge**, or any Chromium-based browser.

```
  ┌────────────────────────────────────────────────────────┐
  │ 1. Open chrome://extensions                            │
  │ 2. Enable "Developer mode" in the top-right corner     │
  │ 3. Click "Load unpacked"                               │
  │ 4. Select the "plugin" folder inside BrowseBias        │
  └────────────────────────────────────────────────────────┘
```

1. Open your browser and navigate to `chrome://extensions/`
2. In the top-right corner, switch the **Developer mode** toggle to **ON**.
3. In the top-left corner, click **Load unpacked**.
4. Select the `plugin/` folder in the `BrowseBias` repository.
5. The **Autocomplete Bias** icon will appear in your browser toolbar. Pin it for quick access!

---

## 2. Setting Your Pseudonym / Cohort Tag

To preserve privacy while allowing researchers to compare how Google autocomplete behaves across different participant cohorts and geographic environments, the extension automatically assigns you an anonymous pseudonym (e.g. `Curious-Fox-42`).

```
+-------------------------------------------------------+
|  [Logo] Autocomplete Bias        v1.1.0 [Silurian]    |
+-------------------------------------------------------+
|  SETTINGS                                             |
|  Bias Highlighting             [ ON  ]                |
|  Data Logging                  [ ON  ]                |
|  Auto-Upload Sync              [ Every 1 hour ▼ ]     |
|                                                       |
|  Server Target                                        |
|  [ Online Server (Hugging Face)                     ▼]|
|                                                       |
|  User Tag / Pseudonym                                 |
|  Auditor cohort or participant tag                    |
|  [ Curious-Fox-42       ]  [Save]  [🎲]               |
+-------------------------------------------------------+
```

1. Click the **Autocomplete Bias** extension icon in your browser toolbar.
2. In the **Settings** section, locate **User Tag / Pseudonym**.
3. You can:
   - Keep your auto-assigned pseudonym.
   - Click the **🎲 Randomize** button to generate a new anonymous animal tag.
   - Enter your assigned research group tag (e.g. `CohortA-Group2`, `Audit-DE-01`) and click **Save**.
4. All subsequent search recordings and feedback reports will be attributed cleanly to this cohort pseudonym.

### Debugging: Inspecting Last Captured Suggestions

To verify that Google autocomplete suggestions are being properly captured and scored:
1. Open the plugin popup.
2. Under **Settings**, click **🔍 Inspect** on the **Captured Suggestions** row.
3. A collapsible drawer appears displaying:
   - The query, domain, and timestamp.
   - The list of captured autocomplete suggestions with their numerical bias pills (High, Moderate, Low, Neutral).
   - Navigation buttons (`◀` / `▶`) to step backward and forward through recently captured queries.
   - **📋 Copy JSON** to copy the capture data to your clipboard, or **{ } Raw** to view the raw JSON payload.

---

## 3. Configuring Server Target: Online vs. Local Server

BrowseBias supports both cloud research collection and fully offline/local student self-hosting.

### Option A: Online Server (Default — Zero Setup)
- **Default Target:** `Online Server (Hugging Face)`
- Students do not need to install Python, run background services, or manage ports. All suggestions and reports sync seamlessly to the course cloud backend.
- The Status section displays `Active Server: Online (HF)` with a green badge.

### Option B: Local Server (Optional — Self-Hosted)
If you would like to run your own local backend and retain full ownership of all collected data:
1. Open a terminal in the `BrowseBias` folder and start the local server:
   ```bash
   python server/app.py
   ```
   (Listens on `http://localhost:8765`)
2. In the plugin popup, change **Server Target** to:
   `Local Server (localhost:8765)`
3. The extension immediately switches its sync endpoint, lexicon URL, and report channels to your local machine.

### Option C: Custom Server URL
If your instructor or research group provides a dedicated URL (e.g. a university server or private Hugging Face space), select `Custom Server URL...`, enter the base URL (e.g. `https://my-course-bias-server.hf.space`), and click **Save**.

---

## 4. Auditing Google Search Autocomplete

1. Navigate to [Google Search](https://www.google.de) or [Google.com](https://www.google.com).
2. Start typing a query (e.g. `"olaf scholz skandal"`, `"climate change"`, or `"asylbewerber"`).
3. Observe the dropdown autocomplete suggestions:
   - Neutral suggestions appear standard.
   - Suggestions with potential controversy, defamation, or political bias display an inline color pill.
   - **Hover your mouse** over any pill to view an explanatory tooltip and the confidence score.

```
Google Search Box: [ olaf scholz skandal                 ]
──────────────────────────────────────────────────────────
🔍 olaf scholz skandal cum ex         [ 🔴 High Bias ]
   └── Tooltip: "Score: 0.85 · Defamation / Controversy"
🔍 olaf scholz skandal wirecard       [ 🟡 Moderate  ]
🔍 olaf scholz partei                 [ Neutral      ]
```

---

## 5. Reporting Problematic Suggestions

If you encounter an autocomplete suggestion that you observe is harmful, defamatory, or incorrectly labeled:

1. Click the **Autocomplete Bias** icon in your toolbar.
2. The popup detects your active Google search query.
3. Click either:
   - `🚨 Problematic Suggestions` (for defamation, conspiracy theories, extremist tropes)
   - `🏷️ Wrong Bias Labels` (if a label was assigned inaccurately)
4. Add an optional comment explaining why you flagged it.
5. Click **🚀 Submit Report**. Your feedback is transmitted securely to the research server.

---

## 6. Running the Automated Collector (Easy GUI)

To systematically collect autocomplete suggestions across extensive keyword datasets without manual typing, use the cross-platform **Collector Simulator** with its local web GUI.

### Launching the GUI:
- **macOS:** Double-click `collector/run_collector_gui.command` (or run `python start_collector.py`)
- **Windows:** Double-click `collector/run_collector_gui.bat` (or run `python start_collector.py`)
- **Linux:** Run `./collector/run_collector_gui.sh` (or run `python start_collector.py`)

A browser window will open automatically at `http://localhost:8766`:

```
+─────────────────────────────────────────────────────────────────+
|  BrowseBias Collector — Runner GUI               [ ● Idle ]     |
+─────────────────────────────────────────────────────────────────+
|  Extension Path: /path/to/BrowseBias/plugin  [ ✓ Ready ]        |
+─────────────────────────────────────────────────────────────────+
|  Simulation Settings:                                           |
|  • Keyword Source:  [ Preset File ▼ ]                          |
|  • Preset:          [ keywords_bundestag.txt (Politicians) ▼ ] |
|  • Google Domain:   [ https://www.google.de ▼ ]                |
|  • Alphabet Cycle:  [x] Type trailing ' a'..' z' expansions    |
|  • Pause Between:   [ 1.5 seconds (Standard) ▼ ]               |
|                                                                 |
|  [ ▶ Start Collection ]     [ ⏹ Stop Collection ]              |
+─────────────────────────────────────────────────────────────────+
|  Live Output:                                                   |
|  > [1/736] Typing 'Olaf Scholz'...                              |
|  > Cycling 'Olaf Scholz a' ... 'Olaf Scholz z'                  |
+─────────────────────────────────────────────────────────────────+
```

1. Select a keyword preset or paste your own custom keywords.
2. Choose your **Google Domain** and **Interface Language** (defaults to `de-DE` for German searches, but English, French, and Spanish are available).
3. Click **▶ Start Collection**.
4. A Playwright browser window will launch and simulate natural human typing speeds, triggering Google autocomplete while the extension captures and scores the suggestions.
5. **Important:** Do *not* minimize the simulator browser window to your Dock or Taskbar! Minimizing strips window focus, which causes Google to close the autocomplete dropdown. You may keep the window unminimized in the background behind other open programs.
6. Click **⏹ Stop Collection** anytime to pause or stop.

---

## 7. Downloading Datasets & Local Fallback Export

In the extension popup, under **Data & Privacy**, you will find the **📥 Download Annotated Dataset** button.

The button dynamically adapts to your selected server target:

1. **When Online (or Local Server is Running):**
   - The extension contacts the active server (`/api/download/suggestions.jsonl`).
   - Your browser downloads the aggregated, annotated suggestions dataset collected across all audit runs.

2. **When Local Server is Offline / Not Running:**
   - If you switched to `Local Server (localhost:8765)` but have not started `python server/app.py`, the extension does **not** fail with an error or broken page.
   - Instead, it automatically exports all autocomplete suggestions recorded directly inside your own browser as a clean JSON file named:
     `browsebias_student_dataset_<cohort_tag>.json`
   - You can immediately open or import this file into the offline viewer or submit it to your course instructor.

---

## 8. Offline Dataset Inspection with the Standalone Viewer

To inspect and explore your collected research datasets without needing to run a server:

1. Locate the file `viewer/dataset_viewer.html` in the repository.
2. **Double-click it** to open it in any web browser (`file:///...`).
3. Drag & drop your downloaded `suggestions.jsonl`, `uploads.jsonl`, `reports.jsonl`, `lexicon.json`, or exported `browsebias_student_dataset_*.json` file into the dashed box.
4. Or click **⚡ Load Realistic Audit Sample** to explore the multi-tab interface immediately!

### Viewer Features:
- **🔍 Autocomplete Searches Tab:** Filter by query, cohort tag, domain, or bias level; view all 10 suggestions per row.
- **⚖️ Bias Dimensions Tab:** Explore continuous Bradley-Terry scores across all 6 core dimensions (`POL`, `ACC`, `CON`, `SEX`, `RAC`, `REL`) with gradient heatbars and explanatory notes.
- **📋 Participant Reports Tab:** Inspect flagged suggestions, bias types, and participant qualitative feedback.
- **📊 Numbers & Cohort Statistics Tab:** Distribution bar charts, dimension frequency breakdowns, and auditor cohort comparison tables.
- **Exporting:** Click **📥 Export CSV** or **📥 Export JSON** on any active tab for downstream data analysis in Python, R, or spreadsheet software.
