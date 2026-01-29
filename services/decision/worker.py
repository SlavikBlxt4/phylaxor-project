import os, json, time, redis, requests, psycopg2
from psycopg2.extras import Json

REDIS_HOST   = os.getenv("REDIS_HOST","redis")
PG_DSN       = os.getenv("PG_DSN","dbname=phylaxor user=postgres password=postgres host=postgres.phylaxor-db.svc.cluster.local")
NOTIFIER_URL = os.getenv("NOTIFIER_URL","http://notifier:8082/send")

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

import json
import time

# Ensure strictly running as script works if cwd is weird
import sys
import os
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

def store_decision(cur, alert_id, path, rule_id, context, rec, latency_ms, kb_id=None, confidence=None, reason=None):
    cur.execute("""INSERT INTO decisions(alert_id,path,rule_id,context,recommendation,latency_ms,kb_id,confidence,reason)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (alert_id, path, rule_id, Json(context or {}), Json(rec or {}), latency_ms, kb_id, confidence, reason))
    return cur.fetchone()[0]

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
                    reason=selected["reason"]
                )
        log(
            "decision_made",
            path=selected["path"],
            decision_id=decision_id,
            latency_ms=latency,
            kb_id=selected["kb_id"],
            rule_id=selected["rule_id"],
            confidence=selected["confidence"]
        )
        _notify(decision_id, evt, selected["rec"], selected["path"])

def make_decision(evt):
    """
    Selects the best decision based on confidence.
    Returns a dict with keys: path, rule_id, kb_id, rec, confidence, reason
    """
    candidates = []
    is_manual_ai = evt.get("force_ai", False)

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

    # B. AI / Fallback
    ai_conf = AI_BASE_CONFIDENCE
    ai_rule = "no_rule"
    ai_trigger = "auto"
    
    if is_manual_ai:
        ai_trigger = "manual"
    
    path_name = "ai" if is_manual_ai else "fallback"
    
    rec_ai = {
      "summary": "AI Analysis requested." if is_manual_ai else "No KB match. AI path not implemented yet.",
      "checks": ["kubectl get events -A | tail -n 50"],
      "hypotheses": [],
      "fixes": ["Add KB item or enable Brain Gateway"]
    }
    
    candidates.append({
        "path": path_name,
        "rule_id": ai_rule,
        "kb_id": None,
        "rec": rec_ai,
        "confidence": ai_conf,
        "reason": f"triggered_by={ai_trigger}"
    })

    # C. Select Best
    # Sort by confidence DESC. Stable sort preserves History > KB > AI order if confidences match.
    selected = sorted(candidates, key=lambda x: (x["confidence"] if x["confidence"] is not None else 0), reverse=True)[0]
    return selected
if __name__ == "__main__":
    main()
