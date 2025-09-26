from fastapi import FastAPI, Request
import os, json, redis, time

app = FastAPI()
r = redis.Redis(host=os.getenv("REDIS_HOST","redis"), port=6379, db=0)

@app.post("/alert")
async def alert(req: Request):
    payload = await req.json()
    evt = {
        "fingerprint": payload.get("fingerprint") or str(int(time.time()*1000)),
        "alertname": payload.get("commonLabels", {}).get("alertname"),
        "labels": payload.get("commonLabels", {}),
        "annotations": payload.get("commonAnnotations", {}),
        "startsAt": payload.get("alerts", [{}])[0].get("startsAt"),
        "status": payload.get("status", "firing")
    }
    r.lpush("phylaxor_raw", json.dumps(evt))
    return {"ok": True}
