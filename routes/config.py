from fastapi import APIRouter
from pydantic import BaseModel
from typing import List
from storage import save_config, load_config

router = APIRouter()


class APIDefinition(BaseModel):
    name: str
    description: str
    method: str
    endpoint: str
    parameters: List[str] = []


class ConfigRequest(BaseModel):
    base_url: str
    apis: List[APIDefinition]


@router.post("/config")
async def set_config(request: ConfigRequest):
    data = {
        "base_url": request.base_url,
        "apis": [api.model_dump() for api in request.apis]
    }
    save_config(data)
    return {
        "success": True,
        "message": f"Config saved. Previous config replaced. {len(request.apis)} API(s) registered.",
        "base_url": request.base_url,
        "apis_registered": [api.name for api in request.apis]
    }


@router.get("/config")
async def get_config():
    config = load_config()
    if not config:
        return {"configured": False, "message": "No config found. Call POST /config first."}
    return {"configured": True, **config}
