import json
import os

DATA_DIR = os.getenv("DATA_DIR", ".")
CONFIG_FILE = os.path.join(DATA_DIR, "agent_config.json")
RULES_FILE = os.path.join(DATA_DIR, "agent_rules.json")

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
