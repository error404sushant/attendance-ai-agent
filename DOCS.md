# Attendance AI Agent — Documentation

## What This Is

A Python backend that connects your Flutter app to your company's attendance APIs through an AI agent. The AI understands what the user is asking, calls the right API, and returns beautiful HTML with charts — which Flutter displays in a WebView.

---

## Architecture / Flow

```
Flutter App
    │
    │  POST /chat { user_id, bearer_token, message }
    ▼
Python Backend (agent.facenova.uk)
    │
    │  Reads config + rules from JSON files
    │  Sends message to AI (OmniRoute)
    ▼
AI Agent (OmniRoute → free model)
    │
    │  Decides which company API to call
    │  Calls company API with bearer_token
    ▼
Company Attendance API
    │
    │  Returns JSON data
    ▼
AI Agent
    │
    │  Formats data as HTML with chart
    ▼
Python Backend
    │
    │  Returns { success: true, html: "..." }
    ▼
Flutter App → WebView renders HTML
```

---

## API Endpoints

### GET /health
Check if server is running.
```
Response: { "status": "ok", "apis_count": 2, "rules_count": 6 }
```

---

### POST /config
Register your company APIs. **Calling this again REPLACES all old APIs.**

```json
Request:
{
  "base_url": "https://your-company-api.com",
  "apis": [
    {
      "name": "get_attendance",
      "description": "Call this when user asks about attendance, present/absent days, or attendance summary",
      "method": "GET",
      "endpoint": "/api/v1/attendance",
      "parameters": ["user_id", "month", "year"]
    },
    {
      "name": "get_leave_balance",
      "description": "Call this when user asks about leaves, remaining leave, sick/casual leave",
      "method": "GET",
      "endpoint": "/api/v1/leaves/balance",
      "parameters": ["user_id"]
    }
  ]
}

Response:
{
  "success": true,
  "message": "Config saved. Previous config replaced. 2 API(s) registered.",
  "apis_registered": ["get_attendance", "get_leave_balance"]
}
```

**Key point:** The `description` field is what the AI reads to decide WHEN to call each API. Write it clearly.

---

### GET /config
View currently registered APIs.

---

### POST /rules
Set agent behavior rules. **Calling this again REPLACES all old rules.**

```json
Request:
{
  "rules": [
    "Only answer questions about attendance, leaves, and holidays.",
    "Never reveal the bearer_token in any response.",
    "Always return HTML with a chart. Dark background. Mobile friendly.",
    "Never make up data. Always call an API first.",
    "If user asks about salary or anything else, say: I can only help with attendance and leave information."
  ]
}

Response:
{
  "success": true,
  "message": "Rules saved. Previous rules completely replaced. 5 rule(s) active."
}
```

---

### GET /rules
View currently active rules.

---

### POST /chat
Main endpoint. Flutter calls this for every user message.

```json
Request:
{
  "user_id": "emp_123",
  "bearer_token": "eyJhbG...",
  "message": "Show my attendance for this month"
}

Response (success):
{
  "success": true,
  "html": "<html>...full HTML with chart...</html>"
}

Response (error):
{
  "success": false,
  "error": "Could not connect to company API",
  "html": null
}
```

---

## What the Agent Auto-Injects

You never need to send date/time from Flutter. The backend adds:

| Field | Example | Source |
|---|---|---|
| `current_date` | `2026-07-17` | Server clock |
| `current_month` | `July` (and `7`) | Server clock |
| `current_year` | `2026` | Server clock |
| `user_id` | `emp_123` | From Flutter |
| `bearer_token` | `eyJ...` | From Flutter (never exposed in HTML) |

---

## Memory / Config Behavior

- `POST /config` → **completely replaces** old config. No merging.
- `POST /rules` → **completely replaces** old rules. No merging.
- The agent always reads the **latest saved config** on every chat request.
- Config is stored in `agent_config.json`, rules in `agent_rules.json`.

---

## Running Locally

```bash
cd backend
cp .env.example .env
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Visit: http://localhost:8000

Make sure OmniRoute is running first:
```bash
claude-free  # or: cd OmniRoute && npm run dev
```

---

## Running on Server (agent.facenova.uk)

### First-time setup
```bash
# SSH into server
ssh root@164.68.117.244

# Clone the repo
git clone YOUR_GITHUB_REPO_URL /opt/attendance-agent
cd /opt/attendance-agent/backend

# Run setup script
bash deploy/setup_server.sh
```

### After code changes (update server)
```bash
ssh root@164.68.117.244
cd /opt/attendance-agent
git pull
systemctl restart attendance-agent
```

### Check server logs
```bash
ssh root@164.68.117.244
journalctl -u attendance-agent -f
```

### Check server status
```bash
systemctl status attendance-agent
```

---

## Server .env (set once on server)

```
AI_BASE_URL=http://localhost:20128/v1
AI_MODEL=auto/coding:free
AI_API_KEY=dummy
DATA_DIR=/opt/attendance-agent/backend
PORT=8000
```

---

## Postman Collection

Import `postman_collection.json` into Postman.

Set the `base_url` variable to:
- Local testing: `http://localhost:8000`
- Production: `https://agent.facenova.uk`

**Order to call when setting up:**
1. `GET /health` — confirm server is running
2. `POST /config` — register your APIs
3. `POST /rules` — set behavior rules
4. `GET /health` — confirm apis_count and rules_count are correct
5. `POST /chat` — test with a real message

---

## Adding a New API Later

Just call `POST /config` again with ALL your APIs including the new one.
The old list is completely replaced, so always include everything.

Example — adding a 3rd API (holidays):
```json
POST /config
{
  "base_url": "https://your-company-api.com",
  "apis": [
    { "name": "get_attendance", ... },
    { "name": "get_leave_balance", ... },
    { "name": "get_holidays", "description": "Call this when user asks about public holidays", ... }
  ]
}
```

---

## File Structure

```
backend/
├── main.py                  ← FastAPI app entry point
├── agent.py                 ← AI agent logic (OmniRoute + tool calling)
├── storage.py               ← Read/write config and rules JSON files
├── routes/
│   ├── chat.py              ← POST /chat
│   ├── config.py            ← POST/GET /config
│   ├── rules.py             ← POST/GET /rules
│   └── health.py            ← GET /health
├── .env                     ← Your environment variables (not in git)
├── .env.example             ← Template
├── requirements.txt         ← Python dependencies
├── postman_collection.json  ← Import into Postman
├── DOCS.md                  ← This file
└── deploy/
    ├── setup_server.sh      ← One-time server setup
    ├── attendance-agent.service ← Systemd service
    └── nginx.conf           ← Nginx config for agent.facenova.uk
```
