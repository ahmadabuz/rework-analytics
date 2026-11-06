# main.py
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import db

app = FastAPI(title="Rework Analytics")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


def get_agents():
    conn = db.get_conn()
    rows = conn.execute("SELECT * FROM agents ORDER BY name").fetchall()
    conn.close()
    return rows


@app.get("/", response_class=HTMLResponse)
def home():
    return RedirectResponse(url="/queue/1")


@app.get("/queue/{agent_id}", response_class=HTMLResponse)
def queue(request: Request, agent_id: int):
    tickets = db.get_agent_queue(agent_id)
    agents = get_agents()
    current = next((a for a in agents if a["id"] == agent_id), None)
    return templates.TemplateResponse(
        request=request,
        name="queue.html",
        context={
            "tickets": tickets, "agents": agents,
            "current_agent": current, "agent_id": agent_id,
        },
    )


@app.get("/ticket/{ticket_id}", response_class=HTMLResponse)
def ticket_detail(request: Request, ticket_id: int):
    ticket, events = db.get_ticket_with_events(ticket_id)
    agents = get_agents()
    return templates.TemplateResponse(
        request=request,
        name="ticket.html",
        context={"ticket": ticket, "events": events, "agents": agents},
    )


@app.post("/ticket/{ticket_id}/action")
def ticket_action(ticket_id: int, action: str = Form(...), agent_id: int = Form(...),
                  note: str = Form("")):
    if action == "resolve":
        db.append_event(ticket_id, "resolved", agent_id, note or "Resolved by agent")
    elif action == "reopen":
        db.append_event(ticket_id, "reopened", agent_id, note or "Reopened")
    elif action == "comment":
        db.append_event(ticket_id, "commented", agent_id, note or "")
    elif action == "reassign":
        conn = db.get_conn()
        conn.execute("UPDATE tickets SET assigned_agent_id = ? WHERE id = ?", (agent_id, ticket_id))
        conn.commit()
        conn.close()
        db.append_event(ticket_id, "assigned", agent_id, f"Reassigned")
    return RedirectResponse(url=f"/ticket/{ticket_id}", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    agent_rework, category_rework, chronic = db.get_supervisor_dashboard()
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "agent_rework": agent_rework,
            "category_rework": category_rework,
            "chronic": chronic,
        },
    )