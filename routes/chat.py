from fastapi import APIRouter
from pydantic import BaseModel
from agent import run_agent

router = APIRouter()


class ChatRequest(BaseModel):
    user_id: str
    bearer_token: str
    message: str


@router.post("/chat")
async def chat(request: ChatRequest):
    try:
        html = await run_agent(
            user_id=request.user_id,
            bearer_token=request.bearer_token,
            message=request.message
        )
        return {"success": True, "html": html}
    except Exception as e:
        return {"success": False, "error": str(e), "html": None}
