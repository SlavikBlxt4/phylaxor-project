import os
import json
import time
import uuid
import datetime
import redis
import requests
import psycopg2
from psycopg2.extras import Json

REDIS_HOST   = os.getenv("REDIS_HOST","redis")
PG_DSN       = os.getenv("PG_DSN","dbname=phylaxor user=postgres password=postgres host=postgres.phylaxor-db.svc.cluster.local")
NOTIFIER_URL = os.getenv("NOTIFIER_URL","http://notifier:8082/send")

# Brain Gateway config
BRAIN_GATEWAY_URL = os.getenv("BRAIN_GATEWAY_URL", "http://brain-gateway:8000")
BRAIN_GATEWAY_TIMEOUT_SECONDS = float(os.getenv("BRAIN_GATEWAY_TIMEOUT_SECONDS", "20"))
BRAIN_GATEWAY_MAX_RETRIES = int(os.getenv("BRAIN_GATEWAY_MAX_RETRIES", "2"))
BRAIN_GATEWAY_RETRY_BACKOFF_MS = int(os.getenv("BRAIN_GATEWAY_RETRY_BACKOFF_MS", "250"))
BRAIN_GATEWAY_MAX_OUTPUT_TOKENS = int(os.getenv("BRAIN_GATEWAY_MAX_OUTPUT_TOKENS", "1024"))

# Limits passed to AIRequest
PHYLAXOR_LOGS_MAX_LINES = int(os.getenv("PHYLAXOR_LOGS_MAX_LINES", "500"))
PHYLAXOR_LOGS_MAX_BYTES = int(os.getenv("PHYLAXOR_LOGS_MAX_BYTES", "100000"))
PHYLAXOR_LOGS_LOOKBACK = int(os.getenv("PHYLAXOR_LOGS_LOOKBACK", "300"))
ENRICHER_EVENT_LIMIT = int(os.getenv("ENRICHER_EVENT_LIMIT", "20"))

r = redis.Redis(host=REDIS_HOST, port=6379, db=0)

def pg():
    return psycopg2.connect(PG_DSN)

# ---------- util ----------
def _render(value, ctx):
    # templating muy simple para checks/fixes
    if isinstance(value, str):
        out = value
        for k,v in ctx.items():
            out = out.replace("{{"+k+"}}", str(v))
        return out
    return value

def _jsonify(val):
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return {"summary": str(val), "checks": [], "hypotheses": [], "fixes": []}

def _context_from(evt):
    labels = evt.get("labels") or {}
    return {
        "alertname": evt.get("alertname",""),
        "namespace": labels.get("namespace","default"),
        "pod":       labels.get("pod",""),
        "node":      labels.get("node",""),
    }

def _utc_now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def _normalize_confidence(value):
    try:
        val = float(value)
    except Exception:
        return 0.0
    if val > 1.0:
        val = val / 100.0
    return max(0.0, min(1.0, val))

def _extract_context(evt):
    ctx = evt.get("context") or {}
    if "alertContext" in ctx:
        alert_ctx = ctx.get("alertContext") or {}
    else:
        alert_ctx = ctx.get("alert") or {}
    cluster_ctx = ctx.get("cluster") or {}
    return {
        "alertContext": alert_ctx or {},
        "cluster": cluster_ctx or {},
    }

def _build_decision_context(source, confidence, matched, hist_reason=None, kb=None):
    decision = {
        "source": source,
        "confidence": _normalize_confidence(confidence),
        "matched": bool(matched),
    }
    history = []
    if hist_reason:
        history.append({"type": "history_check", **hist_reason})
    if kb:
        history.append({
            "type": "kb_match",
            "kb_id": kb.get("kb_id"),
            "summary": kb.get("summary"),
        })
    if history:
        decision["history"] = history
    return decision

def _build_ai_request(evt, decision_ctx, request_id):
    labels = evt.get("labels") or {}
    annotations = evt.get("annotations") or {}

    alert = {
        "fingerprint": evt.get("fingerprint", ""),
        "alertname": evt.get("alertname", ""),
        "status": evt.get("status", ""),
    }
    if evt.get("startsAt"):
        alert["startsAt"] = evt.get("startsAt")
    severity = evt.get("severity") or labels.get("severity") or annotations.get("severity")
    if severity:
        alert["severity"] = severity
    if labels:
        alert["labels"] = labels
    if annotations:
        alert["annotations"] = annotations

    req = {
        "meta": {
            "requestId": request_id,
            "timestamp": _utc_now_iso(),
            "schemaVersion": "1.0",
        },
        "alert": alert,
        "context": _extract_context(evt),
        "constraints": {
            "readOnly": True,
            "noSecrets": True,
            "noDestructiveActions": True,
        },
        "limits": {
            "maxOutputTokens": BRAIN_GATEWAY_MAX_OUTPUT_TOKENS,
            "logs": {
                "maxChars": PHYLAXOR_LOGS_MAX_BYTES,
                "tailLines": PHYLAXOR_LOGS_MAX_LINES,
                "sinceSeconds": PHYLAXOR_LOGS_LOOKBACK,
                "dedupeRepeatedLines": True,
            },
            "events": {
                "maxItems": ENRICHER_EVENT_LIMIT,
            },
        },
        "outputFormat": {
            "type": "json",
            "schemaVersion": "1.0",
        },
    }
    if decision_ctx:
        req["decision"] = decision_ctx
    return req

def _ai_response_to_rec(ai_response):
    checks = []
    for check in ai_response.get("checks", []) or []:
        title = (check.get("title") or "").strip()
        commands = check.get("commands") or []
        reason = (check.get("reason") or "").strip()
        cmd_text = "; ".join([c for c in commands if c])
        entry = ""
        if title and cmd_text:
            entry = f"{title}: {cmd_text}"
        elif title:
            entry = title
        elif cmd_text:
            entry = cmd_text
        if reason:
            entry = f"{entry} (reason: {reason})" if entry else reason
        if entry:
            checks.append(entry)

    fixes = []
    for fix in ai_response.get("fixes", []) or []:
        if fix.get("requiresWrite") is True:
            continue  # respeta read-only
        title = (fix.get("title") or "").strip()
        steps = fix.get("steps") or []
        risk = (fix.get("risk") or "").strip()
        step_text = " / ".join([s for s in steps if s])
        entry = ""
        if title and step_text:
            entry = f"{title}: {step_text}"
        elif title:
            entry = title
        elif step_text:
            entry = step_text
        if risk:
            entry = f"{entry} (risk: {risk})" if entry else f"risk: {risk}"
        if entry:
            fixes.append(entry)

    rec = {
        "summary": ai_response.get("summary", ""),
        "checks": checks,
        "fixes": fixes,
        "hypotheses": ai_response.get("hypotheses", []),
        "recommendedActions": ai_response.get("recommendedActions", []),
        "missingInfo": ai_response.get("missingInfo", []),
        "aiResponse": {k: v for k, v in ai_response.items() if k != "suggestedToolCalls"},
    }
    return rec

def _fallback_rec(evt, prev_rec=None, kb=None, hist_reason=None, ai_error=None):
    labels = evt.get("labels") or {}
    ns = labels.get("namespace", "default")
    pod = labels.get("pod", "")

    summary_parts = []
    if isinstance(prev_rec, dict) and prev_rec.get("summary"):
        summary_parts.append(f"Historial: {prev_rec.get('summary')}")
    if isinstance(kb, dict) and kb.get("summary"):
        summary_parts.append(f"KB: {kb.get('summary')}")
    if not summary_parts:
        summary_parts.append("IA no disponible; respuesta degradada.")
    summary = " | ".join(summary_parts)

    checks = []
    if ns and pod:
        checks.extend([
            f"kubectl -n {ns} get pod {pod} -o wide",
            f"kubectl -n {ns} describe pod {pod}",
            f"kubectl -n {ns} logs {pod} --tail=50",
        ])
    else:
        checks.append("kubectl get pods -A")
    checks.append("kubectl get events -A | tail -n 50")

    fixes = [
        "Revisar eventos y logs; escalar si persiste",
        "Registrar un KB item si se confirma causa",
    ]

    missing = ["AI backend unavailable"]
    if ai_error:
        missing.append(f"AI error: {ai_error}")
    if hist_reason and hist_reason.get("gating_reason"):
        missing.append(f"History gating: {hist_reason.get('gating_reason')}")

    return {
        "summary": summary,
        "checks": checks,
        "hypotheses": [],
        "fixes": fixes,
        "recommendedActions": [],
        "missingInfo": missing,
    }

def _brain_gateway_endpoint():
    return BRAIN_GATEWAY_URL.rstrip("/") + "/v1/brain/complete"

def _call_brain_gateway(ai_request, request_id, fingerprint):
    url = _brain_gateway_endpoint()
    max_retries = max(0, BRAIN_GATEWAY_MAX_RETRIES)
    backoff_ms = max(0, BRAIN_GATEWAY_RETRY_BACKOFF_MS)
    last_error = None

    log("brain_request", request_id=request_id, fingerprint=fingerprint, url=url)

    for attempt in range(max_retries + 1):
        try:
            t0 = time.time()
            resp = requests.post(
                url,
                json=ai_request,
                timeout=BRAIN_GATEWAY_TIMEOUT_SECONDS,
            )
            latency_ms = int((time.time() - t0) * 1000)
        except requests.exceptions.Timeout:
            last_error = "timeout"
            log(
                "brain_timeout",
                request_id=request_id,
                fingerprint=fingerprint,
                attempt=attempt + 1,
            )
        except requests.exceptions.RequestException as e:
            last_error = f"request_error:{type(e).__name__}"
            log(
                "brain_request_error",
                request_id=request_id,
                fingerprint=fingerprint,
                attempt=attempt + 1,
                error=str(e),
            )
        else:
            if 200 <= resp.status_code < 300:
                try:
                    payload = resp.json()
                except Exception as e:
                    log(
                        "brain_invalid_response",
                        request_id=request_id,
                        fingerprint=fingerprint,
                        error=str(e),
                    )
                    return None, "invalid_response", latency_ms
                log(
                    "brain_response",
                    request_id=request_id,
                    fingerprint=fingerprint,
                    status_code=resp.status_code,
                    latency_ms=latency_ms,
                )
                return payload, None, latency_ms

            if 400 <= resp.status_code < 500:
                log(
                    "brain_request_invalid",
                    request_id=request_id,
                    fingerprint=fingerprint,
                    status_code=resp.status_code,
                )
                return None, f"http_{resp.status_code}", latency_ms

            last_error = f"http_{resp.status_code}"
            log(
                "brain_retryable_status",
                request_id=request_id,
                fingerprint=fingerprint,
                status_code=resp.status_code,
                attempt=attempt + 1,
            )

        if attempt < max_retries:
            time.sleep((backoff_ms / 1000.0) * (attempt + 1))
            continue

    log(
        "brain_gateway_unavailable",
        request_id=request_id,
        fingerprint=fingerprint,
        error=last_error,
    )
    return None, last_error, None

# Ensure strictly running as script works if cwd is weird
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import history_score
from constants import KB_BASE_CONFIDENCE, AI_BASE_CONFIDENCE
from logger import env_bool, log

DEBUG_HISTORY = env_bool("PHYLAXOR_DEBUG_HISTORY", False)

# ---------- histórico ----------
def previous_decision(evt):
    """
    Looks up history by fingerprint.
    Returns (recommendation_dict, reason_dict) if eligible.
    Returns (None, reason_dict) if ineligible or no history.
    """
    fp = evt.get("fingerprint")
    if not fp:
        return None, {"gating_reason": "no_fingerprint"}

    with pg() as conn, conn.cursor() as cur:
        # Fetch N=20 potential history items
        # Including kb_id and rule_id for stable grouping keys
        cur.execute("""
            SELECT d.path, d.confidence, d.created_at, d.recommendation, d.id, d.kb_id, d.rule_id
            FROM decisions d
            JOIN alerts a ON a.id = d.alert_id
            WHERE a.fingerprint = %s
            ORDER BY d.id DESC
            LIMIT %s;
        """, (fp, history_score.DEFAULT_CONFIG["LIMIT"]))
        
        db_rows = cur.fetchall()
        
    if not db_rows:
        return None, {"gating_reason": "no_history_found"}
        
    # Map DB tuples to dicts for scoring
    # Columns: 0:path, 1:confidence, 2:created_at, 3:recommendation, 4:id, 5:kb_id, 6:rule_id
    rows = []
    for r in db_rows:
        rows.append({
            "path": r[0],
            "confidence": r[1],
            "created_at": r[2],
            "recommendation": _jsonify(r[3]),
            "id": r[4],
            "kb_id": r[5],
            "rule_id": r[6]
        })
        
    eligible, best_rec, reason = history_score.calculate_score(rows, debug=DEBUG_HISTORY)
    
    if eligible:
        return best_rec, reason
    else:
        return None, reason


# ---------- match KB (todos los matchers deben cumplirse) ----------
def match_kb(evt):
    alertname = evt.get("alertname") or ""
    labels    = evt.get("labels") or {}
    namespace = labels.get("namespace","")
    labels_json = json.dumps(labels)

    sql = """
    WITH evt AS (
      SELECT %s::text AS alertname, %s::text AS namespace, %s::jsonb AS labels
    ),
    m AS (
      SELECT ki.id AS kb_id,
             COUNT(*) AS total,
             SUM((
                (km.kind='alertname' AND km.operator='eq'       AND (SELECT alertname  FROM evt)=km.value) OR
                (km.kind='alertname' AND km.operator='contains' AND (SELECT alertname  FROM evt) ILIKE (chr(37) || km.value || chr(37))) OR
                (km.kind='alertname' AND km.operator='regex'    AND (SELECT alertname  FROM evt) ~* km.value) OR
                (km.kind='namespace' AND km.operator='eq'       AND (SELECT namespace  FROM evt)=km.value) OR
                (km.kind='namespace' AND km.operator='contains' AND (SELECT namespace  FROM evt) ILIKE (chr(37) || km.value || chr(37))) OR
                (km.kind='namespace' AND km.operator='regex'    AND (SELECT namespace  FROM evt) ~* km.value) OR
                (km.kind='label'     AND km.operator='eq'       AND (SELECT labels->>km.field FROM evt)=km.value) OR
                (km.kind='label'     AND km.operator='contains' AND (SELECT labels->>km.field FROM evt) ILIKE (chr(37) || km.value || chr(37))) OR
                (km.kind='label'     AND km.operator='regex'    AND (SELECT labels->>km.field FROM evt) ~* km.value) OR
                (km.kind='regex'     AND km.operator='regex'    AND (
                    (SELECT alertname FROM evt) || ' ' || (SELECT labels::text FROM evt)
                ) ~* km.value)
             )::int) AS matched
      FROM kb_items ki
      JOIN kb_matchers km ON km.kb_id = ki.id
      WHERE ki.enabled = TRUE
      GROUP BY ki.id
    )
    SELECT
      ki.id,
      ki.title,
      ki.checks,
      ki.fixes,
      ki.severity,
      ki.version,
      COALESCE(s.success_rate, 50.0) AS success_rate  -- KB sin feedback: 50 por defecto
    FROM m
    JOIN kb_items ki ON ki.id = m.kb_id
    LEFT JOIN kb_stats s ON s.kb_id = ki.id
    WHERE m.total = m.matched
    ORDER BY
      CASE ki.severity
        WHEN 'critical' THEN 4
        WHEN 'high'     THEN 3
        WHEN 'medium'   THEN 2
        ELSE 1
      END DESC,
      COALESCE(s.success_rate, 50.0) DESC,
      ki.version DESC
    LIMIT 1;
    """

    with pg() as conn, conn.cursor() as cur:
        cur.execute(sql, (alertname, namespace, labels_json))
        row = cur.fetchone()
        if not row:
            return None
        kb_id, title, checks, fixes, severity, version, success_rate = row
        ctx = _context_from(evt)
        checks = [ _render(c, ctx) for c in (checks or []) ]
        fixes  = [ _render(f, ctx) for f in (fixes  or []) ]
        return {
            "kb_id": kb_id,
            "summary": title,
            "checks": checks,
            "fixes": fixes,
            "hypotheses": [],
            "severity": severity,
            "version": version,
            "success_rate": float(success_rate),
        }


def store_alert(cur, evt):
    cur.execute("""INSERT INTO alerts(fingerprint,alertname,labels,starts_at,status)
                   VALUES(%s,%s,%s,%s,%s) RETURNING id""",
                (evt.get("fingerprint"),
                 evt.get("alertname"),
                 Json(evt.get("labels",{})),
                 evt.get("startsAt"),
                 evt.get("status","firing")))
    return cur.fetchone()[0]

def store_decision(cur, alert_id, path, rule_id, context, rec, latency_ms, kb_id=None, confidence=None, reason=None, ai_request_id=None):
    cur.execute("""INSERT INTO decisions(alert_id,path,rule_id,context,recommendation,latency_ms,kb_id,confidence,reason,ai_request_id)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (alert_id, path, rule_id, Json(context or {}), Json(rec or {}), latency_ms, kb_id, confidence, reason, ai_request_id))
    return cur.fetchone()[0]

def store_ai_usage(cur, decision_id, alert_id, request_id, ai_response):
    usage = (ai_response or {}).get("usage") or {}
    if not usage:
        return
    cur.execute("""INSERT INTO ai_usage(decision_id, alert_id, request_id, provider, model, input_tokens, output_tokens, estimated_cost_usd, latency_ms)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    decision_id,
                    alert_id,
                    request_id,
                    ai_response.get("provider"),
                    ai_response.get("model"),
                    usage.get("inputTokens"),
                    usage.get("outputTokens"),
                    usage.get("estimatedCostUsd"),
                    usage.get("latencyMs"),
                ))

def format_msg(evt, rec):
    parts = [f"[{evt.get('alertname')}] {rec.get('summary','')}", "Checks:"]
    parts += [f"- {c}" for c in rec.get("checks",[])[:5]]
    parts += ["Fixes:"]
    parts += [f"- {f}" for f in rec.get("fixes",[])[:5]]
    return "\n".join(parts)

def _notify(decision_id, evt, rec, path):
    try:
        resp = requests.post(
            NOTIFIER_URL,
            json={"decision_id": decision_id, "text": format_msg(evt, rec)},
            timeout=5
        )
        log(
            "notifier_sent",
            path=path,
            decision_id=decision_id,
            status_code=resp.status_code,
        )
    except Exception as e:
        log(
            "notifier_error",
            path=path,
            decision_id=decision_id,
            error=str(e),
        )

def main():
    log("starting")
    while True:
        item = r.brpop("phylaxor_enriched", timeout=5)
        if not item:
            continue
        _, payload = item
        evt = json.loads(payload)
        t0 = time.time()
        labels = evt.get("labels") or {}
        log(
            "received_alert",
            alertname=evt.get("alertname"),
            fingerprint=evt.get("fingerprint"),
            namespace=labels.get("namespace"),
            pod=labels.get("pod"),
            node=labels.get("node"),
        )

        # 1) Store Alert
        with pg() as conn:
            with conn.cursor() as cur:
                alert_id = store_alert(cur, evt)
        log("stored_alert", alert_id=alert_id, fingerprint=evt.get("fingerprint"))

        # 2) Make Decision
        selected = make_decision(evt)

        # 3) Store & Notify
        latency = int((time.time()-t0)*1000)
        with pg() as conn:
            with conn.cursor() as cur:
                decision_id = store_decision(
                    cur, 
                    alert_id, 
                    selected["path"], 
                    selected["rule_id"], 
                    evt.get("context"), 
                    selected["rec"], 
                    latency_ms=latency, 
                    kb_id=selected["kb_id"], 
                    confidence=selected["confidence"], 
                    reason=selected["reason"],
                    ai_request_id=selected.get("ai_request_id")
                )
                if selected.get("ai_response"):
                    store_ai_usage(
                        cur,
                        decision_id,
                        alert_id,
                        selected.get("ai_request_id"),
                        selected.get("ai_response"),
                    )
        log(
            "decision_made",
            path=selected["path"],
            decision_id=decision_id,
            latency_ms=latency,
            kb_id=selected["kb_id"],
            rule_id=selected["rule_id"],
            confidence=selected["confidence"],
            ai_request_id=selected.get("ai_request_id"),
        )
        _notify(decision_id, evt, selected["rec"], selected["path"])

def make_decision(evt):
    """
    Selects the best decision based on confidence.
    Returns a dict with keys: path, rule_id, kb_id, rec, confidence, reason
    """
    candidates = []
    is_manual_ai = evt.get("force_ai", False)
    prev_rec = None
    hist_reason = {}
    kb = None

    # A. Gather Candidates (unless manual override)
    if not is_manual_ai:
        # History
        prev_rec, hist_reason = previous_decision(evt)
        
        # Log history status side-effect (kept here for observability during candidate gathering)
        log(
            "history_check",
            fingerprint=evt.get("fingerprint"),
            eligible=prev_rec is not None,
            gating_reason=hist_reason.get("gating_reason"),
            score_final=hist_reason.get("score_final"),
        )
        if DEBUG_HISTORY:
            log("history_debug", fingerprint=evt.get("fingerprint"), reason=hist_reason)

        if prev_rec:
            candidates.append({
                "path": "history",
                "rule_id": "previous",
                "kb_id": None,
                "rec": prev_rec,
                "confidence": hist_reason.get("score_final", 100),
                "reason": json.dumps(hist_reason)
            })

        # Knowledge Base
        kb = match_kb(evt)
        if kb:
            rec_kb = { "summary": kb["summary"], "checks": kb["checks"], "hypotheses": [], "fixes": kb["fixes"] }
            candidates.append({
                "path": "kb",
                "rule_id": f"kb:{kb['kb_id']}",
                "kb_id": kb["kb_id"],
                "rec": rec_kb,
                "confidence": KB_BASE_CONFIDENCE,
                "reason": "kb exact match"
            })
    else:
        hist_reason = {"gating_reason": "manual_override"}

    # B. AI / Fallback
    ai_conf = AI_BASE_CONFIDENCE
    ai_rule = "no_rule"
    ai_trigger = "auto"
    
    if is_manual_ai:
        ai_trigger = "manual"
    
    path_name = "ai" if is_manual_ai else "fallback"
    
    candidates.append({
        "path": path_name,
        "rule_id": ai_rule,
        "kb_id": None,
        "rec": None,
        "confidence": ai_conf,
        "reason": f"triggered_by={ai_trigger}"
    })

    # C. Select Best
    # Sort by confidence DESC. Stable sort preserves History > KB > AI order if confidences match.
    selected = sorted(candidates, key=lambda x: (x["confidence"] if x["confidence"] is not None else 0), reverse=True)[0]

    # D. If AI path, call Brain Gateway and map response; fallback on error
    if selected["path"] in ("ai", "fallback"):
        request_id = str(uuid.uuid4())
        decision_ctx = _build_decision_context(
            "ai",
            selected.get("confidence"),
            matched=False,
            hist_reason=hist_reason,
            kb=kb,
        )
        ai_request = _build_ai_request(evt, decision_ctx, request_id)
        ai_response, ai_error, _ = _call_brain_gateway(
            ai_request,
            request_id,
            evt.get("fingerprint"),
        )

        if ai_response:
            selected["rec"] = _ai_response_to_rec(ai_response)
            selected["ai_response"] = ai_response
            selected["ai_request_id"] = request_id
            selected["path"] = "ai"
            selected["rule_id"] = "ai:brain_gateway"
            selected["reason"] = f"triggered_by={ai_trigger}"
        else:
            selected["rec"] = _fallback_rec(
                evt,
                prev_rec=prev_rec,
                kb=kb,
                hist_reason=hist_reason,
                ai_error=ai_error,
            )
            selected["ai_request_id"] = request_id
            selected["ai_error"] = ai_error
            selected["path"] = "fallback"
            selected["rule_id"] = "no_rule"
            selected["reason"] = f"ai_unavailable:{ai_error}; triggered_by={ai_trigger}"
    return selected
if __name__ == "__main__":
    main()
