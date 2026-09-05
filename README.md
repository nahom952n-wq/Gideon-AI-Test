# Gideon / ScholarMind

Gideon is an existing Flask application for collecting, processing, and tracking scholarships, internships, fellowships, grants, competitions, jobs, and related opportunities. This version is a **refinement of the existing application**, not a rebuild.

## Run locally

From the directory containing `run.py`:

```bash
python -m venv venv
# Windows PowerShell
venv\Scripts\Activate.ps1
# macOS/Linux
source venv/bin/activate
pip install -r requirements.txt
# Optional: create a .env file for deployment-level defaults, or use Settings in the UI.
python run.py
```

Open `http://127.0.0.1:5000` after the server starts.

## Run with the modified Telegram Web client

Run the two applications in separate terminals. They intentionally use
different loopback ports:

```powershell
# Terminal 1 — Gideon backend
cd C:\Users\bamla\Downloads\Telegram-web-z\Gideon-share
py -3.14 run.py

# Terminal 2 — Telegram Web frontend
cd C:\Users\bamla\Downloads\Telegram-web-z\Telegram-web-z
npm run dev
```

Open `http://localhost:1234` for Telegram Web and
`http://127.0.0.1:5000/dashboard` for Gideon. Telegram Web sends extracted
message batches to `http://127.0.0.1:5000/api/v1/ingest/telegram`; the backend
does not connect to Telegram or require Telegram API credentials.

For the tray desktop shell, install the requirements and run:

```powershell
cd C:\Users\bamla\Downloads\Telegram-web-z\Gideon-share
py -3.14 -m pip install -r requirements.txt
py -3.14 desktop.py
```

The tray shell starts Gideon on `127.0.0.1:5000`. Start Telegram Web separately
on `localhost:1234`, then use the tray menu to open either application.

## AI Providers & API Keys

Open **Settings → AI Providers & API Keys**. The page supports Google Gemini, OpenAI, Anthropic Claude, xAI Grok, and local OpenAI-compatible endpoints such as Ollama or LM Studio. Each provider has a model field and a **Test** action. The local provider uses an endpoint URL rather than a cloud API key.

Saved values are encrypted before they are stored in the `api_key_settings` database table. Environment variables remain supported as a fallback, and Replit users may use Replit Secrets instead of saving keys through the UI. The interface intentionally never displays a stored secret; it only reports whether a value is configured and whether a manual connection test succeeded.

The **Capability routing** form lets you select a provider for summarization, structured extraction, reasoning, translation, classification, vision analysis, chat, and OCR. These choices are stored separately and are loaded by `AIRouter` at request time, so changes take effect without restarting the application. Local AI retains its confidence-based cloud fallback behavior.

## Environment fallback

At minimum, set a Flask secret in `.env`:

```dotenv
FLASK_SECRET_KEY=replace-with-a-long-random-value
```

You can also configure providers through environment variables, including `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GROK_API_KEY`, `LOCAL_AI_URL`, and the corresponding model settings. The Settings page is the recommended way to save credentials for this application.

## Security note

> API keys are sensitive. Do not share screenshots of the API-key settings page or commit `.env`, runtime databases, session files, or backups to source control.

For production or shared deployments, use a strong unique `FLASK_SECRET_KEY`, restrict access to the Settings page, and prefer the deployment platform’s secret manager.

## Verification

The included `smoke_test.py` checks that the Settings page renders, the provider registry includes Grok, encrypted provider settings can be resolved, routing preferences persist, and a saved provider can be cleared. It does not call any external AI service:

```bash
python smoke_test.py
```
