from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from routes.chat import router as chat_router
from routes.config import router as config_router
from routes.rules import router as rules_router
from routes.health import router as health_router

app = FastAPI(
    title="Attendance AI Agent",
    description="AI agent that answers attendance and leave questions using company APIs",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(chat_router)
app.include_router(config_router)
app.include_router(rules_router)


@app.get("/")
async def root():
    return {
        "service": "Attendance AI Agent",
        "version": "1.0.0",
        "endpoints": {
            "GET  /health": "Check if server is running",
            "POST /chat": "Send message from Flutter (user_id, bearer_token, message)",
            "POST /config": "Register your company APIs (replaces old config)",
            "GET  /config": "View current API config",
            "POST /rules": "Set agent behavior rules (replaces old rules)",
            "GET  /rules": "View current rules"
        }
    }
