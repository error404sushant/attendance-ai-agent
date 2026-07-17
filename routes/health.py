from fastapi import APIRouter
from storage import load_config, load_rules

router = APIRouter()


@router.get("/health")
async def health():
    config = load_config()
    rules = load_rules()
    return {
        "status": "ok",
        "service": "Attendance AI Agent",
        "config_loaded": bool(config),
        "apis_count": len(config.get("apis", [])) if config else 0,
        "rules_count": len(rules.get("rules", []))
    }
