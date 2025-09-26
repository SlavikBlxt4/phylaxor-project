from fastapi import FastAPI, Request
import os
from telegram import Bot

app = FastAPI()
BOT = Bot(token=os.getenv("TELEGRAM_TOKEN",""))
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID","")  # puede ser int o str

@app.post("/send")
async def send(req: Request):
    data = await req.json()
    text = data.get("text","<no text>")
    if not (BOT.token and CHAT_ID):
        # modo "seco": no hay token/chat -> no petes, imprime por logs
        print(f"[DRY] Would send: {text}")
        return {"ok": True, "dry": True}
    await BOT.send_message(chat_id=CHAT_ID, text=text)
    return {"ok": True}

