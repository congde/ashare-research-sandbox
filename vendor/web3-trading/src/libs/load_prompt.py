from typing import Dict, Any, Optional
from mcp.mcp_http_client import mcp_client


async def get_prompt(prompt_map: dict, data: Optional[Dict[str, Any]] = None) -> str:
    return (await mcp_client.get_prompt(prompt_map["name"], data=data)) or prompt_map.get("template", "")
