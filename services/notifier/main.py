from fastapi import FastAPI, Request
import os, requests
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton

app = FastAPI()

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
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
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("👍 Correcto", callback_data=f"fb:{decision_id}:1"),
                InlineKeyboardButton("👎 Incorrecto", callback_data=f"fb:{decision_id}:0")
            ]
        ])

        await BOT.send_message(
            chat_id=CHAT_ID,
            text=text,
            reply_markup=keyboard
        )
    else:
        await BOT.send_message(chat_id=CHAT_ID, text=text)

    return {"ok": True}
