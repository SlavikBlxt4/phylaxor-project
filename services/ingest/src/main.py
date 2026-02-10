from fastapi import FastAPI, Request
import os, json, redis, time, logging
# Try specific import for different run contexts
try:
    from fingerprint import calculate_fingerprint
except ImportError:
    from .fingerprint import calculate_fingerprint

app = FastAPI()
r = redis.Redis(host=os.getenv("REDIS_HOST","redis"), port=6379, db=0)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ingest")

@app.post("/alert")
async def alert(req: Request):
    payload = await req.json()
    alerts = payload.get("alerts", [])
    logger.info(f"[ingest] received alerts count={len(alerts)}")

    for a in alerts:
        # Calculate deterministic fingerprint v1
        fp, explanation = calculate_fingerprint(a)
        
        # Log explanation compactly
        # Example: [ingest] computed fingerprint=v1:abc... scope=workload entity=ns/dep inputs={...}
        inputs_str = json.dumps(explanation['inputs'])
        logger.info(
            f"[ingest] computed fingerprint={fp} scope={explanation['scope']} "
            f"entity={explanation['entity_value']} inputs={inputs_str}"
        )

        evt = {
            "fingerprint": fp,
            "fingerprint_explanation": explanation,
            "alertname": a.get("labels", {}).get("alertname"),
            "labels": a.get("labels", {}),
            "annotations": a.get("annotations", {}),
            "startsAt": a.get("startsAt"),
            "status": a.get("status", "firing")
        }
        r.lpush("phylaxor_raw", json.dumps(evt))
        logger.info(
            f"[ingest] queued alert alertname={evt.get('alertname')} "
            f"fingerprint={evt.get('fingerprint')} status={evt.get('status')}"
        )

    print(f"[ingest] queued alerts count={len(alerts)} to phylaxor_raw", flush=True)
    return {"ok": True, "count": len(alerts)}
