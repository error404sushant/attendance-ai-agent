from fastapi import APIRouter
from pydantic import BaseModel
from typing import List
from storage import save_rules, load_rules

router = APIRouter()


class RulesRequest(BaseModel):
    rules: List[str]


@router.post("/rules")
async def set_rules(request: RulesRequest):
    save_rules({"rules": request.rules})
    return {
        "success": True,
        "message": f"Rules saved. Previous rules completely replaced. {len(request.rules)} rule(s) active.",
        "rules": request.rules
    }


@router.get("/rules")
async def get_rules():
    return load_rules()
