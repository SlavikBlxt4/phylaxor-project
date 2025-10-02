import os, json, time, signal, sys
import redis

CTX = {}
try:
    from kubernetes import client, config
    config.load_incluster_config()
    v = client.VersionApi().get_code()
    sc = client.StorageV1Api().list_storage_class()
    nodes = client.CoreV1Api().list_node()

    default_sc = next((s.metadata.name for s in sc.items
                       if (s.metadata.annotations or {}).get("storageclass.kubernetes.io/is-default-class") == "true"), None)
    CTX = {
        "platform": "k8s",
        "version": v.git_version,
        "nodes": len(nodes.items),
        "defaultStorageClass": default_sc
    }
except Exception as e:
    CTX = {"platform": "k8s", "context": "unknown", "error": str(e)}

RHOST = os.getenv("REDIS_SERVICE_HOST", os.getenv("REDIS_HOST", "redis"))
RPORT = int(os.getenv("REDIS_SERVICE_PORT", "6379"))
r = redis.Redis(host=RHOST, port=RPORT, db=0)

_running = True
def _stop(*_):
    global _running
    _running = False
signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)

def main():
    while _running:
        item = r.brpop("phylaxor_raw", timeout=5)
        if not item:
            continue
        _, payload = item
        try:
            evt = json.loads(payload)
            evt["context"] = CTX
            r.lpush("phylaxor_enriched", json.dumps(evt))
        except Exception as e:
            # Log sencillo a stdout
            print(f"[enricher] error procesando evento: {e}", file=sys.stderr, flush=True)

if __name__ == "__main__":
    main()
