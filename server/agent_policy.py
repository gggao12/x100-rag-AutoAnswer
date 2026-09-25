"""Agent 风险策略：只读自动执行，写操作确认。"""
from .registry import registry
MAX_AGENT_STEPS=4
MAX_TOOL_CALLS=3
def requires_confirmation(tool_name: str) -> bool:
    tool=registry.get(tool_name)
    return bool(tool and tool.risk_level in ("write", "high_risk"))
