import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List
from openai import AsyncOpenAI
from storage import save_config, load_config
from curl_parser import parse_curl

router = APIRouter()


class APIInput(BaseModel):
    curl: str
    description: str


class ConfigRequest(BaseModel):
    apis: List[APIInput]


async def _enhance_description(api_info: dict, raw_description: str) -> str:
    """Rewrite the user's raw description into an AI-understandable trigger-condition format."""
    client = AsyncOpenAI(
        base_url=os.getenv("AI_BASE_URL", "http://localhost:20128/v1"),
        api_key=os.getenv("AI_API_KEY", "dummy")
    )

    prompt = f"""You are configuring an AI assistant that routes user questions to APIs.

Convert this rough API description into a clear, structured format with:
1. WHEN to call this API — list of trigger questions/keywords the user might say
2. WHAT it returns — key fields in the response

API info:
- Endpoint: {api_info['method']} {api_info['base_url']}{api_info['endpoint']}
- Parameters: {api_info['parameters']}
- Defaults (hardcoded values from curl): {api_info.get('defaults', {})}
- Raw description from user: "{raw_description}"

Write 2-3 sentences in this format:
"Use when user asks about: [trigger words/questions]. Returns: [what it gives back, key fields]."

Rules:
- Be specific about trigger words so the AI routes correctly
- Mention key response fields so the AI knows what data it has
- Keep it under 60 words
- Return ONLY the improved description, no quotes, no explanation"""

    try:
        response = await client.chat.completions.create(
            model=os.getenv("AI_MODEL", "auto/coding:free"),
            messages=[{"role": "user", "content": prompt}],
        )
        enhanced = response.choices[0].message.content.strip().strip('"\'')
        return enhanced if enhanced else raw_description
    except Exception:
        return raw_description  # fallback to original if AI fails


@router.post("/config")
async def set_config(request: ConfigRequest):
    parsed_apis = []
    base_url = None

    for item in request.apis:
        try:
            parsed = parse_curl(item.curl)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Bad curl: {e}")

        if base_url is None:
            base_url = parsed["base_url"]

        # Enhance the description using AI before saving
        enhanced_desc = await _enhance_description(parsed, item.description)

        parsed_apis.append({
            "name": parsed["name"],
            "description": enhanced_desc,
            "raw_description": item.description,   # keep original too
            "method": parsed["method"],
            "base_url": parsed["base_url"],
            "endpoint": parsed["endpoint"],
            "parameters": parsed["parameters"],
            "defaults": parsed.get("defaults", {}),
            "original_curl": item.curl,
        })

    data = {"base_url": base_url, "apis": parsed_apis}
    save_config(data)

    return {
        "success": True,
        "message": f"Config saved. Previous config replaced. {len(parsed_apis)} API(s) registered.",
        "base_url": base_url,
        "apis_registered": [
            {
                "name": a["name"],
                "method": a["method"],
                "endpoint": a["endpoint"],
                "parameters": a["parameters"],
                "description_enhanced": a["description"],
            }
            for a in parsed_apis
        ]
    }


@router.get("/config")
async def get_config():
    config = load_config()
    if not config:
        return {"configured": False, "message": "No config found. Call POST /config first."}
    return {"configured": True, **config}
