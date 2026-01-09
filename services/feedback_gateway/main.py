import os, time, requests, psycopg2
from psycopg2.extras import Json

TOKEN = os.getenv("TELEGRAM_TOKEN")
PG_DSN = os.getenv("PG_DSN", "dbname=phylaxor user=postgres password=postgres host=postgres.phylaxor-db.svc.cluster.local")

API = f"https://api.telegram.org/bot{TOKEN}"

OFFSET_FILE = os.getenv("OFFSET_FILE", "/tmp/offset.txt")

def pg():
    return psycopg2.connect(PG_DSN)

def mark_offset(offset):
    # nos aseguramos de que el directorio exista, por si algún día no es /tmp
    os.makedirs(os.path.dirname(OFFSET_FILE), exist_ok=True)
    with open(OFFSET_FILE, "w") as f:
        f.write(str(offset))

def get_offset():
    try:
        with open(OFFSET_FILE) as f:
            return int(f.read())
    except Exception:
        return 0

def save_feedback(decision_id, vote):
    with pg() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO feedback(decision_id, vote) VALUES (%s,%s)",
                (decision_id, vote)
            )

def run():
    offset = get_offset()
    print("[feedback] starting feedback poller...", flush=True)

    while True:
        resp = requests.get(f"{API}/getUpdates", params={"timeout":25,"offset":offset})
        data = resp.json()

        for upd in data.get("result", []):
            offset = upd["update_id"] + 1
            mark_offset(offset)

            cq = upd.get("callback_query")
            if not cq: 
                continue

            # format: decision:52:up
            payload = cq["data"].split(":")
            if len(payload) != 3: 
                continue

            _, decision_id, vote = payload
            save_feedback(int(decision_id), vote=="up")
            print(
                f"[feedback] saved decision_id={decision_id} vote={vote}",
                flush=True
            )

            # confirm to user
            requests.post(f"{API}/answerCallbackQuery", data={
                "callback_query_id": cq["id"],
                "text": "✅ Feedback received!"
            })

        time.sleep(1)

if __name__ == "__main__":
    run()
