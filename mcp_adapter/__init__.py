"""MCP Adapter package for Chatterbox."""

from mcp_adapter.catalog import PROJECT_TOOL_SCHEMAS, VOICE_TOOL_SCHEMAS, get_tools_list
from mcp_adapter.project_tools import PROJECT_HANDLERS, handle_project_tool
from mcp_adapter.voice_tools import VOICE_HANDLERS, handle_voice_tool

__all__ = [
    "VOICE_TOOL_SCHEMAS",
    "PROJECT_TOOL_SCHEMAS",
    "get_tools_list",
    "VOICE_HANDLERS",
    "PROJECT_HANDLERS",
    "handle_voice_tool",
    "handle_project_tool",
]
