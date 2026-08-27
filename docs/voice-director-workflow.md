# Chatterbox Voice Director — Workflow & Integration Guide (Phases 11–15)

## 1. Architecture Overview

```text
  AI Agent (Director / Orchestrator)
        │                         │
  (MCP Tools)               (REST API)
        │                         │
        └────────────►◄───────────┘
                      │
           FastAPI Server Runtime
                      │
            VoiceProjectService
     ┌────────────────┼────────────────┐
     ▼                ▼                ▼
 Planning & QC   Mix & Master   Deliverable Export
(Whisper Critic) (Pure Python)   (FINAL.wav + YAML)
```

## 2. End-to-End Autonomous Pipeline

```text
User Script
  │
  ├─► POST /api/v1/voice-workflows (or chatterbox_voice_produce)
  │
  ├─► Step 1: CREATE_PROJECT -> Initializes workspace in projects/{id}/
  │
  ├─► Step 2: PLAN           -> Analyzes story beats, voice plan, sound direction & critic
  │
  ├─► Step 3: CHECK_RESOURCES-> Resolves SFX/Ambience and pronunciation overrides
  │     │
  │     └─► [HUMAN ACTION GATE]: if missing required proper nouns -> pauses with WAITING_FOR_HUMAN
  │
  ├─► Step 4: RENDER         -> Per-beat synthesis via DefaultJobManagerGateway & Voice QC
  │     │
  │     └─► [HUMAN ACTION GATE]: if audio fails QC -> pauses for human review
  │
  ├─► Step 5: PREPARE_MIX    -> Computes deterministic MixPlan with exact WAV durations & beat pauses
  │
  ├─► Step 6: MIX            -> Pure Python 16-bit PCM multi-track audio mix to mix/premaster.wav
  │
  ├─► Step 7: MASTER         -> LUFS loudness normalization & dynamics peak limiter to mix/master.wav
  │
  ├─► Step 8: EXPORT         -> Packages exports/FINAL.wav and writes export-manifest.yaml
  │
  └─► Workflow State = COMPLETED
```

## 3. REST API Reference

### Voice Projects (`/api/v1/voice-projects`)
- `POST /api/v1/voice-projects` — Create project workspace.
- `GET /api/v1/voice-projects/{project_id}` — Get agent-friendly summary.
- `PUT /api/v1/voice-projects/{project_id}/script` — Update script text (invalidates downstream artifacts).
- `POST /api/v1/voice-projects/{project_id}/plan` — Trigger story analysis and planning (202 Accepted).
- `POST /api/v1/voice-projects/{project_id}/resources/check` — Check audio assets and pronunciations (202 Accepted).
- `POST /api/v1/voice-projects/{project_id}/render` — Trigger narration synthesis and Voice QC (202 Accepted, strict gate).
- `POST /api/v1/voice-projects/{project_id}/beats/{beat_id}/render` — Rerender single beat (202 Accepted).
- `POST /api/v1/voice-projects/{project_id}/evaluate` — Rerun QC evaluations (202 Accepted).
- `POST /api/v1/voice-projects/{project_id}/mix/prepare` — Build MixPlan (202 Accepted).
- `GET /api/v1/voice-projects/{project_id}/mix-plan` — Get MixPlan artifact.
- `POST /api/v1/voice-projects/{project_id}/mix` — Execute multi-track audio mixing (202 Accepted).
- `POST /api/v1/voice-projects/{project_id}/master` — Execute dynamics mastering (202 Accepted).
- `POST /api/v1/voice-projects/{project_id}/export` — Package deliverables and manifest (202 Accepted).
- `POST /api/v1/voice-projects/{project_id}/finalize` — Combined pipeline: prepare -> mix -> master -> export (202 Accepted).
- `GET /api/v1/voice-projects/{project_id}/artifacts` — List all deliverables and artifacts.
- `GET /api/v1/voice-projects/{project_id}/artifacts/{artifact_id}` — Download audio or plan artifact.

### Asynchronous Operations (`/api/v1/voice-project-jobs`)
- `GET /api/v1/voice-project-jobs/{job_id}` — Get operation status and progress.
- `POST /api/v1/voice-project-jobs/{job_id}/cancel` — Cancel active operation.

### Autonomous Workflows (`/api/v1/voice-workflows`)
- `POST /api/v1/voice-workflows` — Start autonomous produce workflow.
- `GET /api/v1/voice-workflows/{workflow_id}` — Get workflow status, steps, and human gates.
- `POST /api/v1/voice-workflows/{workflow_id}/resume` — Resume after human intervention.
- `POST /api/v1/voice-workflows/{workflow_id}/cancel` — Cancel autonomous workflow.

## 4. MCP Tools Catalog (35 Tools Total)

### Voice & Project Tools (16 Tools)
- `chatterbox_list_characters`, `chatterbox_generate_tts`, `chatterbox_get_job_status`, `chatterbox_download_audio`, `chatterbox_voice_conversion`, `chatterbox_evaluate_voice`
- `chatterbox_prepare_project`, `chatterbox_answer_project_questions`, `chatterbox_confirm_requirements`, `chatterbox_generate_script`, `chatterbox_confirm_script`, `chatterbox_get_project`, `chatterbox_list_projects`, `chatterbox_confirm_project`, `chatterbox_render_project`, `chatterbox_get_events`

### Voice Project & Post-Production Tools (15 Tools)
- `chatterbox_voice_project_create`
- `chatterbox_voice_project_get`
- `chatterbox_voice_plan`
- `chatterbox_voice_check_resources`
- `chatterbox_voice_render` (Strict: no public bypass)
- `chatterbox_voice_render_beat`
- `chatterbox_voice_qc`
- `chatterbox_voice_job_status`
- `chatterbox_voice_job_cancel`
- `chatterbox_voice_prepare_mix`
- `chatterbox_voice_mix`
- `chatterbox_voice_master`
- `chatterbox_voice_export`
- `chatterbox_voice_finalize`
- `chatterbox_voice_artifacts`

### Autonomous Workflow Tools (4 Tools)
- `chatterbox_voice_produce`
- `chatterbox_voice_workflow_status`
- `chatterbox_voice_workflow_resume`
- `chatterbox_voice_workflow_cancel`
