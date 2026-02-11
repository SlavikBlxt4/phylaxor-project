from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import psycopg2
import os
from pathlib import Path

app = FastAPI()

# ------------------------------
# DB
# ------------------------------
PG_DSN = os.getenv("PG_DSN", "dbname=phylaxor user=postgres password=postgres host=postgres")

def pg():
    return psycopg2.connect(PG_DSN)

# ------------------------------
# Templates & Static
# ------------------------------
BASE_DIR = Path(__file__).resolve().parent
templates_dir = BASE_DIR / "templates"
static_dir = BASE_DIR / "static"

# Fallback for legacy layout (templates/static next to src/)
if not templates_dir.exists():
    templates_dir = BASE_DIR.parent / "templates"
if not static_dir.exists():
    static_dir = BASE_DIR.parent / "static"

templates = Jinja2Templates(directory=str(templates_dir))
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# ------------------------------
# API: Feedback
# ------------------------------
class FeedbackIn(BaseModel):
    decision_id: int
    vote: bool
    notes: str | None = None

@app.post("/feedback")
def add_feedback(item: FeedbackIn):
    with pg() as conn:
        with conn.cursor() as cur:
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

# ------------------------------
# DASHBOARD ROUTES
# ------------------------------

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/dashboard/alerts", response_class=HTMLResponse)
async def dashboard_alerts(request: Request):
    with pg() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, alertname, fingerprint, starts_at, status
                FROM alerts ORDER BY id DESC LIMIT 100
            """)
            alerts = cur.fetchall()
    return templates.TemplateResponse("alerts.html", {"request": request, "alerts": alerts})


@app.get("/dashboard/decisions", response_class=HTMLResponse)
async def dashboard_decisions(request: Request):
    with pg() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT d.id, d.path, d.rule_id, d.kb_id, d.latency_ms, d.created_at, a.alertname
                FROM decisions d
                JOIN alerts a ON a.id = d.alert_id
                ORDER BY d.id DESC LIMIT 100
            """)
            decisions = cur.fetchall()

    return templates.TemplateResponse("decisions.html", {"request": request, "decisions": decisions})


@app.get("/dashboard/kb", response_class=HTMLResponse)
async def dashboard_kb(request: Request):
    with pg() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, title, severity, tags, version, enabled
                FROM kb_items ORDER BY id DESC
            """)
            items = cur.fetchall()

    return templates.TemplateResponse("kb.html", {"request": request, "items": items})


@app.get("/dashboard/matchers", response_class=HTMLResponse)
async def dashboard_matchers(request: Request):
    with pg() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, kb_id, kind, field, operator, value
                FROM kb_matchers ORDER BY id DESC
            """)
            matchers = cur.fetchall()

    return templates.TemplateResponse("matchers.html", {"request": request, "matchers": matchers})
