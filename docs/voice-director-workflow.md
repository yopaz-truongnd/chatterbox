# Voice Director Production Guide

## Architecture

```text
Human / AI Agent
  ├─ Director Console → REST
  └─ Voice Director Skill → MCP
                         ↓
VoiceProjectWorkflowService / VoiceProjectService
DirectorReviewService / DirectorRevisionService
                         ↓
Shared audio domain → local Chatterbox runtime
```

REST, MCP, CLI, and the browser are adapters. Project, workflow, operation,
revision, approval, and artifact state remain authoritative in application
services and persisted stores. Server services never call their own REST API.

## Production lifecycle

The workflow progresses through create, plan, resource check, render, evaluate,
prepare mix, mix, master, approval, and export. Render, rerender, reproduce,
mix, master, and export return operation IDs and run asynchronously. Poll the
operation until `completed`, `failed`, `cancelled`, or `interrupted`; do not
submit an equivalent operation while one is queued or running.

Default production TTS is local Chatterbox. Gemini is optional. The fake
provider is accepted only in tests and explicit validation runs.

## Human gates

Required resources stop the workflow until real pronunciations or managed asset
IDs are supplied. Narration acceptance and final master approval cannot be
bypassed with generic resume. Agents may summarize and recommend but must wait
for an explicit current human decision.

Final approval sends `approve_final_audio`, `artifact_id=master_wav`, and the
exact SHA-256 from the current `human_action`. The approved artifact ID and SHA
are persisted on the master workflow step. A changed or rebuilt master no longer
matches that approval and must be reviewed again. MCP additionally requires
`human_confirmed=true`, which is an attestation of the current human decision,
not a replacement for the server SHA check.

## Recovery

On re-entry, discover persisted projects and workflows, then inspect workflow,
operations, review, revisions, and `chatterbox_voice_next_action`. A queued or
running operation is monitored rather than duplicated. An interrupted workflow
can be explicitly resumed. Pending revisions retain the server-computed
`required_reproduction_steps`; timing-only revisions do not rerender narration
unless those authoritative steps say otherwise.

Browser refresh reconstructs Director Console state from REST. The console does
not own stage, approval, revision impact, or artifact validity.

## Artifact lineage and delivery

`VoiceProjectService.verify_delivery_lineage()` is the canonical delivery gate.
A final artifact is deliverable only when:

- the MixPlan still matches selected attempts and resources;
- premaster and master lineage files match their current inputs;
- the export manifest references the current master SHA;
- every exported file exists and matches its manifest SHA;
- no pending revision invalidates exports; and
- any required final approval matches the current master ID and SHA.

Final artifact listing, download, Director Review, Director Console, and Agent
delivery decisions use this rule. File existence alone is never sufficient.

## Agent workflow

Use the Voice Director skill loop: inspect → decide → act through MCP → observe.
Start with `chatterbox_voice_projects`, `chatterbox_voice_workflows`, and
`chatterbox_voice_jobs` when recovering context. Use
`chatterbox_voice_next_action` before consequential actions. If its response has
`requires_human=true`, stop and present `waiting_for`, `blocking_issue`, and the
requested items.

Review resources with `chatterbox_voice_missing_resources`, production state
with `chatterbox_voice_review`, beats with `chatterbox_voice_review_beat`, and
pending work with `chatterbox_voice_revisions`. Submit artistic changes only
through revision tools and reproduce only the returned dependency path.

## Director Console workflow

The console supports project discovery, persisted operation polling, beat and
attempt review, direction/timing revisions, resource resolution, human gates,
mix/master inspection, and verified delivery. Download controls remain disabled
for stale or unverified final artifacts. Interrupted workflows expose Resume;
approval gates expose their specific review action instead.

## Known limitations

- Human confirmation is enforced by workflow state, exact artifact SHA, and MCP
  attestation; identity and multi-user authorization are outside the local
  single-user runtime.
- Real local inference speed and memory use depend on the selected model and
  hardware. Run the opt-in local production smoke test before release.
- MP3 delivery requires FFmpeg; WAV remains available without it.
