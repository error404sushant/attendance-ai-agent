import json
import os
import httpx
from openai import AsyncOpenAI
from datetime import datetime
from storage import load_config, load_rules


async def run_agent(user_id: str, bearer_token: str, message: str) -> str:
    config = load_config()
    rules = load_rules()

    if not config:
        return "<html><body style='background:#1a1a2e;color:white;font-family:sans-serif;padding:20px'><p style='color:#ff6b6b'>Agent not configured. Ask admin to call POST /config first.</p></body></html>"

    base_url = config.get("base_url", "").rstrip("/")
    apis = config.get("apis", [])
    rules_list = rules.get("rules", [])

    now = datetime.now()

    system_prompt = f"""You are an AI attendance assistant for employees.

CONTEXT (auto-injected — do NOT ask the user for these):
- Today: {now.strftime('%Y-%m-%d')}
- Month: {now.strftime('%B')} (number: {now.month})
- Year: {now.year}
- User ID: {user_id}
- API Base URL: {base_url}

RULES (follow strictly):
{chr(10).join(f'{i+1}. {r}' for i, r in enumerate(rules_list))}

AVAILABLE APIs:
{json.dumps(apis, indent=2)}

STEP-BY-STEP:
1. Read the user's message carefully
2. Decide which API from the list above fits best (use the description field to decide)
3. Call that API tool with the right parameters
4. When you get the JSON response, format it as a beautiful HTML page
5. HTML must have: big summary number at top → chart (use Chart.js from CDN) → details table below
6. Style guide: background #1a1a2e, card background #16213e, accent #00C9A7, text white, rounded corners
7. Make it responsive — max-width 600px, works on phone
8. Return ONLY the HTML — no explanation, no markdown, no code blocks"""

    tools = []
    for api in apis:
        param_names = [p.strip() for p in api.get("parameters", [])]
        properties = {p: {"type": "string", "description": p} for p in param_names}
        tools.append({
            "type": "function",
            "function": {
                "name": api["name"],
                "description": api["description"],
                "parameters": {
                    "type": "object",
                    "properties": properties,
                }
            }
        })

    client = AsyncOpenAI(
        base_url=os.getenv("AI_BASE_URL", "http://localhost:20128/v1"),
        api_key=os.getenv("AI_API_KEY", "dummy")
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": message}
    ]

    for _ in range(6):
        kwargs = {
            "model": os.getenv("AI_MODEL", "auto/coding:free"),
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = await client.chat.completions.create(**kwargs)
        choice = response.choices[0]

        if choice.finish_reason == "tool_calls":
            messages.append(choice.message)

            for tool_call in choice.message.tool_calls:
                fn_name = tool_call.function.name
                fn_args = json.loads(tool_call.function.arguments)

                api_config = next((a for a in apis if a["name"] == fn_name), None)
                if not api_config:
                    result = {"error": f"Unknown API: {fn_name}"}
                else:
                    # Auto-inject common fields if AI didn't provide them
                    if "user_id" not in fn_args:
                        fn_args["user_id"] = user_id
                    if "month" not in fn_args:
                        fn_args["month"] = now.month
                    if "year" not in fn_args:
                        fn_args["year"] = now.year

                    endpoint = api_config["endpoint"]
                    method = api_config.get("method", "GET").upper()

                    try:
                        async with httpx.AsyncClient(timeout=30) as http_client:
                            headers = {"Authorization": f"Bearer {bearer_token}"}
                            if method == "GET":
                                resp = await http_client.get(
                                    f"{base_url}{endpoint}",
                                    params=fn_args,
                                    headers=headers
                                )
                            else:
                                resp = await http_client.post(
                                    f"{base_url}{endpoint}",
                                    json=fn_args,
                                    headers=headers
                                )
                            result = resp.json()
                    except Exception as e:
                        result = {"error": str(e)}

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result)
                })
        else:
            content = choice.message.content or ""
            # Strip markdown fences if model returns them
            for fence in ["```html", "```"]:
                if content.startswith(fence):
                    content = content[len(fence):]
            if content.endswith("```"):
                content = content[:-3]
            return content.strip()

    return "<html><body style='background:#1a1a2e;color:white;padding:20px'><p>Could not generate a response. Please try again.</p></body></html>"
