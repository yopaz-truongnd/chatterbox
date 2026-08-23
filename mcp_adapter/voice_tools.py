"""Voice & Audio MCP tool handlers (TTS, Character, Download, Voice Conversion, Voice Critic)."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable


def handle_list_characters(args: dict, request_fn: Callable, api_url: str, **kwargs) -> dict:
    res = request_fn("/api/v1/characters")
    if "detail" in res:
        return {"content": [{"type": "text", "text": f"Error: {res['detail']}"}], "isError": True}

    chars = res.get("characters", []) if isinstance(res, dict) else res
    lines = ["### Chatterbox Characters List\n"]
    if not chars:
        lines.append("*(Chưa có nhân vật nào trong cơ sở dữ liệu)*")
    for char in chars:
        if not isinstance(char, dict):
            continue
        cid = char.get("id")
        cname = char.get("name", "Unknown")
        clang = char.get("language", "en")
        cdesc = char.get("description", "")
        has_audio = "Yes" if char.get("has_reference_audio") else "No"
        is_default = " (Default)" if char.get("is_default") else ""
        lines.append(f"* **{cname}**{is_default} - ID: `{cid}` | Lang: `{clang}` | Reference Audio: {has_audio}")
        if cdesc:
            lines.append(f"  *Description: {cdesc}*")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def handle_generate_tts(args: dict, request_fn: Callable, api_url: str, **kwargs) -> dict:
    text = args.get("text")
    character_id = args.get("character_id")
    preset = args.get("preset", "balanced")
    model = args.get("model")
    language_id = args.get("language_id")

    form_fields = {"text": text, "character_id": character_id}

    if model == "multilingual":
        endpoint = "/api/v1/tts/multilingual"
        form_fields["language_id"] = language_id or "en"
    elif model == "standard":
        endpoint = "/api/v1/tts/standard"
    elif model in ("nano", "turbo"):
        endpoint = f"/api/v1/tts/{model}"
        form_fields["quality_preset"] = preset
    else:
        endpoint = "/api/v1/tts"
        form_fields["quality_preset"] = preset

    encoded_data = urllib.parse.urlencode({k: v for k, v in form_fields.items() if v is not None}).encode("utf-8")
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    res = request_fn(endpoint, method="POST", data=encoded_data, headers=headers)
    if "detail" in res:
        return {"content": [{"type": "text", "text": f"Error: {res['detail']}"}], "isError": True}

    job_id = res.get("id")
    status = res.get("status")

    # Synchronize MCP voice generation task to Projects Studio
    try:
        from utils.platform_tools import get_default_data_dir
        from datetime import datetime, timezone
        
        data_dir = get_default_data_dir()
        proj_dir = data_dir / "projects"
        proj_dir.mkdir(parents=True, exist_ok=True)
        
        proj_id = f"proj_mcp_{job_id[:12]}"
        created_iso = datetime.now(timezone.utc).isoformat()
        
        project_data = {
            "id": proj_id,
            "topic": f"MCP TTS: {text[:45]}...",
            "status": "rendering" if status in ("queued", "processing") else status or "rendering",
            "requirements": {
                "content_format": "mcp_tts",
                "target_duration_seconds": 30,
                "audience": "general",
                "tone": "expressive",
                "sfx_level": "none",
                "output_formats": ["wav"],
                "character_id": character_id,
            },
            "missing_required": [],
            "missing_recommended": [],
            "pronunciation_dict": {},
            "pronunciation_candidates": [],
            "outline": [
                {
                    "scene_idx": 1,
                    "title": "MCP Generated Audio",
                    "description": "Standalone voice synthesized through Model Context Protocol (MCP)",
                }
            ],
            "script": {
                "full_text": text,
                "scenes": [
                    {
                        "scene_idx": 1,
                        "title": "MCP Generated Audio",
                        "paragraphs": [
                            {
                                "character_id": character_id,
                                "text": text,
                            }
                        ]
                    }
                ]
            },
            "voice_plan": {
                "default_model": model or "turbo",
                "quality_preset": preset or "balanced",
                "character_id": character_id,
            },
            "segments": [
                {
                    "idx": 0,
                    "text": text,
                    "character_id": character_id,
                    "status": "completed" if status == "completed" else "failed",
                    "audio_url": f"/api/v1/jobs/{job_id}/audio" if status == "completed" else None,
                }
            ],
            "jobs": [job_id],
            "final_job_id": job_id,
            "audio_url": f"/api/v1/jobs/{job_id}/audio" if status == "completed" else None,
            "srt_url": f"/api/v1/jobs/{job_id}/srt" if status == "completed" else None,
            "created_at": created_iso,
            "updated_at": created_iso,
        }
        
        proj_file = proj_dir / f"{proj_id}.json"
        proj_file.write_text(json.dumps(project_data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    return {
        "content": [
            {
                "type": "text",
                "text": (
                    f"✅ Tác vụ TTS đã được khởi tạo thành công!\n"
                    f"* **Job ID**: `{job_id}`\n"
                    f"* **Trạng thái**: `{status}`\n"
                    f"Sử dụng công cụ `chatterbox_get_job_status` với `job_id='{job_id}'` để kiểm tra tiến trình."
                ),
            }
        ]
    }


def handle_get_job_status(args: dict, request_fn: Callable, api_url: str, **kwargs) -> dict:
    job_id = args.get("job_id")
    res = request_fn(f"/api/v1/jobs/{job_id}")
    if "detail" in res:
        return {"content": [{"type": "text", "text": f"Error: {res['detail']}"}], "isError": True}

    status = res.get("status", "unknown")
    phase = res.get("phase", "")
    progress = res.get("progress_percent", 0)
    err = res.get("error")
    audio_url = res.get("audio_url")
    benchmark = res.get("benchmark", {})

    output_msg = [
        f"### Trạng thái tác vụ: `{status.upper()}`",
        f"* **Job ID**: `{job_id}`",
        f"* **Giai đoạn**: `{phase}`",
        f"* **Tiến độ**: `{progress}%`",
    ]

    if err:
        output_msg.append(f"* **Lỗi**: `{err}`")

    if status in ("completed", "completed_partial"):
        full_audio_url = f"{api_url.rstrip('/')}/{audio_url.lstrip('/')}" if audio_url else None
        output_msg.append(f"* **Đường dẫn Audio**: {full_audio_url}")
        if benchmark:
            duration = benchmark.get("audio_duration_seconds", 0.0)
            rtf = benchmark.get("realtime_factor", 0.0)
            faster = benchmark.get("faster_than_realtime", 0.0)
            output_msg.append(f"* **Thời lượng Audio**: `{round(duration, 2)}s`")
            output_msg.append(f"* **Realtime Factor (RTF)**: `{rtf}` ({faster}x realtime)")

    return {"content": [{"type": "text", "text": "\n".join(output_msg)}]}


def handle_download_audio(
    args: dict,
    request_fn: Callable,
    api_url: str,
    output_dir: Path,
    log_fn: Callable,
    **kwargs,
) -> dict:
    job_id = args.get("job_id")
    if not job_id:
        return {"content": [{"type": "text", "text": "Error: 'job_id' is required."}], "isError": True}

    dest_path = args.get("destination_path")
    overwrite = bool(args.get("overwrite", False))

    output_dir.mkdir(parents=True, exist_ok=True)
    if not dest_path:
        dest = (output_dir / f"chatterbox_{job_id}.wav").resolve()
    else:
        candidate = Path(dest_path)
        if candidate.is_absolute():
            dest = candidate.resolve()
        else:
            dest = (output_dir / candidate).resolve()

        # Strict directory confinement: target must be inside outputs/mcp/
        try:
            dest.relative_to(output_dir.resolve())
        except ValueError:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Error: Security restriction - destination_path must reside within '{output_dir}'. "
                            f"Attempted path: '{dest}'"
                        ),
                    }
                ],
                "isError": True,
            }

    # Overwrite protection
    if dest.exists() and not overwrite:
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Error: File already exists at '{dest}'. Pass 'overwrite=True' to allow overwriting.",
                }
            ],
            "isError": True,
        }

    dest.parent.mkdir(parents=True, exist_ok=True)
    part_file = dest.with_suffix(dest.suffix + ".part")

    url = f"{api_url.rstrip('/')}/api/v1/jobs/{job_id}/audio"
    log_fn(f"Downloading audio from {url} to {dest} via {part_file}")

    try:
        req = urllib.request.Request(url, headers={"Accept": "audio/wav"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status != 200:
                return {"content": [{"type": "text", "text": f"Error downloading audio: HTTP {resp.status}"}], "isError": True}
            data = resp.read()

        # Basic WAV validation
        if len(data) < 44 or not (data.startswith(b"RIFF") and b"WAVE" in data[:16]):
            return {"content": [{"type": "text", "text": "Error: Downloaded payload is not a valid WAV audio file."}], "isError": True}

        # Secondary overwrite check before atomic commit
        if not overwrite and dest.exists():
            if part_file.exists():
                part_file.unlink(missing_ok=True)
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Error: File already exists at '{dest}'. Pass 'overwrite=True' to allow overwriting.",
                    }
                ],
                "isError": True,
            }

        # Atomic write
        part_file.write_bytes(data)
        part_file.replace(dest)

        return {
            "content": [
                {
                    "type": "text",
                    "text": f"✅ Đã tải và lưu thành công file âm thanh ({len(data)} bytes) tại: `{dest}`",
                }
            ]
        }
    except Exception as exc:
        if part_file.exists():
            part_file.unlink(missing_ok=True)
        return {"content": [{"type": "text", "text": f"Error downloading audio: {exc}"}], "isError": True}


def handle_voice_conversion(
    args: dict,
    request_fn: Callable,
    api_url: str,
    log_fn: Callable,
    encode_multipart_fn: Callable,
    **kwargs,
) -> dict:
    source_path = args.get("source_audio_path")
    character_id = args.get("character_id")
    target_path = args.get("target_audio_path")

    if not source_path or not os.path.isfile(source_path):
        return {"content": [{"type": "text", "text": f"Error: Source audio file not found at path: {source_path}"}], "isError": True}

    with open(source_path, "rb") as f:
        source_bytes = f.read()

    target_bytes = None
    target_filename = "target.wav"

    if target_path:
        if not os.path.isfile(target_path):
            return {"content": [{"type": "text", "text": f"Error: Target custom audio file not found at path: {target_path}"}], "isError": True}
        with open(target_path, "rb") as f:
            target_bytes = f.read()
        target_filename = os.path.basename(target_path)
    elif character_id:
        char_info = request_fn(f"/api/v1/characters/{character_id}")
        if "detail" in char_info:
            return {"content": [{"type": "text", "text": f"Error: Character not found: {char_info['detail']}"}], "isError": True}

        ref_url = char_info.get("reference_audio_url")
        if not ref_url:
            return {"content": [{"type": "text", "text": f"Error: Character `{character_id}` does not have any reference audio"}], "isError": True}

        full_ref_url = f"{api_url.rstrip('/')}/{ref_url.lstrip('/')}"
        log_fn(f"Downloading character voice reference from {full_ref_url}")
        try:
            with urllib.request.urlopen(full_ref_url, timeout=15) as resp:
                target_bytes = resp.read()
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Error loading character reference: {e}"}], "isError": True}
    else:
        return {"content": [{"type": "text", "text": "Error: You must specify either character_id or target_audio_path"}], "isError": True}

    files = {
        "source_audio": (os.path.basename(source_path), source_bytes),
    }
    if target_bytes:
        files["target_voice"] = (target_filename, target_bytes)

    payload, content_type = encode_multipart_fn(files)
    headers = {"Content-Type": content_type}

    res = request_fn("/api/v1/voice-conversion", method="POST", data=payload, headers=headers)
    if "detail" in res:
        return {"content": [{"type": "text", "text": f"Error: {res['detail']}"}], "isError": True}

    job_id = res.get("id")
    status = res.get("status")

    # Synchronize MCP Voice Conversion task to Projects Studio
    try:
        from utils.platform_tools import get_default_data_dir
        from datetime import datetime, timezone
        
        data_dir = get_default_data_dir()
        proj_dir = data_dir / "projects"
        proj_dir.mkdir(parents=True, exist_ok=True)
        
        proj_id = f"proj_mcp_{job_id[:12]}"
        created_iso = datetime.now(timezone.utc).isoformat()
        
        project_data = {
            "id": proj_id,
            "topic": f"MCP VC: {os.path.basename(source_path)}",
            "status": "rendering" if status in ("queued", "processing") else status or "rendering",
            "requirements": {
                "content_format": "mcp_vc",
                "target_duration_seconds": 30,
                "audience": "general",
                "tone": "expressive",
                "sfx_level": "none",
                "output_formats": ["wav"],
                "character_id": character_id,
            },
            "missing_required": [],
            "missing_recommended": [],
            "pronunciation_dict": {},
            "pronunciation_candidates": [],
            "outline": [
                {
                    "scene_idx": 1,
                    "title": "MCP Voice Conversion",
                    "description": f"Voice conversion from source file {os.path.basename(source_path)} to character {character_id}",
                }
            ],
            "script": {
                "full_text": f"[Source Audio: {os.path.basename(source_path)}] -> [Target Character ID: {character_id}]",
                "scenes": [
                    {
                        "scene_idx": 1,
                        "title": "MCP Voice Conversion",
                        "paragraphs": [
                            {
                                "character_id": character_id,
                                "text": f"Voice converted from {os.path.basename(source_path)}",
                            }
                        ]
                    }
                ]
            },
            "voice_plan": {
                "default_model": "voice-conversion",
                "quality_preset": "balanced",
                "character_id": character_id,
            },
            "segments": [
                {
                    "idx": 0,
                    "text": f"Voice converted from {os.path.basename(source_path)}",
                    "character_id": character_id,
                    "status": "completed" if status == "completed" else "failed",
                    "audio_url": f"/api/v1/jobs/{job_id}/audio" if status == "completed" else None,
                }
            ],
            "jobs": [job_id],
            "final_job_id": job_id,
            "audio_url": f"/api/v1/jobs/{job_id}/audio" if status == "completed" else None,
            "srt_url": f"/api/v1/jobs/{job_id}/srt" if status == "completed" else None,
            "created_at": created_iso,
            "updated_at": created_iso,
        }
        
        proj_file = proj_dir / f"{proj_id}.json"
        proj_file.write_text(json.dumps(project_data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    return {
        "content": [
            {
                "type": "text",
                "text": f"Voice conversion job submitted successfully!\n* **Job ID**: `{job_id}`\n* **Status**: `{status}`\nUse `chatterbox_get_job_status` tool to check progress.",
            }
        ]
    }


def handle_evaluate_voice(
    args: dict,
    request_fn: Callable,
    api_url: str,
    encode_multipart_fn: Callable,
    **kwargs,
) -> dict:
    audio_path = args.get("audio_path")
    job_id = args.get("job_id")
    reference_text = args.get("reference_text")
    coach_character_id = args.get("coach_character_id")

    files = {}
    fields = {}

    if job_id:
        fields["job_id"] = job_id
    elif audio_path:
        if not os.path.isfile(audio_path):
            return {"content": [{"type": "text", "text": f"Error: Audio file not found at path: {audio_path}"}], "isError": True}
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()
        files["audio_file"] = (os.path.basename(audio_path), audio_bytes)
    else:
        return {"content": [{"type": "text", "text": "Error: You must specify either audio_path or job_id."}], "isError": True}

    if reference_text:
        fields["reference_text"] = reference_text
    if coach_character_id:
        fields["coach_character_id"] = coach_character_id

    payload, content_type = encode_multipart_fn(files=files, fields=fields)
    headers = {"Content-Type": content_type}

    res = request_fn("/api/v1/voice-critic/evaluate", method="POST", data=payload, headers=headers, timeout=60.0)
    if "detail" in res:
        return {"content": [{"type": "text", "text": f"Error: {res['detail']}"}], "isError": True}

    report = res.get("markdown_report", "")
    evaluation = res.get("evaluation", {})
    feedback_job_id = res.get("feedback_job_id")
    feedback_audio_url = res.get("feedback_audio_url")

    full_audio_url = f"{api_url.rstrip('/')}/{feedback_audio_url.lstrip('/')}" if feedback_audio_url else None
    json_summary = json.dumps(evaluation, ensure_ascii=False, indent=2)

    output_msg = [
        report,
        "\n#### 📊 Structured Evaluation Summary:",
        f"```json\n{json_summary}\n```",
        "\n---",
        f"🔊 **AI Coach Audio Critique**: {full_audio_url}",
        f"*Feedback job ID: `{feedback_job_id}`*",
    ]

    return {"content": [{"type": "text", "text": "\n".join(output_msg)}]}


VOICE_HANDLERS = {
    "chatterbox_list_characters": handle_list_characters,
    "chatterbox_generate_tts": handle_generate_tts,
    "chatterbox_get_job_status": handle_get_job_status,
    "chatterbox_download_audio": handle_download_audio,
    "chatterbox_voice_conversion": handle_voice_conversion,
    "chatterbox_evaluate_voice": handle_evaluate_voice,
}


def handle_voice_tool(
    name: str,
    args: dict,
    request_fn: Callable,
    api_url: str,
    output_dir: Path,
    log_fn: Callable,
    encode_multipart_fn: Callable,
) -> dict | None:
    """Dispatch voice tool if supported, or return None."""
    handler = VOICE_HANDLERS.get(name)
    if not handler:
        return None
    return handler(
        args=args,
        request_fn=request_fn,
        api_url=api_url,
        output_dir=output_dir,
        log_fn=log_fn,
        encode_multipart_fn=encode_multipart_fn,
    )
