from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import psycopg2
import os

app = FastAPI()

PG_DSN = os.getenv("PG_DSN", "dbname=phylaxor user=postgres password=postgres host=postgres")

def pg():
    return psycopg2.connect(PG_DSN)

class FeedbackIn(BaseModel):
    decision_id: int
    vote: bool
    notes: str | None = None

@app.post("/feedback")
def add_feedback(item: FeedbackIn):
    with pg() as conn:
        with conn.cursor() as cur:
            # check decision exists
            cur.execute("SELECT id FROM decisions WHERE id = %s", (item.decision_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Decision not found")

            cur.execute("""
                INSERT INTO feedback(decision_id, vote, notes)
                VALUES (%s, %s, %s)
                RETURNING id
            """, (item.decision_id, item.vote, item.notes))
            fid = cur.fetchone()[0]

    return {"ok": True, "feedback_id": fid}

@app.get("/feedback/{decision_id}")
def list_feedback(decision_id: int):
    with pg() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, vote, notes, created_at
                FROM feedback
                WHERE decision_id = %s
                ORDER BY created_at DESC
            """, (decision_id,))
            rows = cur.fetchall()

    return [
        {"id": r[0], "vote": r[1], "notes": r[2], "created_at": r[3]} for r in rows
    ]

