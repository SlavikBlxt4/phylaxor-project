from fastapi import FastAPI, Request
import os, json, redis, time

app = FastAPI()
r = redis.Redis(host=os.getenv("REDIS_HOST","redis"), port=6379, db=0)

@app.post("/alert")
async def alert(req: Request):
    payload = await req.json()

    for a in payload.get("alerts", []):
        evt = {
            "fingerprint": a.get("fingerprint") or str(int(time.time()*1000)),
            "alertname": a.get("labels", {}).get("alertname"),
            "labels": a.get("labels", {}),
            "annotations": a.get("annotations", {}),
            "startsAt": a.get("startsAt"),
            "status": a.get("status", "firing")
        }
        r.lpush("phylaxor_raw", json.dumps(evt))

    return {"ok": True, "count": len(payload.get("alerts", []))}

