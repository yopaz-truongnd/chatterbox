"""
Chatterbox MCP Server - Model Context Protocol tool provider for local voice cloning.
Communicates with the local Chatterbox REST API server to expose speech synthesis and voice conversion.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
import urllib.error

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

API_URL = os.getenv("CHATTERBOX_API_URL", "http://127.0.0.1:8000")


def log(msg: str) -> None:
    """Log helper writing to stderr (standard for stdio MCP debug logs)."""
    sys.stderr.write(f"[Chatterbox MCP] {msg}\n")
    sys.stderr.flush()


def make_api_request(path: str, method: str = "GET", data: bytes | dict | None = None, headers: dict | None = None) -> dict:
    """Make HTTP request to local Chatterbox REST API."""
    url = f"{API_URL.rstrip('/')}/{path.lstrip('/')}"
    log(f"API Request: {method} {url}")

    req_headers = {"Accept": "application/json"}
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
        with urllib.request.urlopen(req, timeout=15) as response:
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
        return {"detail": f"Failed to connect to Chatterbox API at {API_URL}. Is the server running? Error: {e}"}


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


def get_tools_list() -> list[dict]:
    """Return tool schemas available on this MCP server."""
    return [
        {
            "name": "chatterbox_list_characters",
            "description": "List all available voices and characters stored in Chatterbox.",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "chatterbox_generate_tts",
            "description": "Generate synthesized speech (Text-to-Speech) using a specified character voice.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text to synthesize into speech.",
                    },
                    "character_id": {
                        "type": "string",
                        "description": "The unique ID of the character voice to use (e.g. 'char_123'). Optional.",
                    },
                    "preset": {
                        "type": "string",
                        "enum": ["fast", "balanced", "expressive"],
                        "description": "The quality/speed preset. Default is 'balanced'.",
                    },
                    "model": {
                        "type": "string",
                        "enum": ["nano", "turbo", "standard", "multilingual"],
                        "description": "Override default model type. Optional.",
                    },
                    "language_id": {
                        "type": "string",
                        "description": "Target language ID (e.g., 'en', 'vi', 'zh') for multilingual model. Optional.",
                    },
                },
                "required": ["text"],
            },
        },
        {
            "name": "chatterbox_get_job_status",
            "description": "Get the current status, progress, and output details of a voice generation or conversion job.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "The unique ID of the job.",
                    }
                },
                "required": ["job_id"],
            },
        },
        {
            "name": "chatterbox_voice_conversion",
            "description": "Perform voice conversion to transform the voice of a source audio file to match a target character or a custom target voice WAV.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source_audio_path": {
                        "type": "string",
                        "description": "Absolute filesystem path to the source audio file.",
                    },
                    "character_id": {
                        "type": "string",
                        "description": "The unique ID of the target character voice to copy. Optional.",
                    },
                    "target_audio_path": {
                        "type": "string",
                        "description": "Absolute path to a target custom voice WAV file to copy. Optional.",
                    },
                },
                "required": ["source_audio_path"],
            },
        },
        {
            "name": "chatterbox_evaluate_voice",
            "description": "Evaluate the quality of a voice reading (loudness, expressiveness, pace, pronunciation) and read back the critique using a specified coach character voice.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "audio_path": {
                        "type": "string",
                        "description": "Absolute path to the source audio file to evaluate. Optional (if job_id is provided).",
                    },
                    "job_id": {
                        "type": "string",
                        "description": "Unique ID of a completed TTS job to evaluate. Optional (if audio_path is provided).",
                    },
                    "reference_text": {
                        "type": "string",
                        "description": "The script text/script to check pronunciation against. Optional.",
                    },
                    "coach_character_id": {
                        "type": "string",
                        "description": "Character ID of the AI coach to read back the feedback. Optional.",
                    },
                },
            },
        },
    ]


def execute_tool(name: str, args: dict) -> dict:
    """Execute target MCP tool and return results in standard MCP content format."""
    try:
        if name == "chatterbox_list_characters":
            res = make_api_request("/api/v1/characters")
            if "detail" in res:
                return {"content": [{"type": "text", "text": f"Error: {res['detail']}"}], "isError": True}
            
            # Format output beautifully
            lines = ["### Chatterbox Characters List\n"]
            for char in res:
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

        elif name == "chatterbox_generate_tts":
            text = args.get("text")
            character_id = args.get("character_id")
            preset = args.get("preset", "balanced")
            model = args.get("model")
            language_id = args.get("language_id")

            # Route to correct endpoint
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
            
            res = make_api_request(endpoint, method="POST", data=encoded_data, headers=headers)
            if "detail" in res:
                return {"content": [{"type": "text", "text": f"Error: {res['detail']}"}], "isError": True}
                
            job_id = res.get("id")
            status = res.get("status")
            return {"content": [{"type": "text", "text": f"Job submitted successfully!\n* **Job ID**: `{job_id}`\n* **Status**: `{status}`\nUse `chatterbox_get_job_status` tool to check progress."}]}

        elif name == "chatterbox_get_job_status":
            job_id = args.get("job_id")
            res = make_api_request(f"/api/v1/jobs/{job_id}")
            if "detail" in res:
                return {"content": [{"type": "text", "text": f"Error: {res['detail']}"}], "isError": True}

            status = res.get("status", "unknown")
            phase = res.get("phase", "")
            progress = res.get("progress_percent", 0)
            err = res.get("error")
            audio_url = res.get("audio_url")
            benchmark = res.get("benchmark", {})

            output_msg = [
                f"### Job Status: {status.upper()}",
                f"* **Job ID**: `{job_id}`",
                f"* **Phase**: `{phase}`",
                f"* **Progress**: `{progress}%`"
            ]

            if err:
                output_msg.append(f"* **Error**: `{err}`")

            if status == "completed":
                # Convert relative URL to absolute URL
                full_audio_url = f"{API_URL.rstrip('/')}/{audio_url.lstrip('/')}" if audio_url else None
                output_msg.append(f"* **Audio Output URL**: {full_audio_url}")
                if benchmark:
                    duration = benchmark.get("audio_duration_seconds", 0.0)
                    rtf = benchmark.get("realtime_factor", 0.0)
                    output_msg.append(f"* **Audio Duration**: `{round(duration, 2)}s`")
                    output_msg.append(f"* **Realtime Factor (RTF)**: `{rtf}`")

            return {"content": [{"type": "text", "text": "\n".join(output_msg)}]}

        elif name == "chatterbox_voice_conversion":
            source_path = args.get("source_audio_path")
            character_id = args.get("character_id")
            target_path = args.get("target_audio_path")

            if not os.path.isfile(source_path):
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
                # Fetch character voice reference audio via API
                char_info = make_api_request(f"/api/v1/characters/{character_id}")
                if "detail" in char_info:
                    return {"content": [{"type": "text", "text": f"Error: Character not found: {char_info['detail']}"}], "isError": True}
                
                ref_url = char_info.get("reference_audio_url")
                if not ref_url:
                    return {"content": [{"type": "text", "text": f"Error: Character `{character_id}` does not have any reference audio" }], "isError": True}

                full_ref_url = f"{API_URL.rstrip('/')}/{ref_url.lstrip('/')}"
                log(f"Downloading character voice reference from {full_ref_url}")
                try:
                    with urllib.request.urlopen(full_ref_url, timeout=15) as resp:
                        target_bytes = resp.read()
                except Exception as e:
                    return {"content": [{"type": "text", "text": f"Error loading character reference: {e}"}], "isError": True}
            else:
                return {"content": [{"type": "text", "text": "Error: You must specify either character_id or target_audio_path"}], "isError": True}

            # Upload using Multipart Form
            files = {
                "source_audio": (os.path.basename(source_path), source_bytes),
            }
            if target_bytes:
                files["target_voice"] = (target_filename, target_bytes)

            payload, content_type = encode_multipart_formdata(files)
            headers = {"Content-Type": content_type}

            res = make_api_request("/api/v1/voice-conversion", method="POST", data=payload, headers=headers)
            if "detail" in res:
                return {"content": [{"type": "text", "text": f"Error: {res['detail']}"}], "isError": True}

            job_id = res.get("id")
            status = res.get("status")
            return {"content": [{"type": "text", "text": f"Voice conversion job submitted successfully!\n* **Job ID**: `{job_id}`\n* **Status**: `{status}`\nUse `chatterbox_get_job_status` tool to check progress."}]}

        elif name == "chatterbox_evaluate_voice":
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

            payload, content_type = encode_multipart_formdata(files=files, fields=fields)
            headers = {"Content-Type": content_type}

            res = make_api_request("/api/v1/voice-critic/evaluate", method="POST", data=payload, headers=headers)
            if "detail" in res:
                return {"content": [{"type": "text", "text": f"Error: {res['detail']}"}], "isError": True}

            report = res.get("markdown_report", "")
            spoken = res.get("spoken_feedback", "")
            feedback_job_id = res.get("feedback_job_id")
            feedback_audio_url = res.get("feedback_audio_url")

            full_audio_url = f"{API_URL.rstrip('/')}/{feedback_audio_url.lstrip('/')}" if feedback_audio_url else None
            
            output_msg = [
                report,
                "\n---",
                f"🔊 **AI Coach Audio Critique**: {full_audio_url}",
                f"*Feedback job enqueued with ID: `{feedback_job_id}`*"
            ]

            return {"content": [{"type": "text", "text": "\n".join(output_msg)}]}

        else:
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
                            "version": "1.0.0",
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
                arguments = params.get("arguments", {})
                result = execute_tool(tool_name, arguments)
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": result,
                }
                send_response(response)

            else:
                if req_id is not None:
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {
                            "code": -32601,
                            "message": f"Method not found: {method}",
                        },
                    }
                    send_response(response)
        except Exception as e:
            log(f"Error in JSON-RPC loop: {e}")


if __name__ == "__main__":
    main()
