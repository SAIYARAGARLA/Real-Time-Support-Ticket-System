from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.jobs.scheduler import start_scheduler, stop_scheduler
from app.routers import agents, attachments, auth, categories, messages, notifications, reports, sla, tickets
from app.websockets.routes import router as websocket_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()


app = FastAPI(
    title="Real-Time Support Ticket System",
    description=(
        "FastAPI backend for support tickets, role-based access, automatic agent assignment, "
        "SLA escalation, WebSocket chat, notifications, attachments, and reports."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(auth.router)
app.include_router(agents.router)
app.include_router(categories.router)
app.include_router(sla.router)
app.include_router(tickets.router)
app.include_router(messages.router)
app.include_router(attachments.router)
app.include_router(notifications.router)
app.include_router(reports.router)
app.include_router(websocket_router)

Path("uploads").mkdir(exist_ok=True)
Path("static").mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", tags=["Health"])
async def root():
    return {"message": "Real-Time Support Ticket System API", "status": "running", "docs": "/docs"}


@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "healthy"}


@app.get("/chat-test", include_in_schema=True, tags=["WebSocket Testing"])
async def chat_test_page():
    return FileResponse("static/chat_test.html", media_type="text/html")
