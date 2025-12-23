import os
import json
import time
import signal
import sys
import traceback
import redis
from log_provider import get_log_provider

# ===============================
# Configuración básica
# ===============================

RHOST = os.getenv("REDIS_SERVICE_HOST", os.getenv("REDIS_HOST", "redis"))
RPORT = int(os.getenv("REDIS_SERVICE_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))

# Flags para controlar qué tan "pesado" es el contexto
LOGS_MODE = os.getenv("PHYLAXOR_LOGS_MODE", "none")
ENABLE_EVENTS = os.getenv("PHYLAXOR_EVENTS_ENABLED", "true").lower() == "true"
LOG_LINES = int(os.getenv("PHYLAXOR_LOGS_MAX_LINES", "500"))
EVENT_LIMIT = int(os.getenv("ENRICHER_EVENT_LIMIT", "20"))

# Log provider (will be initialized after K8s client is available)
LOG_PROVIDER = None

# Redis client
r = redis.Redis(host=RHOST, port=RPORT, db=REDIS_DB)


# ===============================
# Kubernetes client
# ===============================

K8S_AVAILABLE = False
core = apps = version_api = storage_api = None
CLUSTER_CTX = {}

try:
    from kubernetes import client, config

    config.load_incluster_config()
    core = client.CoreV1Api()
    apps = client.AppsV1Api()
    version_api = client.VersionApi()
    storage_api = client.StorageV1Api()
    K8S_AVAILABLE = True
except Exception as e:
    print(f"[enricher] Kubernetes client not available: {e}", file=sys.stderr, flush=True)
    traceback.print_exc()

# Initialize log provider (after K8s client setup)
try:
    LOG_PROVIDER = get_log_provider(LOGS_MODE, core_api=core if K8S_AVAILABLE else None)
    print(f"[enricher] Log provider initialized: mode={LOGS_MODE}", flush=True)
except Exception as e:
    print(f"[enricher] Error initializing log provider: {e}", file=sys.stderr, flush=True)
    traceback.print_exc()
    # Fallback to None provider
    from log_provider import NoneLogProvider
    LOG_PROVIDER = NoneLogProvider()
    print(f"[enricher] Fallback to NoneLogProvider", flush=True)


# ===============================
# Helpers de contexto de cluster
# ===============================

def build_cluster_context():
    """
    Captura un snapshot ligero del cluster: versión, nº nodos, SC por defecto, nodos Ready/NotReady.
    Se calcula una vez al inicio y se reutiliza.
    """
    if not K8S_AVAILABLE:
        return {"platform": "k8s", "context": "unknown", "error": "k8s client not available"}

    ctx = {"platform": "k8s"}

    try:
        v = version_api.get_code()
        ctx["version"] = v.git_version
    except Exception as e:
        ctx["version_error"] = str(e)

    try:
        sc_list = storage_api.list_storage_class().items
        default_sc = next(
            (s.metadata.name for s in sc_list
             if (s.metadata.annotations or {}).get("storageclass.kubernetes.io/is-default-class") == "true"),
            None
        )
        ctx["defaultStorageClass"] = default_sc
    except Exception as e:
        ctx["storage_error"] = str(e)

    try:
        nodes = core.list_node().items
        ctx["nodes"] = len(nodes)
        ready = 0
        not_ready = 0
        for n in nodes:
            conds = n.status.conditions or []
            st = next((c.status for c in conds if c.type == "Ready"), "Unknown")
            if st == "True":
                ready += 1
            else:
                not_ready += 1
        ctx["nodeSummary"] = {"ready": ready, "notReady": not_ready}
    except Exception as e:
        ctx["nodes_error"] = str(e)

    return ctx


CLUSTER_CTX = build_cluster_context()


# ===============================
# Helpers de contexto por alerta
# ===============================

def safe_call(fn, default=None, label=""):
    try:
        return fn()
    except Exception as e:
        print(f"[enricher] error in {label}: {e}", file=sys.stderr, flush=True)
        traceback.print_exc()
        return default


def get_namespace_info(ns: str):
    if not K8S_AVAILABLE or not ns:
        return None
    def _inner():
        obj = core.read_namespace(ns)
        return {
            "name": obj.metadata.name,
            "labels": obj.metadata.labels or {},
            "status": getattr(obj.status, "phase", None)
        }
    return safe_call(_inner, default=None, label=f"get_namespace_info({ns})")


def get_pod_info(ns: str, pod: str):
    if not K8S_AVAILABLE or not ns or not pod:
        return None

    def _inner():
        p = core.read_namespaced_pod(pod, ns)
        cs = p.status.container_statuses or []
        ready = sum(1 for c in cs if c.ready)
        restarts = sum(c.restart_count for c in cs)
        return {
            "name": p.metadata.name,
            "namespace": p.metadata.namespace,
            "nodeName": p.spec.node_name,
            "phase": p.status.phase,
            "podIP": p.status.pod_ip,
            "containerStatuses": [
                {
                    "name": c.name,
                    "ready": c.ready,
                    "restartCount": c.restart_count,
                    "state": {
                        "waiting": getattr(c.state.waiting, "reason", None) if c.state.waiting else None,
                        "terminated": getattr(c.state.terminated, "reason", None) if c.state.terminated else None
                    }
                } for c in cs
            ],
            "readyContainers": ready,
            "restarts": restarts,
        }

    return safe_call(_inner, default=None, label=f"get_pod_info({ns}/{pod})")


def get_recent_events(ns: str, pod: str):
    if not K8S_AVAILABLE or not ns or not pod or not ENABLE_EVENTS:
        return []

    def _inner():
        ev = core.list_namespaced_event(
            namespace=ns,
            field_selector=f"involvedObject.kind=Pod,involvedObject.name={pod}"
        )
        items = ev.items[-EVENT_LIMIT:]
        return [
            {
                "type": e.type,
                "reason": e.reason,
                "message": e.message,
                "firstTimestamp": str(e.first_timestamp or ""),
                "lastTimestamp": str(e.last_timestamp or "")
            }
            for e in items
        ]

    return safe_call(_inner, default=[], label=f"get_recent_events({ns}/{pod})")


def get_pod_logs(ns: str, pod: str):
    if not K8S_AVAILABLE or not ns or not pod or LOG_PROVIDER is None:
        return None
    return LOG_PROVIDER.get_logs(ns, pod)


def detect_workload(ns: str, pod_obj):
    if not K8S_AVAILABLE or not ns or not pod_obj:
        return None

    # Prefer K8s client objects, fallback to dict payloads.
    if hasattr(pod_obj, "metadata"):
        owner_refs = pod_obj.metadata.owner_references or []
    elif isinstance(pod_obj, dict):
        owner_refs = (pod_obj.get("ownerReferences")
                      or pod_obj.get("metadata", {}).get("ownerReferences")
                      or [])
    else:
        owner_refs = []

    def to_dict_owner(o):
        return {
            "kind": o.kind,
            "name": o.name
        }

    if owner_refs:
        o = owner_refs[0]
        # owner es un objeto de k8s
        if hasattr(o, "kind"):
            return {"kind": o.kind, "name": o.name}
        # owner es ya dict-ish
        return {"kind": o.get("kind"), "name": o.get("name")}

    return None


def get_node_info(node_name: str):
    if not K8S_AVAILABLE or not node_name:
        return None

    def _inner():
        n = core.read_node(node_name)
        conds = n.status.conditions or []
        return {
            "name": n.metadata.name,
            "labels": n.metadata.labels or {},
            "conditions": [
                {
                    "type": c.type,
                    "status": c.status,
                    "reason": c.reason,
                    "message": c.message
                } for c in conds
            ],
            "capacity": dict(n.status.capacity or {}),
            "allocatable": dict(n.status.allocatable or {})
        }

    return safe_call(_inner, default=None, label=f"get_node_info({node_name})")


def get_pod_storage(ns: str, pod: str):
    if not K8S_AVAILABLE or not ns or not pod:
        return None

    def _inner():
        p = core.read_namespaced_pod(pod, ns)
        vols = p.spec.volumes or []
        pvcs = []
        vol_summary = []
        for v in vols:
            vdict = {"name": v.name}
            if v.persistent_volume_claim:
                pvc_name = v.persistent_volume_claim.claim_name
                vdict["pvc"] = pvc_name
                pvcs.append(pvc_name)
            vol_summary.append(vdict)
        return {
            "pvcs": pvcs,
            "volumes": vol_summary
        }

    return safe_call(_inner, default=None, label=f"get_pod_storage({ns}/{pod})")


def build_alert_context(evt: dict):
    """
    Construye el sub-contexto específico de la alerta.
    """
    labels = evt.get("labels", {}) or {}
    ns = labels.get("namespace") or labels.get("kubernetes_namespace")
    pod = labels.get("pod") or labels.get("pod_name")

    ctx = {
        "namespace": ns,
        "pod": pod,
        "workload": None,
        "podStatus": None,
        "node": None,
        "events": [],
        "logs": None,
        "storage": None
    }

    # si no hay namespace/pod, poco podemos hacer
    if not ns or not pod:
        return ctx

    # Pod info
    pod_info = get_pod_info(ns, pod)
    ctx["podStatus"] = pod_info

    # Workload
    if pod_info:
        # aquí podríamos pasar el objeto real, pero dado que usamos dict, intentamos extraer ownerRefs desde la API cruda
        p_raw = safe_call(lambda: core.read_namespaced_pod(pod, ns), default=None, label="read_namespaced_pod_for_owner")
        ctx["workload"] = detect_workload(ns, p_raw)

    # Node info
    node_name = pod_info.get("nodeName") if pod_info else None
    if node_name:
        ctx["node"] = get_node_info(node_name)

    # Storage info
    ctx["storage"] = get_pod_storage(ns, pod)

    # Events
    ctx["events"] = get_recent_events(ns, pod)

    # Logs
    ctx["logs"] = get_pod_logs(ns, pod)

    return ctx


# ===============================
# Loop principal
# ===============================

_running = True

def _stop(*_):
    global _running
    _running = False

signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)


def main():
    print("[enricher] Starting enricher v2 with rich context...", flush=True)
    while _running:
        item = r.brpop("phylaxor_raw", timeout=5)
        if not item:
            continue

        _, payload = item
        try:
            evt = json.loads(payload)

            # context enriquecido
            context = {
                "cluster": CLUSTER_CTX,
                "alert": build_alert_context(evt)
            }
            evt["context"] = context

            r.lpush("phylaxor_enriched", json.dumps(evt))
        except Exception as e:
            print(f"[enricher] error procesando evento: {e}", file=sys.stderr, flush=True)
            traceback.print_exc()

    print("[enricher] Stopping enricher loop", flush=True)


if __name__ == "__main__":
    main()
