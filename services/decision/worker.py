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

# Try specific import for different run contexts
try:
    import history_score
except ImportError:
    from . import history_score

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
        
    eligible, best_rec, reason = history_score.calculate_score(rows)
    
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
        print(
            f"[decision] notifier sent path={path} decision_id={decision_id} status={resp.status_code}",
            flush=True
        )
    except Exception as e:
        print(
            f"[decision] notifier error path={path} decision_id={decision_id}: {e}",
            flush=True
        )

def main():
    print("[decision] starting decision worker...", flush=True)
    while True:
        item = r.brpop("phylaxor_enriched", timeout=5)
        if not item:
            continue
        _, payload = item
        evt = json.loads(payload)
        t0 = time.time()
        labels = evt.get("labels") or {}
        print(
            f"[decision] received alert alertname={evt.get('alertname')} "
            f"fingerprint={evt.get('fingerprint')} namespace={labels.get('namespace')}",
            flush=True
        )

        # 1) guarda alerta
        with pg() as conn:
            with conn.cursor() as cur:
                alert_id = store_alert(cur, evt)
        print(
            f"[decision] stored alert id={alert_id} fingerprint={evt.get('fingerprint')}",
            flush=True
        )

        # 2) histórico primero
        prev_rec, hist_reason = previous_decision(evt)
        
        # Log history status
        print(
            f"[decision] history check fingerprint={evt.get('fingerprint')} "
            f"eligible={prev_rec is not None} reason={hist_reason.get('gating_reason')} "
            f"score={hist_reason.get('score_final')} samples={hist_reason.get('valid_count')}",
            flush=True
        )

        if prev_rec:
            latency = int((time.time()-t0)*1000)
            with pg() as conn:
                with conn.cursor() as cur:
                    decision_id = store_decision(
                        cur, alert_id, "history", "previous", evt.get("context"), 
                        prev_rec, latency_ms=latency, kb_id=None, 
                        confidence=hist_reason.get("score_final", 100), 
                        reason=json.dumps(hist_reason)
                    )
            print(f"[decision] decision path=history id={decision_id} latency_ms={latency}", flush=True)
            _notify(decision_id, evt, prev_rec, "history")
            continue

        # 3) buscar conocimiento en DB
        kb = match_kb(evt)
        if kb:
            rec = { "summary": kb["summary"], "checks": kb["checks"], "hypotheses": [], "fixes": kb["fixes"] }
            latency = int((time.time()-t0)*1000)
            with pg() as conn:
                with conn.cursor() as cur:
                    decision_id = store_decision(
                        cur, alert_id, "kb", f"kb:{kb['kb_id']}", evt.get("context"),
                        rec, latency_ms=latency, kb_id=kb["kb_id"], confidence=100, reason="kb exact match"
                    )
            print(f"[decision] decision path=kb id={decision_id} latency_ms={latency}", flush=True)
            _notify(decision_id, evt, rec, "kb")
            continue

        # 4) fallback (IA/semantic llegará luego)
        rec = {
          "summary": "No KB match. AI path not implemented yet.",
          "checks": ["kubectl get events -A | tail -n 50"],
          "hypotheses": [],
          "fixes": ["Add KB item or enable Brain Gateway"]
        }
        latency = int((time.time()-t0)*1000)
        with pg() as conn:
            with conn.cursor() as cur:
                decision_id = store_decision(cur, alert_id, "fallback", "no_rule", evt.get("context"), rec, latency_ms=latency, kb_id=None, confidence=None, reason="no kb/hist match")
        print(f"[decision] decision path=fallback id={decision_id} latency_ms={latency}", flush=True)
        _notify(decision_id, evt, rec, "fallback")

if __name__ == "__main__":
    main()
