"""Project Planning & Orchestration MCP tool handlers."""

from __future__ import annotations

import json
from typing import Any, Callable


def handle_prepare_project(args: dict, request_fn: Callable, api_url: str, **kwargs) -> dict:
    topic = args.get("topic")
    initial_reqs = args.get("initial_requirements")
    auto_defaults = bool(args.get("auto_defaults", False))

    payload = {
        "topic": topic,
        "initial_requirements": initial_reqs,
        "auto_defaults": auto_defaults,
    }
    res = request_fn("/api/v1/projects/prepare", method="POST", data=payload)
    if "detail" in res:
        return {"content": [{"type": "text", "text": f"Error: {res['detail']}"}], "isError": True}

    proj_id = res.get("project_id")
    p_status = res.get("status", "unknown")
    questions = res.get("questions", [])
    summary = res.get("summary", "")

    lines = [
        f"### 🎯 Khởi tạo dự án âm thanh: `{proj_id}`",
        f"* **Trạng thái**: `{p_status.upper()}`",
        "\n" + summary,
    ]

    if questions:
        lines.append("\n#### ❓ Danh sách câu hỏi cần thu thập bổ sung:")
        for idx, q in enumerate(questions, 1):
            req_mark = "*(Bắt buộc)*" if q.get("required") else "*(Khuyến nghị)*"
            opts = ", ".join(q.get("options", []))
            lines.append(f"{idx}. **{q.get('question')}** {req_mark}")
            if opts:
                lines.append(f"   - *Gợi ý lựa chọn*: {opts}")
        lines.append(f"\n💡 *Sử dụng `chatterbox_answer_project_questions` với `project_id='{proj_id}'` để gửi câu trả lời.*")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def handle_answer_project_questions(args: dict, request_fn: Callable, api_url: str, **kwargs) -> dict:
    proj_id = args.get("project_id")
    answers = args.get("answers")
    auto_defaults = bool(args.get("auto_defaults", False))

    if not proj_id:
        return {"content": [{"type": "text", "text": "Error: 'project_id' is required."}], "isError": True}

    payload = {
        "answers": answers,
        "auto_defaults": auto_defaults,
    }
    res = request_fn(f"/api/v1/projects/{proj_id}/answer", method="POST", data=payload)
    if "detail" in res:
        return {"content": [{"type": "text", "text": f"Error: {res['detail']}"}], "isError": True}

    p_status = res.get("status", "unknown")
    summary = res.get("summary", "")
    questions = res.get("questions", [])

    lines = [
        f"### 📝 Cập nhật yêu cầu dự án: `{proj_id}`",
        f"* **Trạng thái mới**: `{p_status.upper()}`",
        "\n" + summary,
    ]

    if questions:
        lines.append("\n#### ⚠️ Vẫn còn thông tin cần làm rõ:")
        for idx, q in enumerate(questions, 1):
            req_mark = "*(Bắt buộc)*" if q.get("required") else "*(Khuyến nghị)*"
            opts = ", ".join(q.get("options", []))
            lines.append(f"{idx}. **{q.get('question')}** {req_mark}")
            if opts:
                lines.append(f"   - *Gợi ý*: {opts}")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def handle_confirm_requirements(args: dict, request_fn: Callable, api_url: str, **kwargs) -> dict:
    proj_id = args.get("project_id")
    confirmed = bool(args.get("confirmed", True))

    if not proj_id:
        return {"content": [{"type": "text", "text": "Error: 'project_id' is required."}], "isError": True}

    payload = {"confirmed": confirmed}
    res = request_fn(f"/api/v1/projects/{proj_id}/confirm-requirements", method="POST", data=payload)
    if "detail" in res:
        return {"content": [{"type": "text", "text": f"Error: {res['detail']}"}], "isError": True}

    msg = res.get("message", "")
    p_status = res.get("status", "")
    summary = res.get("summary", "")

    return {
        "content": [
            {
                "type": "text",
                "text": (
                    f"Gate 1 Confirmed: {msg}\n"
                    f"* **Project ID**: `{proj_id}`\n"
                    f"* **Trạng thái**: `{p_status.upper()}`\n\n"
                    f"{summary}"
                ),
            }
        ]
    }


def handle_generate_script(args: dict, request_fn: Callable, api_url: str, **kwargs) -> dict:
    proj_id = args.get("project_id")
    custom_prompt = args.get("custom_prompt")
    num_scenes = args.get("num_scenes")

    if not proj_id:
        return {"content": [{"type": "text", "text": "Error: 'project_id' is required."}], "isError": True}

    payload = {
        "custom_prompt": custom_prompt,
        "num_scenes": num_scenes,
    }
    res = request_fn(f"/api/v1/projects/{proj_id}/generate-script", method="POST", data=payload)
    if "detail" in res:
        return {"content": [{"type": "text", "text": f"Error: {res['detail']}"}], "isError": True}

    p_status = res.get("status", "")
    summary = res.get("summary", "")
    return {
        "content": [
            {
                "type": "text",
                "text": f"📜 Generated English script for `{proj_id}` (Status: `{p_status.upper()}`):\n\n{summary}",
            }
        ]
    }


def handle_confirm_script(args: dict, request_fn: Callable, api_url: str, **kwargs) -> dict:
    proj_id = args.get("project_id")
    confirmed = bool(args.get("confirmed", True))
    script_text = args.get("script_text")

    if not proj_id:
        return {"content": [{"type": "text", "text": "Error: 'project_id' is required."}], "isError": True}

    payload = {
        "confirmed": confirmed,
        "script_text": script_text,
    }
    res = request_fn(f"/api/v1/projects/{proj_id}/confirm-script", method="POST", data=payload)
    if "detail" in res:
        return {"content": [{"type": "text", "text": f"Error: {res['detail']}"}], "isError": True}

    msg = res.get("message", "")
    p_status = res.get("status", "")
    summary = res.get("summary", "")

    return {
        "content": [
            {
                "type": "text",
                "text": (
                    f"Gate 2: {msg}\n"
                    f"* **Project ID**: `{proj_id}`\n"
                    f"* **Trạng thái**: `{p_status.upper()}`\n\n"
                    f"{summary}"
                ),
            }
        ]
    }


def handle_get_project(args: dict, request_fn: Callable, api_url: str, **kwargs) -> dict:
    proj_id = args.get("project_id")
    if not proj_id:
        return {"content": [{"type": "text", "text": "Error: 'project_id' is required."}], "isError": True}

    res = request_fn(f"/api/v1/projects/{proj_id}")
    if "detail" in res:
        return {"content": [{"type": "text", "text": f"Error: {res['detail']}"}], "isError": True}

    summary = res.get("summary", "")
    json_dump = json.dumps(res, ensure_ascii=False, indent=2)
    return {
        "content": [
            {
                "type": "text",
                "text": f"{summary}\n\n#### 📦 Raw Project Data:\n```json\n{json_dump}\n```",
            }
        ]
    }


def handle_list_projects(args: dict, request_fn: Callable, api_url: str, **kwargs) -> dict:
    res = request_fn("/api/v1/projects")
    if "detail" in res:
        return {"content": [{"type": "text", "text": f"Error: {res['detail']}"}], "isError": True}

    projects = res.get("projects", [])
    lines = [f"### 📋 Audio Projects List ({len(projects)} projects)\n"]
    if not projects:
        lines.append("*(No projects created yet)*")
    for p in projects:
        lines.append(f"* **`{p.get('id')}`** — **{p.get('topic')}** (Status: `{p.get('status')}` • Format: `{p.get('requirements', {}).get('content_format', 'N/A')}`)")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def handle_confirm_project(args: dict, request_fn: Callable, api_url: str, **kwargs) -> dict:
    proj_id = args.get("project_id")
    confirmed = bool(args.get("confirmed", True))

    if not proj_id:
        return {"content": [{"type": "text", "text": "Error: 'project_id' is required."}], "isError": True}

    payload = {"confirmed": confirmed}
    res = request_fn(f"/api/v1/projects/{proj_id}/confirm", method="POST", data=payload)
    if "detail" in res:
        return {"content": [{"type": "text", "text": f"Error: {res['detail']}"}], "isError": True}

    msg = res.get("message", "")
    p_status = res.get("status", "")
    summary = res.get("summary", "")

    return {
        "content": [
            {
                "type": "text",
                "text": (
                    f"{msg}\n"
                    f"* **Project ID**: `{proj_id}`\n"
                    f"* **Trạng thái**: `{p_status.upper()}`\n\n"
                    f"{summary}"
                ),
            }
        ]
    }


def handle_render_project(args: dict, request_fn: Callable, api_url: str, **kwargs) -> dict:
    proj_id = args.get("project_id")
    script_text = args.get("script_text")
    character_id = args.get("character_id")
    quality_preset = args.get("quality_preset")

    if not proj_id:
        return {"content": [{"type": "text", "text": "Error: 'project_id' is required."}], "isError": True}

    payload = {
        "script_text": script_text,
        "character_id": character_id,
        "quality_preset": quality_preset,
    }
    res = request_fn(f"/api/v1/projects/{proj_id}/render", method="POST", data=payload)
    if "detail" in res:
        return {"content": [{"type": "text", "text": f"Error: {res['detail']}"}], "isError": True}

    job_id = res.get("job_id") or res.get("final_job_id")
    p_status = res.get("status", "")
    msg = res.get("message", "")
    script = res.get("script_text", "")
    seg_count = res.get("segment_count", 0)

    output_text = (
        f"🚀 {msg}\n"
        f"* **Project ID**: `{proj_id}`\n"
        f"* **Segments**: `{seg_count}`\n"
        f"* **Job ID**: `{job_id}`\n"
        f"* **Trạng thái dự án**: `{p_status.upper()}`\n\n"
        f"📜 **Script**:\n"
        f"> {script}\n\n"
        f"Sử dụng công cụ `chatterbox_get_job_status` với `job_id='{job_id}'` để theo dõi tiến độ tổng hợp âm thanh."
    )
    return {"content": [{"type": "text", "text": output_text}]}


def handle_get_events(args: dict, request_fn: Callable, api_url: str, **kwargs) -> dict:
    after_id = int(args.get("after_event_id", 0))
    wait_s = int(args.get("wait_seconds", 0))
    proj_id = args.get("project_id")
    params = f"?after_id={after_id}&wait={wait_s}"
    if proj_id:
        params += f"&project_id={proj_id}"
    res = request_fn(f"/api/v1/events{params}")
    if "detail" in res:
        return {"content": [{"type": "text", "text": f"Error: {res['detail']}"}], "isError": True}

    events = res.get("events", [])
    last_id = res.get("last_event_id", after_id)
    md = [f"### 📡 Chatterbox Event Stream ({len(events)} new events, last_event_id: `{last_id}`)\n"]
    if not events:
        md.append("*(No new events received)*")
    else:
        for ev in events:
            ev_id = ev.get("id")
            ev_type = ev.get("type", "unknown")
            ev_proj = ev.get("project_id") or "global"
            ev_stat = ev.get("status") or "-"
            ev_prog = f"({ev.get('progress')}%)" if ev.get("progress") is not None else ""
            md.append(f"- `#{ev_id}` **`{ev_type}`** [Project: `{ev_proj}`] Status: `{ev_stat}` {ev_prog}")
            if ev.get("data"):
                md.append(f"  ```json\n  {json.dumps(ev['data'], ensure_ascii=False)}\n  ```")
    return {"content": [{"type": "text", "text": "\n".join(md)}]}


PROJECT_HANDLERS = {
    "chatterbox_prepare_project": handle_prepare_project,
    "chatterbox_answer_project_questions": handle_answer_project_questions,
    "chatterbox_confirm_requirements": handle_confirm_requirements,
    "chatterbox_generate_script": handle_generate_script,
    "chatterbox_confirm_script": handle_confirm_script,
    "chatterbox_get_project": handle_get_project,
    "chatterbox_list_projects": handle_list_projects,
    "chatterbox_confirm_project": handle_confirm_project,
    "chatterbox_render_project": handle_render_project,
    "chatterbox_get_events": handle_get_events,
}


def handle_project_tool(
    name: str,
    args: dict,
    request_fn: Callable,
    api_url: str,
    log_fn: Callable,
) -> dict | None:
    """Dispatch project tool if supported, or return None."""
    handler = PROJECT_HANDLERS.get(name)
    if not handler:
        return None
    return handler(
        args=args,
        request_fn=request_fn,
        api_url=api_url,
        log_fn=log_fn,
    )
