import os, json, time, redis, requests, psycopg2
from psycopg2.extras import Json
from rules import rule_for

REDIS_HOST = os.getenv("REDIS_HOST","redis")
PG_DSN = os.getenv("PG_DSN","dbname=phylaxor user=postgres password=postgres host=postgres")
NOTIFIER_URL = os.getenv("NOTIFIER_URL","http://notifier:8082/send")

r = redis.Redis(host=REDIS_HOST, port=6379, db=0)

def pg():
    return psycopg2.connect(PG_DSN)
# prueba pipeline 2

def previous_decision(evt):
    fp  = evt.get("fingerprint")
    name = evt.get("alertname")
    pod  = evt.get("labels",{}).get("pod","")

    with pg() as conn:
        with conn.cursor() as cur:
            # 1) fingerprint exacto
            if fp:
                cur.execute("""
                    SELECT d.recommendation
                    FROM decisions d
                    JOIN alerts a ON a.id = d.alert_id
                    WHERE a.fingerprint = %s
                    ORDER BY d.id DESC
                    LIMIT 1;
                """, (fp,))
                row = cur.fetchone()
                if row: return row[0]

            # 2) alertname + namespace + pod
            cur.execute("""
                SELECT d.recommendation
                FROM decisions d
                JOIN alerts a ON a.id = d.alert_id
                WHERE a.alertname = %s
                  AND a.labels->>'namespace' = %s
                  AND a.labels->>'pod' = %s
                ORDER BY d.id DESC
                LIMIT 1;
            """, (name, ns, pod))
            row = cur.fetchone()
            if row: return row[0]

            # 3) alertname + namespace
            cur.execute("""
                SELECT d.recommendation
                FROM decisions d
                JOIN alerts a ON a.id = d.alert_id
                WHERE a.alertname = %s
                  AND a.labels->>'namespace' = %s
                ORDER BY d.id DESC
                LIMIT 1;
            """, (name, ns))
            row = cur.fetchone()
            if row: return row[0]

            # 4) alertname solo
            cur.execute("""
                SELECT d.recommendation
                FROM decisions d
                JOIN alerts a ON a.id = d.alert_id
                WHERE a.alertname = %s
                ORDER BY d.id DESC
                LIMIT 1;
            """, (name,))
            row = cur.fetchone()
            return row[0] if row else None

def store_alert(cur, evt):
    cur.execute("""insert into alerts(fingerprint,alertname,labels,starts_at,status)
                   values(%s,%s,%s,%s,%s) returning id""",
                (evt.get("fingerprint"),
                 evt.get("alertname"),
                 Json(evt.get("labels",{})),
                 evt.get("startsAt"),
                 evt.get("status","firing")))
    return cur.fetchone()[0]

def store_decision(cur, alert_id, path, rule_id, context, rec, latency_ms):
    cur.execute("""insert into decisions(alert_id,path,rule_id,context,recommendation,latency_ms)
                   values(%s,%s,%s,%s,%s,%s) returning id""",
                (alert_id, path, rule_id, Json(context or {}), Json(rec or {}), latency_ms))
    return cur.fetchone()[0]

def format_msg(evt, rec):
    parts = [f"[{evt.get('alertname')}] {rec.get('summary','')}", "Checks:"]
    parts += [f"- {c}" for c in rec.get("checks",[])[:5]]
    parts += ["Fixes:"]
    parts += [f"- {f}" for f in rec.get("fixes",[])[:5]]
    return "\n".join(parts)

def main():
    while True:
        item = r.brpop("phylaxor_enriched", timeout=5)
        if not item:
            continue
        _, payload = item
        evt = json.loads(payload)
        t0 = time.time()

        # guarda alerta
        with pg() as conn:
            with conn.cursor() as cur:
                alert_id = store_alert(cur, evt)

        t0 = time.time()

        # aplica reglas
        rule = rule_for(evt)
        if rule:
            rec = {
              "summary": rule["summary"],
              "checks": rule["checks"],
              "hypotheses": [],
              "fixes": rule["fixes"]
            }
            latency = int((time.time()-t0)*1000)
            with pg() as conn:
                with conn.cursor() as cur:
                    decision_id = store_decision(cur, alert_id, "rule", rule["rule_id"], evt.get("context"), rec, latency)
            # notifica
            try:
                requests.post(NOTIFIER_URL, json={"decision_id": decision_id, "text": format_msg(evt, rec)}, timeout=5)
            except Exception as e:
                print("Notifier error:", e)
            continue

        # si no hay regla aún, de momento avisamos con un mensaje genérico (IA llegará luego)
        rec = {
          "summary": "No matching rule. AI path not implemented yet.",
          "checks": ["kubectl get events -A | tail -n 50"],
          "hypotheses": [],
          "fixes": ["Add rule or enable Brain Gateway"]
        }
        latency = int((time.time()-t0)*1000)
        with pg() as conn:
            with conn.cursor() as cur:
                decision_id = store_decision(cur, alert_id, "rule", "no_rule_placeholder", evt.get("context"), rec, latency)
        try:
            requests.post(NOTIFIER_URL, json={"decision_id": decision_id, "text": format_msg(evt, rec)}, timeout=5)
        except Exception as e:
            print("Notifier error:", e)

if __name__ == "__main__":
    main()
