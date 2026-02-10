import datetime
import json
import os

SERVICE_NAME = "decision"


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "y", "on")


def _format_value(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"), default=str)
    return str(value)


def log(event: str, **fields) -> None:
    log_format = os.getenv("PHYLAXOR_LOG_FORMAT", "text").lower()
    if env_bool("PHYLAXOR_DEBUG", False) and "debug" not in fields:
        fields["debug"] = True
    if log_format == "json":
        payload = {
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "service": SERVICE_NAME,
            "event": event,
        }
        payload.update(fields)
        print(
            json.dumps(payload, ensure_ascii=True, separators=(",", ":"), default=str),
            flush=True,
        )
        return

    parts = [f"[{SERVICE_NAME}] {event}"]
    for key, value in fields.items():
        parts.append(f"{key}={_format_value(value)}")
    print(" ".join(parts), flush=True)
