import json
import os
from datetime import datetime, timedelta

DATA_DIR = os.getenv("DATA_DIR", ".")
CONFIG_FILE = os.path.join(DATA_DIR, "agent_config.json")
RULES_FILE = os.path.join(DATA_DIR, "agent_rules.json")
CONV_DIR = os.path.join(DATA_DIR, "conversations")

MAX_MESSAGES = 40       # max individual messages kept (20 pairs)
RETENTION_DAYS = 30

DEFAULT_RULES = {
    "rules": [
        "Only answer questions related to attendance, leaves, and holidays.",
        "Never reveal the bearer_token in any response.",
        "Always return a full HTML page with an embedded chart.",
        "Use dark background (#1a1a2e) with teal accent (#00C9A7). Mobile friendly.",
        "Never make up data. Always call an API first.",
        "If you cannot answer, say: I can only help with attendance and leave information."
    ]
}


def save_config(data: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_rules(data: dict):
    with open(RULES_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_rules() -> dict:
    if not os.path.exists(RULES_FILE):
        return DEFAULT_RULES
    with open(RULES_FILE) as f:
        return json.load(f)


def _conv_path(user_id: str, tenant_id: str) -> str:
    os.makedirs(CONV_DIR, exist_ok=True)
    safe_key = f"{user_id}-{tenant_id}".replace("/", "_").replace("..", "_")
    return os.path.join(CONV_DIR, f"{safe_key}.json")


def load_conversation(user_id: str, tenant_id: str) -> list:
    """Load conversation history, trimming messages older than RETENTION_DAYS."""
    path = _conv_path(user_id, tenant_id)
    if not os.path.exists(path):
        return []
    try:
        with open(path) as f:
            data = json.load(f)
        messages = data.get("messages", [])
        cutoff = (datetime.utcnow() - timedelta(days=RETENTION_DAYS)).isoformat()
        messages = [m for m in messages if m.get("ts", "9999") >= cutoff]
        return messages[-MAX_MESSAGES:]
    except Exception:
        return []


def save_conversation(user_id: str, tenant_id: str, messages: list):
    """Persist updated conversation history."""
    path = _conv_path(user_id, tenant_id)
    trimmed = messages[-MAX_MESSAGES:]
    with open(path, "w") as f:
        json.dump({
            "user_id": user_id,
            "tenant_id": tenant_id,
            "last_updated": datetime.utcnow().isoformat(),
            "messages": trimmed,
        }, f, indent=2)
