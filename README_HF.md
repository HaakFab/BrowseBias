---
title: BrowseBias Research Server
emoji: ⚖️
colorFrom: indigo
colorTo: blue
sdk: gradio
app_file: app.py
pinned: false
license: mit
---

# BrowseBias Server — Algorithmic Bias Collection & Research Platform

This repository is configured for **100% free deployment on Hugging Face Spaces** using the **Gradio SDK** (no paid Docker subscription or credit card required).

## 🚀 Environment Variables / Secrets (Settings -> Variables and secrets)
Configure these secrets in your Hugging Face Space settings:

| Variable | Description | Recommended |
|---|---|---|
| `ADMIN_PASSWORD` | Password required to access admin rating controls. Students do NOT need this to collect or upload data. | `your-secure-pass` |
| `THKI_KEY` | Optional: TH Köln KI Connect API Key for running free campus LLM rating models. | Secret |
| `GOOGLE_API_KEY` | Optional: Gemini API Key for running `gemini-3.5-flash-lite`. | Secret |
| `OPENAI_API_KEY` | Optional: OpenAI API Key for running GPT models. | Secret |

## 📦 Architecture & Free Hosting
- Hugging Face automatically spins up a managed container for free and runs `python app.py`.
- `app.py` exposes the interactive Gradio dashboard for browser visitors at the root (`/`), while mounting all backend Flask endpoints at `/api/...` and `/viewer` via FastAPI/WSGIMiddleware.
- Chrome Extension users connect directly to `https://<your-username>-<your-space-name>.hf.space/api/upload` and `https://<your-username>-<your-space-name>.hf.space/api/lexicon`.
