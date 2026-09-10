"""Chatterbox MCP Server - Model Context Protocol tool provider for local voice cloning.

Communicates with the local Chatterbox REST API server to expose speech synthesis,
voice conversion, quality evaluation, and safe local audio exports.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from mcp_adapter.catalog import PROJECT_TOOL_SCHEMAS, VOICE_TOOL_SCHEMAS, VOICE_PROJECT_TOOL_SCHEMAS, get_tools_list
from mcp_adapter.project_tools import handle_project_tool
from mcp_adapter.voice_project_tools import handle_voice_project_tool
from mcp_adapter.voice_tools import handle_voice_tool
from mcp_adapter.runtime_tools import (
    handle_runtime_capabilities,
    handle_runtime_preflight,
    handle_validate_runtime,
    handle_validation_status,
    handle_validation_report,
    handle_validation_cancel,
)
from mcp_adapter.asset_tools import handle_asset_tool
from mcp_adapter.series_tools import (
    handle_series_create,
    handle_series_get,
    handle_series_add_episode,
    handle_series_produce,
    handle_series_status,
    handle_series_review_queue,
    handle_series_cancel,
)
from mcp_adapter.health_tools import (
    handle_voice_health,
    handle_voice_events,
    handle_voice_diagnostics,
    handle_voice_series_health,
    handle_voice_series_events,
)

# Backup standard stdout and redirect default sys.stdout to sys.stderr
# This prevents random print() statements from corrupting the JSON-RPC stdin/stdout channel.
rpc_stdout = sys.stdout
sys.stdout = sys.stderr

# Set UTF-8 encoding for stdio
if hasattr(rpc_stdout, "reconfigure"):
    rpc_stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_MCP_OUTPUT_DIR = PROJECT_DIR / "outputs" / "mcp"
API_URL = os.getenv("CHATTERBOX_API_URL", "http://127.0.0.1:8000")


def log(msg: str) -> None:
    """Log helper writing to stderr (standard for stdio MCP debug logs)."""
    sys.stderr.write(f"[Chatterbox MCP] {msg}\n")
    sys.stderr.flush()


def make_api_request(
    path: str,
    method: str = "GET",
    data: bytes | dict | None = None,
    headers: dict | None = None,
    timeout: float = 30.0,
) -> dict:
    """Make HTTP request to local Chatterbox REST API with custom timeout and robust error catching."""
    url = f"{API_URL.rstrip('/')}/{path.lstrip('/')}"
    log(f"API Request: {method} {url}")

    req_headers = {"Accept": "application/json"}
    api_key = os.getenv("CHATTERBOX_API_KEY")
    if api_key:
        req_headers["X-API-Key"] = api_key

    if headers:
        req_headers.update(headers)

    req_data = None
    if data is not None:
        if isinstance(data, dict):
            req_data = json.dumps(data).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
        elif isinstance(data, bytes):
            req_data = data
        else:
            req_data = str(data).encode("utf-8")

    req = urllib.request.Request(url, data=req_data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            resp_data = response.read().decode("utf-8")
            return json.loads(resp_data)
    except urllib.error.HTTPError as e:
        try:
            err_content = e.read().decode("utf-8")
            log(f"HTTP Error {e.code}: {err_content}")
            return json.loads(err_content)
        except Exception:
            return {"detail": f"HTTP Error {e.code}: {e.reason}"}
    except Exception as e:
        log(f"Connection Error: {e}")
        return {
            "detail": (
                f"Không thể kết nối tới Chatterbox API tại '{API_URL}'. "
                "Vui lòng đảm bảo máy chủ API đang chạy (khởi động bằng lệnh './run_chatterbox_api.sh')."
            )
        }


def encode_multipart_formdata(files: dict[str, tuple[str, bytes]], fields: dict[str, str] | None = None) -> tuple[bytes, str]:
    """Encode fields and files as multipart/form-data for uploads without external library."""
    boundary = "----ChatterboxMCPBoundary" + os.urandom(16).hex()
    body = []

    if fields:
        for name, value in fields.items():
            if value is not None:
                body.append(f"--{boundary}".encode("utf-8"))
                body.append(f'Content-Disposition: form-data; name="{name}"'.encode("utf-8"))
                body.append(b"")
                body.append(str(value).encode("utf-8"))

    for name, (filename, content) in files.items():
        if content is not None:
            body.append(f"--{boundary}".encode("utf-8"))
            body.append(f'Content-Disposition: form-data; name="{name}"; filename="{filename}"'.encode("utf-8"))
            mime_type = "audio/wav" if filename.lower().endswith(".wav") else "application/octet-stream"
            body.append(f"Content-Type: {mime_type}".encode("utf-8"))
            body.append(b"")
            body.append(content)

    body.append(f"--{boundary}--".encode("utf-8"))
    body.append(b"")

    payload = b"\r\n".join(body)
    content_type = f"multipart/form-data; boundary={boundary}"
    return payload, content_type


def execute_tool(name: str, args: dict) -> dict:
    """Execute target MCP tool and return results in standard MCP content format."""
    try:
        # 1. Check voice tools
        voice_result = handle_voice_tool(
            name=name,
            args=args,
            request_fn=make_api_request,
            api_url=API_URL,
            output_dir=DEFAULT_MCP_OUTPUT_DIR,
            log_fn=log,
            encode_multipart_fn=encode_multipart_formdata,
        )
        if voice_result is not None:
            return voice_result

        # 2. Check voice project tools
        voice_project_result = handle_voice_project_tool(
            name=name,
            args=args,
            request_fn=make_api_request,
            api_url=API_URL,
            log_fn=log,
        )
        if voice_project_result is not None:
            return voice_project_result

        # 3. Check project tools
        project_result = handle_project_tool(
            name=name,
            args=args,
            request_fn=make_api_request,
            api_url=API_URL,
            log_fn=log,
        )
        if project_result is not None:
            return project_result

        # 4. Phase 17 & 21 Runtime and Validation tools
        if name == "chatterbox_voice_runtime_capabilities":
            return handle_runtime_capabilities(args, request_fn=make_api_request)
        if name == "chatterbox_voice_runtime_preflight":
            return handle_runtime_preflight(args, request_fn=make_api_request)
        if name == "chatterbox_voice_validate_runtime":
            return handle_validate_runtime(args, request_fn=make_api_request)
        if name == "chatterbox_voice_validation_status":
            return handle_validation_status(args, request_fn=make_api_request)
        if name == "chatterbox_voice_validation_report":
            return handle_validation_report(args, request_fn=make_api_request)
        if name == "chatterbox_voice_validation_cancel":
            return handle_validation_cancel(args, request_fn=make_api_request)

        # 5. Phase 18 Asset Library tools
        asset_result = handle_asset_tool(
            name=name,
            args=args,
            request_fn=make_api_request,
            api_url=API_URL,
            log_fn=log,
        )
        if asset_result is not None:
            return asset_result

        # 6. Phase 19 Series tools
        if name == "chatterbox_voice_series_create":
            return handle_series_create(args, request_fn=make_api_request)
        if name == "chatterbox_voice_series_get":
            return handle_series_get(args, request_fn=make_api_request)
        if name == "chatterbox_voice_series_add_episode":
            return handle_series_add_episode(args, request_fn=make_api_request)
        if name == "chatterbox_voice_series_produce":
            return handle_series_produce(args, request_fn=make_api_request)
        if name == "chatterbox_voice_series_status":
            return handle_series_status(args, request_fn=make_api_request)
        if name == "chatterbox_voice_series_review_queue":
            return handle_series_review_queue(args, request_fn=make_api_request)
        if name == "chatterbox_voice_series_cancel":
            return handle_series_cancel(args, request_fn=make_api_request)

        # 7. Phase 20 Health & Observability tools
        if name == "chatterbox_voice_health":
            return handle_voice_health(args, request_fn=make_api_request)
        if name == "chatterbox_voice_events":
            return handle_voice_events(args, request_fn=make_api_request)
        if name == "chatterbox_voice_diagnostics":
            return handle_voice_diagnostics(args, request_fn=make_api_request)
        if name == "chatterbox_voice_series_health":
            return handle_voice_series_health(args, request_fn=make_api_request)
        if name == "chatterbox_voice_series_events":
            return handle_voice_series_events(args, request_fn=make_api_request)

        return {"content": [{"type": "text", "text": f"Error: Tool '{name}' not found."}], "isError": True}
    except Exception as e:
        log(f"Exception during tool execution: {e}")
        return {"content": [{"type": "text", "text": f"Internal MCP Error: {e}"}], "isError": True}


def send_response(response: dict) -> None:
    """Send JSON-RPC response to stdout."""
    response_str = json.dumps(response, ensure_ascii=False)
    rpc_stdout.write(response_str + "\n")
    rpc_stdout.flush()


def main() -> None:
    """Stdio-based JSON-RPC server loop."""
    log("Chatterbox MCP Server started and listening on stdin...")
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue

            request = json.loads(line)
            if not isinstance(request, dict):
                continue

            req_id = request.get("id")
            method = request.get("method")
            params = request.get("params", {})

            if method == "initialize":
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {
                            "tools": {},
                        },
                        "serverInfo": {
                            "name": "chatterbox-mcp",
                            "version": "1.4.0",
                        },
                    },
                }
                send_response(response)

            elif method == "notifications/initialized":
                pass

            elif method == "tools/list":
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "tools": get_tools_list(),
                    },
                }
                send_response(response)

            elif method == "tools/call":
                tool_name = params.get("name")
                tool_args = params.get("arguments", {})
                result = execute_tool(tool_name, tool_args)
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": result,
                }
                send_response(response)

            else:
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method '{method}' not found",
                    },
                }
                send_response(response)

        except json.JSONDecodeError:
            pass
        except Exception as e:
            log(f"Unhandled server loop exception: {e}")


if __name__ == "__main__":
    main()
