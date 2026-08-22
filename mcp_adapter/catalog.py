"""Chatterbox MCP Tool Schema Catalog."""

from __future__ import annotations

VOICE_TOOL_SCHEMAS: list[dict] = [
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
        "description": "Generate synthesized speech (Text-to-Speech) using a specified character voice or standard preset.",
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
                    "description": "Target model: 'nano' (light/CPU), 'turbo' (paralinguistic tags), 'standard' (500M high quality), 'multilingual'. Optional.",
                },
                "language_id": {
                    "type": "string",
                    "description": "Target language ID (e.g. 'en', 'zh', 'ja', 'fr') for multilingual model. Optional.",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "chatterbox_get_job_status",
        "description": "Get current status, progress, duration, and output audio URL of a voice generation or conversion job.",
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
        "name": "chatterbox_download_audio",
        "description": "Safely download the completed audio WAV file from a Chatterbox job with atomic write and overwrite protection.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "Unique ID of the completed job.",
                },
                "destination_path": {
                    "type": "string",
                    "description": "Target filename or relative path inside project 'outputs/mcp/' (e.g. 'speech.wav'). Absolute paths outside outputs/mcp/ are rejected for security. Defaults to 'chatterbox_{job_id}.wav'.",
                },
                "overwrite": {
                    "type": "boolean",
                    "description": "Whether to overwrite existing destination file. Defaults to False.",
                },
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
        "description": "Evaluate the quality of a voice reading (loudness, expressiveness, pace, pronunciation) with Voice Critic feedback and structured metrics.",
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
                    "description": "The script text to check pronunciation accuracy against. Optional.",
                },
                "coach_character_id": {
                    "type": "string",
                    "description": "Character ID of the AI coach to read back the spoken feedback. Optional.",
                },
            },
        },
    },
]

PROJECT_TOOL_SCHEMAS: list[dict] = [
    {
        "name": "chatterbox_prepare_project",
        "description": "Initialize a structured audio project from a user topic/idea. Extracts existing parameters, determines missing required/recommended slots, and returns a single-batch list of questions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "The topic, concept, or description of the audio project (e.g. 'Podcast 5 phút về lịch sử AI cho người mới').",
                },
                "initial_requirements": {
                    "type": "object",
                    "description": "Pre-known parameters (format, target_duration_seconds, audience, language, tone, character_id, sfx_level, output_formats). Optional.",
                },
                "auto_defaults": {
                    "type": "boolean",
                    "description": "If True, auto-populates sensible defaults for all non-essential recommended fields without asking. Defaults to False.",
                },
            },
            "required": ["topic"],
        },
    },
    {
        "name": "chatterbox_answer_project_questions",
        "description": "Submit answers (structured dict or natural language string) to fill missing project requirements, advancing the project to final confirmation review.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The unique ID of the project.",
                },
                "answers": {
                    "description": "Answers to the missing questions (can be a dictionary mapping field IDs, or a natural language text response).",
                },
                "auto_defaults": {
                    "type": "boolean",
                    "description": "If True, automatically fills any remaining non-critical fields with standard defaults. Defaults to False.",
                },
            },
            "required": ["project_id", "answers"],
        },
    },
    {
        "name": "chatterbox_confirm_requirements",
        "description": "Gate 1 Confirmation: Explicitly approve project requirements and automatically generate the initial English scene outline and script.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The unique ID of the project.",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "Set to True to confirm requirements and proceed to script generation, or False to cancel. Defaults to True.",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "chatterbox_generate_script",
        "description": "Generate or re-generate the English scene outline and full narration script based on confirmed requirements.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The unique ID of the project.",
                },
                "custom_prompt": {
                    "type": "string",
                    "description": "Optional custom prompt or instructions to tailor the generated script.",
                },
                "num_scenes": {
                    "type": "integer",
                    "description": "Optional target number of scenes (default: auto based on target duration).",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "chatterbox_confirm_script",
        "description": "Gate 2 Confirmation: Review and approve the English script and scene outline. Approval transitions the project to 'approved', enabling high-level rendering.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The unique ID of the project.",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "Set to True to approve the script, or False to request revision. Defaults to True.",
                },
                "script_text": {
                    "type": "string",
                    "description": "Optional updated script text edited by user.",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "chatterbox_confirm_project",
        "description": "Unified Confirmation dispatcher: Confirms whichever gate is currently pending (Gate 1 requirements or Gate 2 script).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The unique ID of the project to approve.",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "Set to True to approve, or False to cancel/revise. Defaults to True.",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "chatterbox_render_project",
        "description": "High-level Orchestration: Segment the approved script, synthesize segments with signal quality checks, and merge the final master audio. Strictly rejects unapproved projects.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The unique ID of the approved project.",
                },
                "script_text": {
                    "type": "string",
                    "description": "Custom narration script text override. Optional.",
                },
                "character_id": {
                    "type": "string",
                    "description": "Character ID override. Optional.",
                },
                "quality_preset": {
                    "type": "string",
                    "enum": ["fast", "balanced", "expressive"],
                    "description": "Quality preset override. Optional.",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "chatterbox_get_project",
        "description": "Retrieve the current state, requirements, outline, script, segments, and structured summary for a project.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The unique ID of the project.",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "chatterbox_list_projects",
        "description": "List all existing audio projects with their status and metadata.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "chatterbox_get_events",
        "description": "Long-polling event stream for real-time project & rendering status updates. Returns immediately when new events occur or waits up to wait_seconds with zero CPU idle usage.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "after_event_id": {
                    "type": "integer",
                    "description": "Retrieve events with ID strictly greater than this ID (default: 0).",
                },
                "project_id": {
                    "type": "string",
                    "description": "Optional project ID filter.",
                },
                "wait_seconds": {
                    "type": "integer",
                    "description": "Max seconds to wait for new events (default: 0, max: 30).",
                },
            },
        },
    },
]


def get_tools_list() -> list[dict]:
    """Return all tool schemas available on this MCP server."""
    return VOICE_TOOL_SCHEMAS + PROJECT_TOOL_SCHEMAS
