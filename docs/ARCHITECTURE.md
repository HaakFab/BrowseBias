# BrowseBias — System Architecture & Dataflow Specification

**Version:** `1.1.0`  
**Version Tag:** `Silurian`  
**Target Environment:** Academic Research & Public Algorithmic Audit Deployment

---

## 1. High-Level System Architecture

The **BrowseBias** ecosystem consists of 5 modular components designed to operate seamlessly together or independently:

```mermaid
flowchart TB
    subgraph ClientLayer ["1. Client & Extension Layer"]
        User["Auditor / Study Participant"]
        Ext["Chrome Extension (v1.1.0 Silurian)\n- Pseudonym Generator\n- Bias Visual Pills & Tooltips\n- Local Buffer Storage"]
        Collector["Automated Collector\n- Playwright Browser Simulator\n- Cross-Platform Web GUI (Port 8766)"]
        User -->|Searches Google| Ext
        Collector -->|Automated Human Typing| Ext
    end

    subgraph ServerLayer ["2. Research Server & Ingestion Layer"]
        Server["Flask Research Server (Port 8765)\n- /api/upload (Batches)\n- /api/report (Feedback)\n- /api/lexicon (Synced Cache)\n- /api/models/available (Catalog)\n- /api/download/bundle (ZIP)"]
        Dashboard["Interactive Server Console\n- Fluid Dark Theme Dashboard\n- Two-Stage Model Selector\n- Cohort / Pseudonym Filtering\n- Live Rating Monitor"]
        Server <--> Dashboard
        Ext -->|POST /api/upload (Hourly/Manual)| Server
        Ext -->|POST /api/report| Server
        Server -->|GET /api/lexicon| Ext
    end

    subgraph StorageLayer ["3. Storage & Dataset Layer"]
        UploadsFile[("uploads.jsonl\n(Raw Batches)")]
        SuggestionsFile[("suggestions.jsonl\n(Flat Queries & Suggestions)")]
        ReportsFile[("reports.jsonl\n(Participant Feedback)")]
        LexiconFile[("lexicon.json\n(Quantified Scores & Tooltips)")]
        Server --> UploadsFile
        Server --> SuggestionsFile
        Server --> ReportsFile
        Server <--> LexiconFile
    end

    subgraph OfflineLayer ["4. Offline Analysis Tools"]
        Viewer["Standalone HTML Dataset Viewer\n- Single Portable File\n- 4 Rich Research Tabs\n- Bias Dimension Explorer\n- Drag & Drop JSONL\n- CSV / JSON Exporters"]
        Server -.->|Exports Bundle ZIP| Viewer
    end

    subgraph LLMLayer ["5. Bias Quantification Engine & Two-Stage Selection"]
        Engine["Bias Engine Pipeline\n1. spaCy Normalization\n2. Multi-Category Identification\n3. Listwise Matchmaking\n4. Bradley-Terry Logistic Fitting"]
        Models["Scientific Model Providers\n- THKI (chat.kiconnect.nrw/api/v1)\n- Google Gemini (gemini-3.5-flash-lite)\n- OpenAI (gpt-4o-mini)\n- Local (Ollama / vLLM)"]
        Server <--> Engine
        Engine <--> Models
    end
```

---

## 2. Pseudonymized User Tag & Cohort Auditing

To audit whether Google Search autocomplete changes based on user history, cohort location, or search behavior without collecting personal identifiable information (PII):

```
+-------------------------------------------------------------+
|                  Automatic Generation                       |
|   Adjective (24)  +  Animal (24)  +  Number (10..99)        |
|   e.g. "Curious-Fox-42", "Silver-Hawk-88", "Polar-Otter-17"  |
+-------------------------------------------------------------+
                              │
                              ▼
+-------------------------------------------------------------+
|            Plugin Popup Settings (Customizable)             |
|   Auditors can customize tag to cohort code:                |
|   e.g. "CohortA-Auditor01", "AuditGroup-DE", "ControlGroup" |
+-------------------------------------------------------------+
                              │
                              ▼
+-------------------------------------------------------------+
|              Data Payload Propagation                       |
|   - Attached to each search item in chrome.storage.local    |
|   - Sent in batch upload payload: user_pseudonym            |
|   - Stored in suggestions.jsonl & reports.jsonl             |
+-------------------------------------------------------------+
                              │
                              ▼
+-------------------------------------------------------------+
|              Dashboard & Viewer Filtering                   |
|   Researchers can filter table rows and compare autocomplete|
|   variance across participant cohorts and user tags         |
+-------------------------------------------------------------+
```

---

## 3. Two-Stage Scientific Model Selection & Provenance

BrowseBias enforces strict model provenance: all suggestion tags, comparison groups, and Bradley-Terry pairwise preference matrices in a run are attributed exclusively to the selected model.

### 1. Two-Stage Model Selector:
- **Stage 1 (Provider Family):** Select from `THKI` (TH Köln KI Connect), `Google Gemini`, `OpenAI`, or `Local / Ollama`. Providers with active API keys in `.env` are visually badged with `[✓ Key Active]`.
- **Stage 2 (Target Model):** Select the exact model to execute the pipeline (e.g., `openai-gpt5.4-mini` for THKI, or `gemini-3.5-flash-lite` for Google Gemini).

### 2. Periodic THKI Model Discovery (< 14 Days):
- On server startup, the engine checks `THKI_MODELS_LAST_CHECKED` in `.env`.
- If the date is older than 14 days or missing, it queries `GET https://chat.kiconnect.nrw/api/v1/models` using `THKI_KEY`.
- Discovered models are saved to `server/data/thki_models.json` and the `.env` timestamp is automatically updated.
- Researchers can also trigger an immediate check via the dashboard's `[ 🔄 Check / Refresh Models ]` button.

---

## 4. Multi-Category Framework & Bradley-Terry Scoring

The quantification pipeline categorizes potential bias into 6 core dimensions:
1. `POL`: Political Ideology & Partisan Slant
2. `ACC`: Accusation & Defamation
3. `CON`: Conspiracy & Esotericism
4. `SEX`: Sexism & Gender Bias
5. `RAC`: Racism & Xenophobia
6. `REL`: Religious Bias

Latent bias scores are estimated using a regularized Bradley-Terry paired comparison model:

$$P(i \succ j) = \frac{e^{\alpha (s_i - s_j)}}{1 + e^{\alpha (s_i - s_j)}}$$

Continuous scores are normalized into $[0.00, 1.00]$ and persisted into `server/data/lexicon.json`.
