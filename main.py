from __future__ import annotations
import json, os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()
BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "transactions.json"
PAYPAL_BASE_URL = os.getenv("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com").rstrip("/")
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

app = FastAPI(title="PayPilot AI", version="2.0.0", description="AI-assisted payment insights using PayPal Sandbox.")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

class CreateOrderRequest(BaseModel):
    amount: float = Field(gt=0, le=100000, description="Payment amount in USD")
    description: str = Field(default="PayPilot demo payment", min_length=1, max_length=120)

class AssistantRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


def read_transactions() -> list[dict[str, Any]]:
    if not DATA_FILE.exists():
        return []
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def write_transactions(items: list[dict[str, Any]]) -> None:
    temp = DATA_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(items, indent=2), encoding="utf-8")
    temp.replace(DATA_FILE)


def upsert_transaction(item: dict[str, Any]) -> None:
    rows = read_transactions()
    for idx, row in enumerate(rows):
        if row.get("order_id") == item.get("order_id"):
            rows[idx] = {**row, **item}
            write_transactions(rows)
            return
    rows.insert(0, item)
    write_transactions(rows)


def paypal_configured() -> bool:
    return bool(os.getenv("PAYPAL_CLIENT_ID") and os.getenv("PAYPAL_CLIENT_SECRET"))

async def paypal_access_token() -> str:
    client_id = os.getenv("PAYPAL_CLIENT_ID", "")
    secret = os.getenv("PAYPAL_CLIENT_SECRET", "")
    if not client_id or not secret:
        raise HTTPException(status_code=503, detail="PayPal Sandbox is not configured. Add credentials to your local .env file.")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(f"{PAYPAL_BASE_URL}/v1/oauth2/token", auth=(client_id, secret), data={"grant_type": "client_credentials"}, headers={"Accept": "application/json", "Accept-Language": "en_US"})
    if response.is_error:
        raise HTTPException(status_code=502, detail=f"PayPal authentication failed ({response.status_code}). Check Sandbox credentials.")
    return response.json()["access_token"]

async def paypal_request(method: str, path: str, payload: dict | None = None) -> dict:
    token = await paypal_access_token()
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.request(method, f"{PAYPAL_BASE_URL}{path}", json=payload, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Prefer": "return=representation"})
    if response.is_error:
        try: message = response.json().get("message", "PayPal request failed")
        except Exception: message = "PayPal request failed"
        raise HTTPException(status_code=502, detail=f"PayPal API error ({response.status_code}): {message}")
    return response.json() if response.content else {}


def normalize_order(order: dict) -> dict:
    pu = (order.get("purchase_units") or [{}])[0]
    amount = pu.get("amount", {})
    return {"order_id": order.get("id"), "amount": float(amount.get("value", 0) or 0), "currency": amount.get("currency_code", "USD"), "status": order.get("status", "UNKNOWN"), "risk_flag": False, "description": pu.get("description", "PayPal Sandbox payment"), "updated_at": datetime.now(timezone.utc).isoformat(), "source": "paypal_sandbox"}

@app.get("/", include_in_schema=False)
async def home():
    return FileResponse(BASE_DIR / "static" / "index.html")

@app.get("/api/health")
async def health():
    return {"status": "ok", "app": "PayPilot AI", "paypal_configured": paypal_configured(), "ai_mode": "gemini" if os.getenv("GEMINI_API_KEY") else "local_fallback"}

@app.get("/api/transactions")
async def transactions():
    return {"items": read_transactions()}

@app.get("/dashboard/summary")
async def dashboard_summary():
    items = read_transactions()
    completed = [x for x in items if x.get("status") == "COMPLETED"]
    pending = [x for x in items if x.get("status") in {"CREATED", "PAYER_ACTION_REQUIRED", "APPROVED", "PENDING"}]
    risk = [x for x in items if x.get("risk_flag")]
    currency = next((x.get("currency", "USD") for x in items), "USD")
    sales = round(sum(float(x.get("amount", 0) or 0) for x in completed), 2)
    return {"currency": currency, "total_sales": sales, "completed_count": len(completed), "pending_count": len(pending), "risk_count": len(risk), "transaction_count": len(items), "transactions": items[:12], "source": "local_transaction_store", "paypal_configured": paypal_configured(), "ai_mode": "gemini" if os.getenv("GEMINI_API_KEY") else "local_fallback"}

@app.get("/paypal/test")
async def paypal_test():
    token = await paypal_access_token()
    return {"status": "connected", "message": "PayPal Sandbox authentication successful", "token_received": bool(token)}

@app.post("/paypal/create-order")
async def create_order(body: CreateOrderRequest):
    payload = {"intent": "CAPTURE", "purchase_units": [{"amount": {"currency_code": "USD", "value": f"{body.amount:.2f}"}, "description": body.description}], "payment_source": {"paypal": {"experience_context": {"brand_name": "PayPilot AI", "shipping_preference": "NO_SHIPPING", "user_action": "PAY_NOW", "return_url": f"{APP_BASE_URL}/paypal/return", "cancel_url": f"{APP_BASE_URL}/paypal/cancel"}}}}
    order = await paypal_request("POST", "/v2/checkout/orders", payload)
    record = normalize_order(order)
    upsert_transaction(record)
    approval = next((x.get("href") for x in order.get("links", []) if x.get("rel") == "payer-action"), None)
    if not approval:
        approval = next((x.get("href") for x in order.get("links", []) if x.get("rel") == "approve"), None)
    return {"order_id": order.get("id"), "status": order.get("status"), "approval_url": approval, "transaction": record}

@app.post("/paypal/capture-order/{order_id}")
async def capture_order(order_id: str):
    if not order_id or len(order_id) > 80:
        raise HTTPException(status_code=400, detail="Invalid order ID")
    order = await paypal_request("POST", f"/v2/checkout/orders/{order_id}/capture", {})
    record = normalize_order(order)
    # Capture response may include capture-level status; only persist completed when PayPal confirms it.
    if order.get("status") == "COMPLETED":
        record["status"] = "COMPLETED"
    upsert_transaction(record)
    return {"order": order, "transaction": record}

@app.get("/paypal/return", response_class=HTMLResponse)
async def paypal_return(token: str | None = None):
    if not token:
        return HTMLResponse(_result_page(False, "No PayPal order token was returned."), status_code=400)
    try:
        result = await paypal_request("POST", f"/v2/checkout/orders/{token}/capture", {})
        record = normalize_order(result)
        upsert_transaction(record)
        success = result.get("status") == "COMPLETED"
        title = "Payment completed" if success else "Payment not completed yet"
        message = "PayPal Sandbox confirmed this capture. Your dashboard has been updated." if success else f"PayPal returned status: {result.get('status', 'UNKNOWN')}"
        return HTMLResponse(_result_page(success, message, title))
    except HTTPException as exc:
        return HTMLResponse(_result_page(False, str(exc.detail), "Payment needs attention"), status_code=exc.status_code)

@app.get("/paypal/cancel", response_class=HTMLResponse)
async def paypal_cancel():
    return HTMLResponse(_result_page(False, "Checkout was cancelled. No successful capture was recorded.", "Checkout cancelled"))

def _result_page(success: bool, message: str, title: str = "PayPilot AI") -> str:
    color = "#34d399" if success else "#fbbf24"
    return f"""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} · PayPilot AI</title><style>body{{margin:0;background:#07111f;color:#edf4ff;font:16px system-ui;display:grid;place-items:center;min-height:100vh}}main{{max-width:520px;margin:20px;padding:34px;border:1px solid #24344d;border-radius:24px;background:#0d1b2d}}h1{{color:{color}}}a{{color:#93c5fd}}p{{line-height:1.7;color:#b8c7db}}</style></head><body><main><p>PAYPILOT AI · PAYPAL SANDBOX</p><h1>{title}</h1><p>{message}</p><p><a href="/">Return to dashboard →</a></p></main></body></html>"""


def local_answer(question: str) -> dict:
    items = read_transactions()
    completed = [x for x in items if x.get("status") == "COMPLETED"]
    pending = [x for x in items if x.get("status") in {"CREATED", "PAYER_ACTION_REQUIRED", "APPROVED", "PENDING"}]
    flagged = [x for x in items if x.get("risk_flag")]
    sales = sum(float(x.get("amount", 0) or 0) for x in completed)
    q = question.lower()
    if any(w in q for w in ["risk", "fraud", "suspicious", "attention"]):
        answer = f"Risk review: {len(flagged)} transaction(s) are flagged by the current rule-based checks. {len(pending)} payment(s) are still pending. This demo does not prove fraud; review flagged records manually."
    elif any(w in q for w in ["sales", "revenue", "total", "money", "amount"]):
        answer = f"Recorded completed sales total ${sales:,.2f} across {len(completed)} completed payment(s). There are {len(pending)} pending payment(s). Currency totals are shown from the stored transaction records."
    elif any(w in q for w in ["pending", "unfinished", "waiting"]):
        answer = f"There are {len(pending)} pending payment(s)." + (" Order IDs: " + ", ".join(str(x.get("order_id")) for x in pending[:5]) if pending else " No pending orders are currently stored.")
    elif any(w in q for w in ["completed", "successful", "paid"]):
        answer = f"Completed payments: {len(completed)}. Pending payments: {len(pending)}. Completed sales: ${sales:,.2f}."
    elif any(w in q for w in ["how many", "count", "transactions"]):
        answer = f"There are {len(items)} stored transaction(s): {len(completed)} completed, {len(pending)} pending, and {len(flagged)} flagged by the current rules."
    else:
        answer = f"Here is your payment snapshot: {len(items)} transaction(s), {len(completed)} completed, {len(pending)} pending, ${sales:,.2f} completed sales, and {len(flagged)} risk flag(s). Try asking about sales, completed payments, pending orders, or risk."
    return {"answer": answer, "mode": "local_fallback", "disclaimer": "Rule-based summary of local records; not financial, legal, or definitive fraud advice."}




@app.post("/api/assistant")
async def assistant(body: AssistantRequest):
    from decimal import Decimal, InvalidOperation

    key = os.getenv("GROQ_API_KEY", "").strip()
    model = os.getenv(
        "GROQ_MODEL", "openai/gpt-oss-20b"
    ).strip()

    # ---------- Local fallback if API key is missing ----------
    if not key:
        result = local_answer(body.question)
        result["mode"] = "local_fallback"
        result["disclaimer"] += (
            " Groq API key is not configured."
        )
        return result

    try:
        items = read_transactions()

        # ---------- Safely interpret risk flags ----------
        def is_flagged(value):
            if isinstance(value, bool):
                return value

            if isinstance(value, (int, float)):
                return value != 0

            if isinstance(value, str):
                return value.strip().lower() in (
                    "true", "1", "yes", "flagged"
                )

            return False

        # ---------- Calculate accurate statistics ----------
        completed_count = 0
        pending_count = 0
        failed_count = 0
        refunded_count = 0
        risk_count = 0

        currency_totals = {}
        status_counts = {}

        for item in items:
            status = str(
                item.get("status", "UNKNOWN")
            ).upper().strip()

            currency = str(
                item.get("currency", "USD")
            ).upper().strip()

            status_counts[status] = (
                status_counts.get(status, 0) + 1
            )

            if status == "COMPLETED":
                completed_count += 1

                try:
                    amount = Decimal(
                        str(item.get("amount", 0))
                    )

                    if not amount.is_finite():
                        amount = Decimal("0")

                except (InvalidOperation, ValueError):
                    amount = Decimal("0")

                currency_totals[currency] = (
                    currency_totals.get(
                        currency, Decimal("0")
                    ) + amount
                )

            elif status in (
                "CREATED",
                "APPROVED",
                "PENDING",
                "PAYER_ACTION_REQUIRED",
            ):
                pending_count += 1

            elif status in ("FAILED", "DENIED"):
                failed_count += 1

            elif status in ("REFUNDED", "PARTIALLY_REFUNDED"):
                refunded_count += 1

            if is_flagged(item.get("risk_flag", False)):
                risk_count += 1

        # ---------- Prepare authoritative summary ----------
        totals = {
            currency: str(amount.quantize(Decimal("0.01")))
            for currency, amount in currency_totals.items()
        }

        summary = {
            "total_transactions": len(items),
            "completed_transactions": completed_count,
            "pending_transactions": pending_count,
            "failed_transactions": failed_count,
            "refunded_transactions": refunded_count,
            "risk_flagged_transactions": risk_count,
            "completed_sales_by_currency": totals,
            "status_counts": status_counts,
        }

        # Include a maximum of 40 records as supporting context.
        safe_context = [
            {
                k: item.get(k)
                for k in (
                    "order_id",
                    "amount",
                    "currency",
                    "status",
                    "risk_flag",
                    "updated_at",
                )
            }
            for item in items[:40]
        ]

        # ---------- Strict AI instructions ----------
        system_prompt = """
You are PayPilot AI, an intelligent payment operations copilot.

Your task is to explain payment data and provide useful,
careful business insights.

STRICT DATA RULES:

1. Use only the supplied transaction records and
   calculated summary.

2. The calculated summary is authoritative for totals
   and transaction counts. Do not recalculate or
   contradict it.

3. Never invent transactions, customers, amounts,
   currencies, payment events, or business facts.

4. A risk_flag value of false means only that no risk
   flag is stored for that transaction.

5. NEVER claim that a payment passed fraud checks,
   was verified as safe, or is fraud-free based only
   on risk_flag=false.

6. A risk flag is a review signal, not proof of fraud.

7. Do not claim that the risk rules are effective
   merely because no records were flagged.

8. Keep currencies separate. Never combine USD, INR,
   or other currencies into one total.

9. If there are very few transactions, explicitly
   explain that the sample is too small for reliable
   business or fraud conclusions.

10. Do not claim to process, approve, refund, or
    transfer money. You only analyze records.

RESPONSE FORMAT:

Use clear Markdown headings.

Include:
- Transaction summary
- Payment status explanation
- Risk indicators and limitations
- Exactly three practical business recommendations
- A short limitations note

Recommendations must be realistic and supported by
the available data.

Do not recommend expanding into other currencies
unless the user's business context supports it.

Use professional, concise language.
"""

        user_prompt = (
            "AUTHORITATIVE CALCULATED SUMMARY:\n"
            + json.dumps(summary, indent=2)
            + "\n\nTRANSACTION RECORDS (maximum 40):\n"
            + json.dumps(safe_context, indent=2)
            + "\n\nUSER QUESTION:\n"
            + body.question
        )

        # ---------- Call Groq AI ----------
        print("Groq request starting. Model:", model)

        async with httpx.AsyncClient(timeout=40) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": system_prompt,
                        },
                        {
                            "role": "user",
                            "content": user_prompt,
                        },
                    ],
                    "temperature": 0.2,
                    "max_completion_tokens": 1200,
                },
            )

        print("Groq HTTP status:", response.status_code)
        response.raise_for_status()

        data = response.json()

        answer = (
            data["choices"][0]["message"].get("content") or ""
        ).strip()

        if not answer:
            raise ValueError(
                "Groq returned empty message content"
            )

        print("Groq AI response received successfully")

        return {
            "answer": answer,
            "mode": "groq",
            "summary": summary,
            "disclaimer": (
                "AI-generated operational insights based on "
                "stored transaction records. No stored risk flag "
                "does not establish that a payment is safe. "
                "Risk indicators are not proof of fraud. "
                "Verify important financial decisions."
            ),
        }

    except httpx.HTTPStatusError as exc:
        print(
            "Groq HTTP error:",
            exc.response.status_code,
            exc.response.text[:1000],
        )

    except Exception as exc:
        print(
            "Groq integration error:",
            type(exc).__name__,
            str(exc),
        )

    # ---------- Fallback ----------
    result = local_answer(body.question)
    result["mode"] = "local_fallback"
    result["disclaimer"] += (
        " Groq was unavailable, so local fallback was used."
    )

    return result
