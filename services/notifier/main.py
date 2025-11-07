from fastapi import FastAPI, Request
import os, json, requests
from telegram import Bot

app = FastAPI()

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
FEEDBACK_URL = os.getenv("FEEDBACK_URL", "http://feedback:8083/feedback")

BOT = Bot(token=BOT_TOKEN) if BOT_TOKEN else None


@app.post("/send")
async def send(req: Request):
    data = await req.json()
    text = data.get("text", "<no text>")
    decision_id = data.get("decision_id")

    if not BOT or not CHAT_ID:
        print(f"[DRY] Would send: {text}")
        return {"ok": True, "dry": True}

    # ✅ Si hay decision_id → añadimos botones
    if decision_id:
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "👍 Correcto", "callback_data": f"fb:{decision_id}:1"},
                    {"text": "👎 Incorrecto", "callback_data": f"fb:{decision_id}:0"}
                ]
            ]
        }

        await BOT.send_message(
            chat_id=CHAT_ID,
            text=text,
            reply_markup=json.dumps(keyboard)
        )
    else:
        await BOT.send_message(chat_id=CHAT_ID, text=text)

    return {"ok": True}


# ✅ Telegram webhook
@app.post("/webhook")
async def telegram_webhook(request: Request):
    body = await request.json()

    # if callback_query (user pressed a button)
    if "callback_query" in body:
        cq = body["callback_query"]
        data = cq.get("data", "")
        callback_id = cq.get("id")

        # Expected format: fb:<decision_id>:<vote>
        # Example "fb:12:1"
        if data.startswith("fb:"):
            _, decision_id, vote = data.split(":")
            vote_bool = vote == "1"

            # ✅ forward feedback to feedback-service
            try:
                r = requests.post(FEEDBACK_URL, json={
                    "decision_id": int(decision_id),
                    "vote": vote_bool
                })
                print("[NOTIFIER] Stored feedback:", r.text)
            except Exception as e:
                print("[NOTIFIER] Feedback error:", e)

            # ✅ Answer callback to prevent Telegram spinner
            if BOT:
                try:
                    await BOT.answer_callback_query(
                        callback_query_id=callback_id,
                        text="✅ ¡Gracias por tu feedback!"
                    )
                except:
                    pass

    return {"ok": True}
