from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List
from storage import save_config, load_config
from curl_parser import parse_curl

router = APIRouter()


class APIInput(BaseModel):
    curl: str
    description: str


class ConfigRequest(BaseModel):
    apis: List[APIInput]


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

        parsed_apis.append({
            "name": parsed["name"],
            "description": item.description,
            "method": parsed["method"],
            "endpoint": parsed["endpoint"],
            "parameters": parsed["parameters"],
            "original_curl": item.curl,
        })

    data = {"base_url": base_url, "apis": parsed_apis}
    save_config(data)

    return {
        "success": True,
        "message": f"Config saved. Previous config replaced. {len(parsed_apis)} API(s) registered.",
        "base_url": base_url,
        "apis_registered": [
            {"name": a["name"], "method": a["method"], "endpoint": a["endpoint"], "parameters": a["parameters"]}
            for a in parsed_apis
        ]
    }


@router.get("/config")
async def get_config():
    config = load_config()
    if not config:
        return {"configured": False, "message": "No config found. Call POST /config first."}
    return {"configured": True, **config}
