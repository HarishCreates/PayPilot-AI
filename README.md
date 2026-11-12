# PayPilot AI — Smart Payment Intelligence

PayPilot AI is a hackathon-ready **prototype** combining PayPal Sandbox checkout with an AI-assisted payment operations dashboard. It demonstrates an end-to-end payment flow, transaction persistence, a dashboard, CSV export, transparent review signals, and a payment assistant.

> **Important:** this is a demo, not a production payment platform or a validated fraud detection system. Use PayPal Sandbox accounts only. A risk flag is a review signal, not proof of fraud. Never add real card data, passwords, or API keys to the repository.

## Features

- PayPal Orders v2: create an order, open the PayPal Sandbox approval page, capture on return, and persist the resulting status.
- Finance dashboard: completed sales, completed and pending counts, recent transaction records, review flags, and CSV export.
- Smart assistant: optional Gemini API integration; local rule-based fallback works when no AI key is configured.
- Clear source labels and disclaimers so AI-generated insights are not presented as verified financial advice.
- FastAPI API docs, input validation, basic automated tests, and a clean public-repository starter setup.

## Requirements

- Python 3.11 or newer
- PayPal Developer Sandbox REST app credentials for checkout testing
- Optional: Google AI Studio API key for Gemini responses. Availability, quota, and terms can change; the project remains usable without this key.

## Run locally (Windows PowerShell)

1. Open this folder in VS Code.
2. Create and activate a virtual environment:

   ```powershell
   py -3.11 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Install dependencies:

   ```powershell
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. Copy `.env.example` to `.env` and fill in your own **Sandbox** app credentials:

   ```powershell
   Copy-Item .env.example .env
   ```

   Set `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET`. Keep `PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com`. For optional Gemini mode, add `GEMINI_API_KEY` from Google AI Studio. Do not share `.env` or commit it.

5. Start the server from the project root:

   ```powershell
   uvicorn main:app --reload
   ```

6. Visit `http://127.0.0.1:8000`. API documentation: `http://127.0.0.1:8000/docs`.

If PayPal credentials are not configured, the dashboard and local assistant still run, but creating a PayPal order will show a setup message.

## Test

```powershell
pytest -q
```

Tests use temporary transaction files and do not make real PayPal network calls.

## API routes

| Route | Purpose |
|---|---|
| `GET /api/health` | Service status and configured modes |
| `GET /api/transactions` | Local transaction records |
| `GET /dashboard/summary` | Dashboard aggregates |
| `GET /paypal/test` | Verify Sandbox OAuth credentials |
| `POST /paypal/create-order` | Create a PayPal order |
| `GET /paypal/return?token=...` | Capture the approved order and show result |
| `GET /paypal/cancel` | Checkout cancellation page |
| `POST /paypal/capture-order/{order_id}` | Explicit capture endpoint |
| `POST /api/assistant` | Ask a question about stored transaction records |

## How the AI works

When `GEMINI_API_KEY` is configured, the assistant sends a minimized set of transaction fields and the user's question to the configured Gemini model. Otherwise, it uses a local, deterministic rule-based assistant. If Gemini is unavailable or quota is exhausted, the local fallback is used. The fallback is not a machine-learning model. Do not describe the risk monitor as trained or validated fraud detection: this version reports explicit stored review flags and pending statuses.

## Data and privacy

- Transaction records are stored in `transactions.json` for this local demo.
- `.env` is ignored by Git; never commit credentials.
- The optional AI provider receives the selected transaction summary and question. Do not use personal or sensitive production payment data.
- This project is not PCI-compliant and should not be connected to live payments.

## GitHub publishing checklist

1. Review the code and replace any demo details you want to personalize.
2. Ensure `.env` is not staged and no secrets are in commit history.
3. Create a public repository and upload the project files, including this README and MIT license.
4. Run the app and tests on your own computer before recording a demo.
5. Record a short walkthrough showing the working app, Sandbox approval/capture, and assistant behavior. Explain which features are live integrations and which use a local fallback.
6. Read the current hackathon rules carefully; eligibility, AI requirements, disclosures, and submission format are determined by the organizer, not this README.

## Suggested demo flow

1. Open the dashboard and explain the summary values come from local transaction records.
2. Create a small Sandbox order and open the approval link.
3. Sign in with a PayPal **Sandbox buyer** account, approve, then return to the app.
4. Refresh and show the completed order in the transaction table.
5. Ask the assistant about completed sales or pending orders.
6. Export CSV and explain the limitations of rule-based risk flags.

## License

MIT. See `LICENSE`.
