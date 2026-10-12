# BrowseBias — Student & Course Participant Guide

Welcome to the **BrowseBias** course toolkit! This guide walks you through installing the browser extension, auditing Google autocomplete suggestions, using your pseudonymized cohort tag, running the automated collector, and viewing collected datasets.

---

## 🚀 Quick Navigation
1. [Installing the Chrome Extension](#1-installing-the-chrome-extension)
2. [Setting Your Pseudonym / Cohort Tag](#2-setting-your-pseudonym--cohort-tag)
3. [Auditing Google Search Autocomplete](#3-auditing-google-search-autocomplete)
4. [Reporting Problematic Suggestions](#4-reporting-problematic-suggestions)
5. [Running the Automated Collector (Easy GUI)](#5-running-the-automated-collector-easy-gui)
6. [Offline Dataset Inspection with the Standalone Viewer](#6-offline-dataset-inspection-with-the-standalone-viewer)

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

To preserve privacy while allowing us to compare how Google autocomplete behaves across different student cohorts, the extension automatically assigns you a unique pseudonym (e.g. `Curious-Fox-42`).

```
+-------------------------------------------------------+
|  [Logo] Autocomplete Bias        v1.1.0 [Silurian]    |
+-------------------------------------------------------+
|  SETTINGS                                             |
|  Bias Highlighting             [ ON  ]                |
|  Data Logging                  [ ON  ]                |
|  Auto-Upload Sync              [ Every 1 hour ▼ ]     |
|                                                       |
|  User Tag / Pseudonym                                 |
|  Audit tag for student cohort                         |
|  [ Curious-Fox-42       ]  [Save]  [🎲]               |
+-------------------------------------------------------+
```

1. Click the **Autocomplete Bias** extension icon in your browser toolbar.
2. In the **Settings** section, locate **User Tag / Pseudonym**.
3. You can:
   - Keep your auto-assigned pseudonym.
   - Click the **🎲 Randomize** button to generate a new animal tag.
   - Enter your assigned cohort code (e.g. `CohortA-Group2`) and click **Save**.
4. All subsequent search recordings and feedback reports will be tagged with this pseudonym.

---

## 3. Auditing Google Search Autocomplete

1. Navigate to [Google Search](https://www.google.de) or [Google.com](https://www.google.com).
2. Start typing a query (e.g. `"olaf scholz skandal"` or `"klimawandel"`).
3. Look at the dropdown autocomplete suggestions:
   - Neutral suggestions appear standard.
   - Suggestions with potential opinion, controversy, defamation, or political bias display an inline color pill.
   - **Hover your mouse** over any pill to read an explanatory tooltip and the confidence score.

```
Google Search Box: [ olaf scholz skandal                 ]
──────────────────────────────────────────────────────────
🔍 olaf scholz skandal cum ex         [ 🔴 High Bias ]
   └── Tooltip: "Score: 0.85 · Defamation / Controversy"
🔍 olaf scholz skandal wirecard       [ 🟡 Moderate  ]
🔍 olaf scholz partei                 [ Neutral      ]
```

---

## 4. Reporting Problematic Suggestions

If you encounter an autocomplete suggestion that you believe is harmful, defamatory, or incorrectly labeled:

1. Click the **Autocomplete Bias** icon in your toolbar.
2. The popup detects your active Google search query.
3. Click either:
   - `🚨 Problematic Suggestions` (for hate speech, defamation, conspiracy theories)
   - `🏷️ Wrong Bias Labels` (if a label was assigned inaccurately)
4. Add an optional comment explaining why you flagged it.
5. Click **🚀 Submit Report**. Your feedback is transmitted securely to the research server.

---

## 5. Running the Automated Collector (Easy GUI)

Rather than typing hundreds of terms manually, you can use the **Collector Simulator** with our intuitive web GUI.

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
2. Click **▶ Start Collection**.
3. A Playwright browser window will open and simulate natural human typing speed, triggering Google autocomplete while the extension captures and scores the suggestions.
4. Click **⏹ Stop Collection** anytime to pause or stop.

---

## 6. Offline Dataset Inspection with the Standalone Viewer

Want to inspect your collected dataset without having to start a Python server?

1. Locate the file `viewer/dataset_viewer.html` in the repository.
2. **Double-click it** to open it in any web browser (`file:///...`).
3. Drag & drop your downloaded `suggestions.jsonl` or `uploads.jsonl` file into the dashed box.
4. Or click **✨ Load Demo Sample** to explore the viewer immediately!

### Viewer Features:
- **Search bar:** Filter queries, suggestions, and user tags in real time.
- **Cohort Filter:** Isolate results submitted by your specific pseudonym tag.
- **Pill Tooltips:** View all 10 autocomplete suggestions per query, complete with bias pills.
- **Column Sorting:** Click any column header to sort ascending or descending.
- **Exporting:** Click **📤 Export CSV** or **📤 Export JSON** to export your filtered slice for homework or data analysis.
