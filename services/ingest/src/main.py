from fastapi import FastAPI, Request
import os, json, redis, time, logging, re
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

RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def validated_run_id(labels):
    """Return a safe E2E correlation id without reflecting invalid input to logs."""
    run_id = (labels or {}).get("phylaxor_run_id")
    if run_id is None:
        return "none"
    return run_id if isinstance(run_id, str) and RUN_ID_RE.fullmatch(run_id) else "invalid"

@app.post("/alert")
async def alert(req: Request):
    payload = await req.json()
    alerts = payload.get("alerts", [])
    logger.info(f"[ingest] received alerts count={len(alerts)}")

    for a in alerts:
        labels = dict(a.get("labels", {}) or {})
        run_id = validated_run_id(labels)
        if run_id == "invalid":
            labels.pop("phylaxor_run_id", None)
        logger.info(
            f"[ingest] received alert alertname={labels.get('alertname')} "
            f"run_id={run_id}"
        )
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
            "alertname": labels.get("alertname"),
            "labels": labels,
            "annotations": a.get("annotations", {}),
            "startsAt": a.get("startsAt"),
            "status": a.get("status", "firing")
        }
        r.lpush("phylaxor_raw", json.dumps(evt))
        logger.info(
            f"[ingest] queued alert alertname={evt.get('alertname')} "
            f"fingerprint={evt.get('fingerprint')} status={evt.get('status')} "
            f"run_id={run_id}"
        )

    print(f"[ingest] queued alerts count={len(alerts)} to phylaxor_raw", flush=True)
    return {"ok": True, "count": len(alerts)}
