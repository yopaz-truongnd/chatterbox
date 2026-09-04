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
                "retry_budget": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Maximum TTS/QC attempts per beat.",
                },
                "auto_accept_qc_pass": {
                    "type": "boolean",
                    "description": "Whether QC-passed narration is accepted without a human gate.",
                },
                "allow_resource_substitute": {
                    "type": "boolean",
                    "description": "Allow semantic substitution for missing audio resources.",
                },
                "mixing_profile": {
                    "type": "string",
                    "description": "Mixing profile (for example, storytelling or dramatic).",
                },
                "mastering_profile": {
                    "type": "string",
                    "description": "Mastering dynamics profile (default: 'storytelling').",
                },
                "output_formats": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "require_final_approval": {
                    "type": "boolean",
                    "description": "Pause after mastering for explicit final approval.",
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
    {
        "name": "chatterbox_voice_workflow_approve",
        "description": "Submit an explicit approval decision for narration or final master audio.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string"},
                "action": {
                    "type": "string",
                    "enum": ["approve_narration", "approve_final_audio"],
                },
                "approved": {"type": "boolean"},
                "artifact_id": {"type": "string"},
                "artifact_sha256": {"type": "string"},
            },
            "required": ["workflow_id", "action", "approved"],
        },
    },
]


def _director_tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "name": name,
        "description": description,
        "inputSchema": {"type": "object", "properties": properties, "required": required},
    }


_PROJECT = {"project_id": {"type": "string"}}
_BEAT = {**_PROJECT, "beat_id": {"type": "string"}}
_ATTEMPT = {**_BEAT, "attempt_id": {"type": "integer"}, "actor_id": {"type": "string"}, "reason": {"type": "string"}}
VOICE_PROJECT_TOOL_SCHEMAS.extend([
    _director_tool("chatterbox_voice_review", "Get the complete director-facing production review.", _PROJECT, ["project_id"]),
    _director_tool("chatterbox_voice_missing_resources", "Get the required and recommended resource shopping list.", _PROJECT, ["project_id"]),
    _director_tool("chatterbox_voice_add_pronunciation", "Add a provider-independent pronunciation override.", {**_PROJECT, "term": {"type": "string"}, "phonetic": {"type": "string"}, "actor_id": {"type": "string"}}, ["project_id", "term", "phonetic"]),
    _director_tool("chatterbox_voice_bind_resource", "Bind a managed asset to a resource gap.", {**_PROJECT, "resource_id": {"type": "string"}, "asset_id": {"type": "string"}, "allow_substitution": {"type": "boolean"}}, ["project_id", "resource_id", "asset_id"]),
    _director_tool("chatterbox_voice_review_beat", "Review one beat and all generated candidates.", _BEAT, ["project_id", "beat_id"]),
    _director_tool("chatterbox_voice_select_attempt", "Select an existing passing candidate without rerendering.", _ATTEMPT, ["project_id", "beat_id", "attempt_id"]),
    _director_tool("chatterbox_voice_approve_attempt", "Explicitly approve and select a candidate.", _ATTEMPT, ["project_id", "beat_id", "attempt_id", "actor_id"]),
    _director_tool("chatterbox_voice_reject_attempt", "Reject an audio candidate with audit metadata.", _ATTEMPT, ["project_id", "beat_id", "attempt_id", "actor_id"]),
    _director_tool("chatterbox_voice_update_direction", "Patch narration direction for one beat.", {**_BEAT, "emotion": {"type": "string"}, "energy": {"type": "number"}, "pace": {"type": "number"}, "voice_style": {"type": "string"}}, ["project_id", "beat_id"]),
    _director_tool("chatterbox_voice_update_timing", "Patch pauses without rerendering narration.", {**_BEAT, "pause_before_ms": {"type": "number"}, "pause_after_ms": {"type": "number"}}, ["project_id", "beat_id"]),
    _director_tool("chatterbox_voice_update_resources", "Patch beat ambience or SFX direction.", {**_BEAT, "ambience_intent": {"type": "string"}, "sfx": {"type": "array", "items": {"type": "object"}}}, ["project_id", "beat_id"]),
    _director_tool("chatterbox_voice_revisions", "Get persisted revision history and invalidation state.", _PROJECT, ["project_id"]),
    _director_tool("chatterbox_voice_reproduce", "Schedule minimum-safe incremental reproduction.", {**_PROJECT, "revision_ids": {"type": "array", "items": {"type": "string"}}, "provider": {"type": "string"}, "policy": {"type": "object"}}, ["project_id"]),
])


ASSET_TOOL_SCHEMAS: list[dict] = [
    {
        "name": "chatterbox_voice_assets",
        "description": "List all assets in the Intelligent Asset Library, optionally filtered by category.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["ambience", "sfx", "voice_reference", "pronunciation_reference"],
                    "description": "Optional category filter.",
                },
            },
        },
    },
    {
        "name": "chatterbox_voice_asset_register",
        "description": "Register a single audio file into the Intelligent Asset Library with security validation (path traversal checks, magic byte validation, SHA-256 dedup).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute or permitted-root-relative path to the audio file.",
                },
                "category": {
                    "type": "string",
                    "enum": ["ambience", "sfx", "voice_reference", "pronunciation_reference"],
                    "description": "Asset category.",
                },
                "intents": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Semantic intent tags (e.g. 'forest_atmosphere', 'thunder_crack').",
                },
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Search keywords for matching.",
                },
                "mood": {"type": "string", "description": "Mood descriptor (e.g. 'tense', 'peaceful')."},
                "environment": {"type": "string", "description": "Environment descriptor (e.g. 'forest', 'cave')."},
                "energy": {"type": "number", "minimum": 0.0, "maximum": 5.0, "description": "Energy level 0.0–5.0."},
                "loopable": {"type": "boolean", "description": "Whether the asset is suitable for looping."},
                "license": {"type": "string", "description": "License identifier (e.g. 'CC0', 'CC-BY-4.0')."},
                "source_url": {"type": "string", "description": "URL where this asset was obtained."},
                "attribution": {"type": "string", "description": "Required attribution text."},
            },
            "required": ["file_path", "category"],
        },
    },
    {
        "name": "chatterbox_voice_asset_scan",
        "description": "Batch scan a directory and automatically ingest all supported audio files (WAV, MP3, FLAC) into the Asset Library.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "directory_path": {
                    "type": "string",
                    "description": "Path to the directory to scan.",
                },
                "category": {
                    "type": "string",
                    "enum": ["ambience", "sfx", "voice_reference", "pronunciation_reference"],
                    "description": "Category to assign to all discovered assets.",
                },
            },
            "required": ["directory_path", "category"],
        },
    },
    {
        "name": "chatterbox_voice_asset_match",
        "description": "Find and rank library assets that best match a semantic request using intent overlap, mood, duration, and energy scoring.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "intents": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Required semantic intents to match (e.g. ['forest_atmosphere']).",
                },
                "category": {
                    "type": "string",
                    "enum": ["ambience", "sfx", "voice_reference", "pronunciation_reference"],
                    "description": "Asset category to search within.",
                },
                "mood": {"type": "string", "description": "Optional mood filter."},
                "environment": {"type": "string", "description": "Optional environment keyword filter."},
                "duration_ms": {"type": "number", "description": "Desired duration in milliseconds."},
                "loopable": {"type": "boolean", "description": "If true, only loopable assets are returned."},
                "story_context": {"type": "string", "description": "Story beat context text for energy scoring."},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 50, "description": "Maximum results to return (default: 5)."},
            },
            "required": ["intents", "category"],
        },
    },
    {
        "name": "chatterbox_voice_asset_preview",
        "description": "Get the URL to fetch a 200ms WAV preview clip for a specific asset in the library.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "asset_id": {
                    "type": "string",
                    "description": "The asset ID to preview.",
                },
            },
            "required": ["asset_id"],
        },
    },
]

RUNTIME_TOOL_SCHEMAS: list[dict] = [
    {
        "name": "chatterbox_voice_runtime_capabilities",
        "description": "Inspect in-process local Chatterbox runtime capabilities (cached models, active models, compute device, max concurrency, supported formats).",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "chatterbox_voice_runtime_preflight",
        "description": "Perform synchronous preflight validation for a project before execution.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Target project ID."},
                "provider": {"type": "string", "description": "TTS provider ('local', 'gemini', 'fake')."},
                "requested_formats": {"type": "array", "items": {"type": "string"}, "description": "Requested output audio formats."},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "chatterbox_voice_validate_runtime",
        "description": "Launch full real-runtime production validation against local Chatterbox TTS.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "provider": {"type": "string", "description": "TTS Provider ('local', 'gemini', 'fake')."},
                "model": {"type": "string", "description": "TTS Model (e.g. 'nano', 'turbo')."},
                "language": {"type": "string", "description": "Language code (default 'en')."},
                "script_path": {"type": "string", "description": "Optional story script path."},
                "profile": {"type": "string", "description": "Optional validation profile name/path."},
                "output_formats": {"type": "array", "items": {"type": "string"}, "description": "Deliverable formats (wav, mp3)."},
                "require_final_approval": {"type": "boolean", "description": "Whether final master approval is required."},
                "require_narration_acceptance": {"type": "boolean", "description": "Whether narration review gate is required."},
                "run_incremental_reproduction": {"type": "boolean", "description": "Test one-beat incremental reproduction."},
            },
        },
    },
    {
        "name": "chatterbox_voice_validation_status",
        "description": "Query progress and execution status of a production validation run.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "validation_id": {"type": "string", "description": "Target validation ID."},
            },
            "required": ["validation_id"],
        },
    },
    {
        "name": "chatterbox_voice_validation_report",
        "description": "Retrieve full sanitized diagnostics and metrics report for a production validation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "validation_id": {"type": "string", "description": "Target validation ID."},
            },
            "required": ["validation_id"],
        },
    },
    {
        "name": "chatterbox_voice_validation_cancel",
        "description": "Cancel an active production validation execution.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "validation_id": {"type": "string", "description": "Target validation ID."},
            },
            "required": ["validation_id"],
        },
    },
]

SERIES_TOOL_SCHEMAS: list[dict] = [
    {
        "name": "chatterbox_voice_series_create",
        "description": "Create a multi-episode story series with shared voice, pronunciation, and sound bibles.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Title of the series."},
                "description": {"type": "string", "description": "Optional summary or overview."},
                "language": {"type": "string", "description": "Primary language code (default 'en')."},
                "voice_bible": {"type": "object", "description": "Shared narrator and voice configuration."},
                "pronunciation_bible": {"type": "object", "description": "Shared proper noun pronunciation dictionary."},
                "sound_bible": {"type": "object", "description": "Shared sound palette and mastering profile."},
                "series_id": {"type": "string", "description": "Optional explicit series ID."},
            },
            "required": ["title"],
        },
    },
    {
        "name": "chatterbox_voice_series_get",
        "description": "Get detailed status, episodes list, and bibles for a specific series.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "series_id": {"type": "string", "description": "Target series ID."},
            },
            "required": ["series_id"],
        },
    },
    {
        "name": "chatterbox_voice_series_add_episode",
        "description": "Add an episode project to a story series.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "series_id": {"type": "string", "description": "Target series ID."},
                "project_id": {"type": "string", "description": "VoiceProject ID corresponding to this episode."},
                "title": {"type": "string", "description": "Title of the episode."},
                "episode_number": {"type": "integer", "description": "Episode order number (1-based)."},
            },
            "required": ["series_id", "project_id", "title"],
        },
    },
    {
        "name": "chatterbox_voice_series_produce",
        "description": "Execute batch production across episodes in a story series with concurrency control.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "series_id": {"type": "string", "description": "Target series ID."},
                "episode_ids": {"type": "array", "items": {"type": "string"}, "description": "Optional list of specific episode IDs to produce."},
            },
            "required": ["series_id"],
        },
    },
    {
        "name": "chatterbox_voice_series_status",
        "description": "Get overall batch progress and status for a series.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "series_id": {"type": "string", "description": "Target series ID."},
            },
            "required": ["series_id"],
        },
    },
    {
        "name": "chatterbox_voice_series_review_queue",
        "description": "Get all pending human approval gates across episodes in a story series.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "series_id": {"type": "string", "description": "Target series ID."},
            },
            "required": ["series_id"],
        },
    },
    {
        "name": "chatterbox_voice_series_cancel",
        "description": "Cancel an in-flight batch production for a story series.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "series_id": {"type": "string", "description": "Target series ID."},
            },
            "required": ["series_id"],
        },
    },
]

HEALTH_TOOL_SCHEMAS: list[dict] = [
    {
        "name": "chatterbox_voice_health",
        "description": "Get aggregated production health and artifact freshness for a voice project.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Target project ID."},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "chatterbox_voice_events",
        "description": "Get recent structured audit events for a project.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Target project ID."},
                "limit": {"type": "integer", "description": "Max events to fetch (default: 100)."},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "chatterbox_voice_diagnostics",
        "description": "Generate a comprehensive sanitized diagnostic bundle for troubleshooting a project or series.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Optional project ID."},
                "series_id": {"type": "string", "description": "Optional series ID."},
            },
        },
    },
    {
        "name": "chatterbox_voice_series_health",
        "description": "Get aggregated production health for an entire story series.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "series_id": {"type": "string", "description": "Target series ID."},
            },
            "required": ["series_id"],
        },
    },
    {
        "name": "chatterbox_voice_series_events",
        "description": "Get recent structured audit events for a series.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "series_id": {"type": "string", "description": "Target series ID."},
                "limit": {"type": "integer", "description": "Max events to fetch (default: 100)."},
            },
            "required": ["series_id"],
        },
    },
]


def get_tools_list() -> list[dict]:
    """Return all tool schemas available on this MCP server."""
    return (
        VOICE_TOOL_SCHEMAS
        + PROJECT_TOOL_SCHEMAS
        + VOICE_PROJECT_TOOL_SCHEMAS
        + ASSET_TOOL_SCHEMAS
        + RUNTIME_TOOL_SCHEMAS
        + SERIES_TOOL_SCHEMAS
        + HEALTH_TOOL_SCHEMAS
    )
