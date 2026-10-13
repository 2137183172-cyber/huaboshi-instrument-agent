from typing import TypedDict, Optional, Dict, Any

class AgentState(TypedDict, total=False):
    user_query: str
    intent: str
    slots: Dict[str, Any]
    workflow_result: Dict[str, Any]
    final_result: Dict[str, Any]
    error: Optional[str]