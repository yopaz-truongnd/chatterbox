"""MCP Asset Library Tools Adapter (Phase 18).

Provides 5 coarse-grained MCP tools for AI agents to interact with the
Intelligent Asset Library via the REST API. Thin adapter — no business logic.
"""

from __future__ import annotations

import json
from typing import Any, Callable


def _success(data: Any) -> dict:
    return {
        "content": [{"type": "text", "text": json.dumps(data, indent=2, ensure_ascii=False)}],
        "isError": False,
    }


def _error(msg: str, code: str = "ERROR") -> dict:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps({"error": {"code": code, "message": msg}}, indent=2),
            }
        ],
        "isError": True,
    }


def _req(request_fn: Callable | None, method: str, path: str, data: dict | None = None) -> dict:
    """Execute REST request via request_fn or in-process TestClient fallback."""
    if request_fn is not None:
        return request_fn(path, method=method, data=data)

    try:
        import os

        from fastapi.testclient import TestClient
        import api_app

        client = TestClient(api_app.app)
        api_key = os.getenv("CHATTERBOX_API_KEY")
        headers = {"X-API-Key": api_key} if api_key else {}

        if method == "GET":
            resp = client.get(path, headers=headers)
        else:
            resp = client.post(path, json=data or {}, headers=headers)

        try:
            return resp.json()
        except Exception:
            return {"detail": resp.text, "status_code": resp.status_code}
    except Exception as exc:
        return {"detail": f"Failed to execute local request: {exc}"}


def _handle(res: Any) -> dict:
    # If the response is a list, it's a valid payload (e.g., asset list)
    if isinstance(res, list):
        return _success(res)
    if not isinstance(res, dict):
        return _success(res)
    if "detail" in res and not isinstance(res.get("detail"), list):
        if res.get("status_code", 200) >= 400:
            return _error(str(res["detail"]))
    if res.get("error"):
        err = res["error"]
        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        return _error(msg)
    return _success(res)


def handle_asset_tool(
    name: str,
    args: dict[str, Any],
    request_fn: Callable | None = None,
    api_url: str | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> dict | None:
    """Dispatch asset library MCP tool calls to the REST API."""

    if not name.startswith("chatterbox_voice_asset"):
        return None

    # ------------------------------------------------------------------ #
    # 1. List assets                                                       #
    # ------------------------------------------------------------------ #
    if name == "chatterbox_voice_assets":
        category = args.get("category")
        path = "/api/v1/voice-assets"
        if category:
            path += f"?category={category}"
        return _handle(_req(request_fn, "GET", path))

    # ------------------------------------------------------------------ #
    # 2. Register a single file                                            #
    # ------------------------------------------------------------------ #
    if name == "chatterbox_voice_asset_register":
        file_path = (args.get("file_path") or "").strip()
        category = (args.get("category") or "").strip()
        if not file_path:
            return _error("'file_path' is required.", code="VALIDATION_ERROR")
        if not category:
            return _error("'category' is required.", code="VALIDATION_ERROR")
        payload = {
            "file_path": file_path,
            "category": category,
            "intents": args.get("intents", []),
            "keywords": args.get("keywords", []),
            "mood": args.get("mood"),
            "environment": args.get("environment"),
            "energy": args.get("energy"),
            "loopable": args.get("loopable", False),
            "license": args.get("license"),
            "source_url": args.get("source_url"),
            "attribution": args.get("attribution"),
        }
        return _handle(_req(request_fn, "POST", "/api/v1/voice-assets/register", payload))

    # ------------------------------------------------------------------ #
    # 3. Scan a directory                                                  #
    # ------------------------------------------------------------------ #
    if name == "chatterbox_voice_asset_scan":
        directory_path = (args.get("directory_path") or "").strip()
        category = (args.get("category") or "").strip()
        if not directory_path:
            return _error("'directory_path' is required.", code="VALIDATION_ERROR")
        if not category:
            return _error("'category' is required.", code="VALIDATION_ERROR")
        payload = {"directory_path": directory_path, "category": category}
        return _handle(_req(request_fn, "POST", "/api/v1/voice-assets/scan", payload))

    # ------------------------------------------------------------------ #
    # 4. Match assets                                                      #
    # ------------------------------------------------------------------ #
    if name == "chatterbox_voice_asset_match":
        intents = args.get("intents") or []
        category = (args.get("category") or "").strip()
        if not intents:
            return _error("'intents' must be a non-empty list.", code="VALIDATION_ERROR")
        if not category:
            return _error("'category' is required.", code="VALIDATION_ERROR")
        payload = {
            "intents": intents,
            "category": category,
            "mood": args.get("mood"),
            "environment": args.get("environment"),
            "duration_ms": args.get("duration_ms"),
            "loopable": args.get("loopable"),
            "story_context": args.get("story_context"),
            "top_k": args.get("top_k", 5),
        }
        return _handle(_req(request_fn, "POST", "/api/v1/voice-assets/match", payload))

    # ------------------------------------------------------------------ #
    # 5. Preview asset                                                     #
    # ------------------------------------------------------------------ #
    if name == "chatterbox_voice_asset_preview":
        asset_id = (args.get("asset_id") or "").strip()
        if not asset_id:
            return _error("'asset_id' is required.", code="VALIDATION_ERROR")
        # Preview returns binary WAV — return URL hint for agent use
        return _success(
            {
                "asset_id": asset_id,
                "preview_url": f"/api/v1/voice-assets/{asset_id}/preview",
                "note": "Fetch the preview_url to receive a 200ms WAV audio clip.",
            }
        )

    return None
