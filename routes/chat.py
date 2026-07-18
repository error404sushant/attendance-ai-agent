from fastapi import APIRouter
from pydantic import BaseModel
from agent import run_agent

router = APIRouter()


class ChatRequest(BaseModel):
    user_id: str
    tenant_id: str = "default"   # optional for now; defaults to "default"
    bearer_token: str
    message: str
    format: str = "html"         # "html" for rich cards, "text" for plain text only


@router.post("/chat")
async def chat(request: ChatRequest):
    try:
        result = await run_agent(
            user_id=request.user_id,
            tenant_id=request.tenant_id,
            bearer_token=request.bearer_token,
            message=request.message,
            format=request.format,
        )
        return {"success": True, "html": result.get("html"), "text": result.get("text"), "card_height": result.get("card_height", 480)}
    except Exception as e:
        return {"success": False, "error": str(e), "html": None, "text": None}
