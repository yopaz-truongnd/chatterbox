"""Chatterbox MCP Tool Schema Catalog (Phase 13-15)."""

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
        "description": "Download generated audio output safely to a local path on the user machine.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "The ID of the completed job whose audio output should be downloaded.",
                },
                "destination_dir": {
                    "type": "string",
                    "description": "Local folder path where the audio file should be saved. Default is the Chatterbox outputs directory.",
                },
            },
            "required": ["job_id"],
        },
    },
    {
        "name": "chatterbox_voice_conversion",
        "description": "Convert speech in a source audio file to match the timbre and vocal characteristics of a target voice.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_audio_path": {
                    "type": "string",
                    "description": "Path to the input voice audio file to convert.",
                },
                "target_character_id": {
                    "type": "string",
                    "description": "Target character ID to clone/mimic voice from.",
                },
            },
            "required": ["source_audio_path", "target_character_id"],
        },
    },
    {
        "name": "chatterbox_evaluate_voice",
        "description": "Analyze and evaluate speech synthesis quality metrics (Signal QC and Speech Critic) for an audio file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "audio_path": {
                    "type": "string",
                    "description": "Path to the audio file to evaluate.",
                },
                "reference_text": {
                    "type": "string",
                    "description": "Reference script text to verify against omissions or hallucinations.",
                },
            },
            "required": ["audio_path"],
        },
    },
]

PROJECT_TOOL_SCHEMAS: list[dict] = [
    {
        "name": "chatterbox_prepare_project",
        "description": "Initialize a structured audio story/podcast project from a user prompt, collecting initial requirements and generating clarifying questions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "The high-level topic or theme of the story, podcast, or voice project.",
                },
                "initial_requirements": {
                    "type": "string",
                    "description": "Optional user preferences (tone, audience, target length, number of characters, sound style).",
                },
                "auto_defaults": {
                    "type": "boolean",
                    "description": "If true, automatically fill reasonable defaults for unanswered requirements.",
                },
            },
            "required": ["topic"],
        },
    },
    {
        "name": "chatterbox_answer_project_questions",
        "description": "Submit answers to requirements questions for an in-progress audio project.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The unique ID of the project.",
                },
                "answers": {
                    "type": "object",
                    "description": "Key-value mapping of question IDs or question text to user answers.",
                },
                "auto_defaults": {
                    "type": "boolean",
                    "description": "If true, fill any remaining unanswered questions with reasonable defaults.",
                },
            },
            "required": ["project_id", "answers"],
        },
    },
    {
        "name": "chatterbox_confirm_requirements",
        "description": "Confirm and finalize the project requirements matrix, locking the story brief for script writing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The unique ID of the project.",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "Whether the user/agent confirms the requirements (must be true to proceed).",
                },
            },
            "required": ["project_id", "confirmed"],
        },
    },
    {
        "name": "chatterbox_generate_script",
        "description": "Generate a full narrative voice script with pacing, emotional beats, and sound cues based on confirmed requirements.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The unique ID of the project.",
                },
                "custom_instructions": {
                    "type": "string",
                    "description": "Optional extra instructions for script generation.",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "chatterbox_confirm_script",
        "description": "Confirm or adjust generated voice script before character allocation and timeline planning.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The unique ID of the project.",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "Whether the user/agent confirms the script.",
                },
            },
            "required": ["project_id", "confirmed"],
        },
    },
    {
        "name": "chatterbox_get_project",
        "description": "Retrieve current project details, stage, script, voice timeline, and render status.",
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
        "description": "List all active and completed audio projects.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "chatterbox_confirm_project",
        "description": "Confirm the finalized script, voice casting, and timeline before audio rendering starts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The unique ID of the project.",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "Whether the user confirms the script and voice allocation (must be true to start render).",
                },
            },
            "required": ["project_id", "confirmed"],
        },
    },
    {
        "name": "chatterbox_render_project",
        "description": "Trigger multi-segment voice synthesis and timeline assembly for a confirmed project.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The unique ID of the project to render.",
                },
                "priority": {
                    "type": "string",
                    "enum": ["normal", "high"],
                    "description": "Execution priority (default: 'normal').",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "chatterbox_get_events",
        "description": "Stream or poll project execution events, timeline updates, and progress logs.",
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
]

VOICE_PROJECT_TOOL_SCHEMAS: list[dict] = [
    # ---------------------------------------------------------
    # Core Lifecycle Tools (Phase 13)
    # ---------------------------------------------------------
    {
        "name": "chatterbox_voice_project_create",
        "description": "Create a new Voice Narration project with source script and configuration.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "script_text": {
                    "type": "string",
                    "description": "The raw story script text to narrate.",
                },
                "project_id": {
                    "type": "string",
                    "description": "Unique project identifier slug (e.g. 'torch_dragon'). Optional.",
                },
                "title": {
                    "type": "string",
                    "description": "Human-readable project title. Optional.",
                },
                "language": {
                    "type": "string",
                    "description": "Source text language code (default: 'en').",
                },
                "config": {
                    "type": "object",
                    "description": "Optional voice configuration (e.g. voice profile).",
                },
            },
            "required": ["script_text"],
        },
    },
    {
        "name": "chatterbox_voice_project_get",
        "description": "Get comprehensive agent-friendly project summary including current stage, beat counts, resource readiness, and suggested next action.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The unique project identifier.",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "chatterbox_voice_plan",
        "description": "Trigger automated story beat analysis, narration planning, sound direction, and director critique for a voice project.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The unique project identifier.",
                },
                "config": {
                    "type": "object",
                    "description": "Optional planning settings override.",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "chatterbox_voice_check_resources",
        "description": "Check and resolve audio requirements (SFX, Ambience) and pronunciation knowledge for a directed voice plan.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The unique project identifier.",
                },
                "manifest_path": {
                    "type": "string",
                    "description": "Custom asset manifest path. Optional.",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "chatterbox_voice_render",
        "description": "Trigger asynchronous narration audio synthesis and automated Voice QC verification for a project.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The unique project identifier.",
                },
                "provider": {
                    "type": "string",
                    "description": "TTS Provider: 'local' (default), 'gemini', or 'fake' (testing).",
                },
                "beats": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional subset of beat IDs to render.",
                },
                "auto_qc": {
                    "type": "boolean",
                    "description": "Whether to perform automatic Voice QC (default: true).",
                },
                "force_rerender": {
                    "type": "boolean",
                    "description": "Whether to force rerender of passed beats (default: false).",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "chatterbox_voice_render_beat",
        "description": "Selectively synthesize or rerender a single specific narration beat.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The unique project identifier.",
                },
                "beat_id": {
                    "type": "string",
                    "description": "Beat ID to render (e.g. 'B01').",
                },
                "provider": {
                    "type": "string",
                    "description": "TTS Provider: 'local', 'gemini', or 'fake'.",
                },
            },
            "required": ["project_id", "beat_id"],
        },
    },
    {
        "name": "chatterbox_voice_qc",
        "description": "Re-evaluate Signal QC and Speech Critic on existing audio renders without re-synthesizing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The unique project identifier.",
                },
                "beats": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional subset of beat IDs to re-evaluate.",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "chatterbox_voice_job_status",
        "description": "Check status, progress, active stage, and current beat of an asynchronous Voice Project operation job.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "The operation job ID (e.g. 'vp_op_xxx').",
                },
            },
            "required": ["job_id"],
        },
    },
    {
        "name": "chatterbox_voice_job_cancel",
        "description": "Cancel a running or queued Voice Project operation job.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "The operation job ID to cancel.",
                },
            },
            "required": ["job_id"],
        },
    },
    # ---------------------------------------------------------
    # Phase 14: Mixing, Mastering & Deliverables Tools
    # ---------------------------------------------------------
    {
        "name": "chatterbox_voice_prepare_mix",
        "description": "Prepare multi-track audio MixPlan for a project in NARRATION_READY stage.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The unique project identifier.",
                },
                "mastering_profile": {
                    "type": "string",
                    "description": "Mastering profile name ('storytelling', 'podcast'). Default: 'storytelling'.",
                },
                "output_formats": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Target export formats (e.g. ['wav']).",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "chatterbox_voice_mix",
        "description": "Render multi-track timeline audio mix to generate mix/premaster.wav.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The unique project identifier.",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "chatterbox_voice_master",
        "description": "Apply loudness normalization and dynamics limiter to create mix/master.wav.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The unique project identifier.",
                },
                "profile": {
                    "type": "string",
                    "description": "Mastering profile name (default: 'storytelling').",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "chatterbox_voice_export",
        "description": "Package master audio into deliverable files (FINAL.wav) with cryptographic export manifest.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The unique project identifier.",
                },
                "formats": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of export formats (default: ['wav']).",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "chatterbox_voice_finalize",
        "description": "Execute end-to-end post-production pipeline (prepare_mix -> mix -> master -> export) in a single operation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The unique project identifier.",
                },
                "mastering_profile": {
                    "type": "string",
                    "description": "Mastering profile (default: 'storytelling').",
                },
                "output_formats": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Target export formats (default: ['wav']).",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "chatterbox_voice_artifacts",
        "description": "List all generated deliverable audio and plan artifacts for a voice project.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The unique project identifier.",
                },
            },
            "required": ["project_id"],
        },
    },
    # ---------------------------------------------------------
    # Phase 15: Autonomous Workflow Tools
    # ---------------------------------------------------------
    {
        "name": "chatterbox_voice_produce",
        "description": "Launch autonomous end-to-end voice story production from script to final deliverable audio. Automatically plans, verifies resources, renders, QCs, mixes, masters, and exports. Pauses at human gates if required pronunciations or audio reviews are needed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "script_text": {
                    "type": "string",
                    "description": "The complete story script text to produce.",
                },
                "project_id": {
                    "type": "string",
                    "description": "Optional custom project identifier.",
                },
                "title": {
                    "type": "string",
                    "description": "Optional story title.",
                },
                "provider": {
                    "type": "string",
                    "description": "TTS provider ('local', 'gemini', 'fake'). Default: 'local'.",
                },
                "mastering_profile": {
                    "type": "string",
                    "description": "Mastering dynamics profile (default: 'storytelling').",
                },
            },
            "required": ["script_text"],
        },
    },
    {
        "name": "chatterbox_voice_workflow_status",
        "description": "Check status, current step, human action gates, and results of an autonomous production workflow.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workflow_id": {
                    "type": "string",
                    "description": "The workflow ID (e.g. 'vwf_xxx').",
                },
            },
            "required": ["workflow_id"],
        },
    },
    {
        "name": "chatterbox_voice_workflow_resume",
        "description": "Resume execution of an autonomous workflow after resolving a human gate (e.g. after adding required pronunciation).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workflow_id": {
                    "type": "string",
                    "description": "The workflow ID to resume.",
                },
            },
            "required": ["workflow_id"],
        },
    },
    {
        "name": "chatterbox_voice_workflow_cancel",
        "description": "Cancel an in-flight autonomous production workflow.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workflow_id": {
                    "type": "string",
                    "description": "The workflow ID to cancel.",
                },
            },
            "required": ["workflow_id"],
        },
    },
]


def get_tools_list() -> list[dict]:
    """Return all tool schemas available on this MCP server."""
    return VOICE_TOOL_SCHEMAS + PROJECT_TOOL_SCHEMAS + VOICE_PROJECT_TOOL_SCHEMAS
