from fastapi import FastAPI, Request
import os, json, redis, time

app = FastAPI()
r = redis.Redis(host=os.getenv("REDIS_HOST","redis"), port=6379, db=0)

@app.post("/alert")
async def alert(req: Request):
    payload = await req.json()
    alerts = payload.get("alerts", [])
    print(f"[ingest] received alerts count={len(alerts)}", flush=True)

    for a in alerts:
        evt = {
            "fingerprint": a.get("fingerprint") or str(int(time.time()*1000)),
            "alertname": a.get("labels", {}).get("alertname"),
            "labels": a.get("labels", {}),
            "annotations": a.get("annotations", {}),
            "startsAt": a.get("startsAt"),
            "status": a.get("status", "firing")
        }
        r.lpush("phylaxor_raw", json.dumps(evt))
        print(
            f"[ingest] queued alert alertname={evt.get('alertname')} "
            f"fingerprint={evt.get('fingerprint')} status={evt.get('status')}",
            flush=True
        )

    print(f"[ingest] queued alerts count={len(alerts)} to phylaxor_raw", flush=True)
    return {"ok": True, "count": len(alerts)}
