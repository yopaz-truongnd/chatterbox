---
name: voice-director
description: >-
  Converts scripts into cinematic narration timelines using emotional beats,
  directing tones, dynamic pauses, and SFX cueing before rendering with Chatterbox.
---

# Voice Director Skill (v1)

This skill guides the agent through converting narrative scripts into a cinematic, emotion-driven audio production timeline using the Chatterbox Projects & Batch APIs.

---

## 🎙️ Lifecycle of a Directing Project

The Voice Director workflow supports two execution modes: **Interactive Confirmation Mode** (Default) and **Auto-Run Mode**.

### Mode A: Interactive Confirmation (Default)

#### PHASE 1: Analyze & Plan (Analysis Table)
When given a script, do **NOT** generate audio yet. First, create a structured emotional beat table:

| Beat | Category (Hook/Reveal/Climax/Reflection) | Emotion | Energy (1-5) | Pause (s) | SFX Cue | Script Segment |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |

##### Rules for Phase 1:
1. **Split by Emotion**: Divide by storytelling beats (shifting tension, reveals, emotional peaks) rather than standard punctuation or sentence boundaries.
2. **Keep Beats Short**: Keep each beat to 1-3 sentences maximum.
3. **SFX Tags**: Suggest atmospheric sound effects like `[WIND_LOW]`, `[DEEP_RUMBLE]`, `[FIRE_WHOOSH]`, `[IMPACT_BOOM]`, `[ETHEREAL_PAD]`.
4. **Director Notes**: Beneath the table, provide a short bulleted list of Director Notes for each beat describing the delivery.
5. **Phase Ending**: Always conclude Phase 1 with the exact phrase:
   `**Awaiting approval for rendering.**`

#### PHASE 2: Script Execution (After User Approval)
Only after the user responds with **`APPROVED`**, **`DUYỆT`**, **`OK`**, or **`ok`**, proceed to output the beat-by-beat directing blocks and render.

For each beat, output:
### Beat X
* **Scene**: [Brief visual or thematic context]
* **Audio Profile**: [Emotion, Energy Level, WPM target]
* **SFX Cue**: [SFX Name and timing]
* **Director Note**: [Delivery style details]
* **TTS Text**: [The text to be read, including natural inline pauses e.g. `(0.8s pause)`]

After presenting Phase 2, proceed to call the Projects API to render the audio.

---

### Mode B: Auto-Run (Skip Confirmation)
* **Trigger**: This mode only runs when the user explicitly requests it (e.g. *"chạy tự động"*, *"không cần xác nhận"*, *"auto run"*).
* **Behavior**: Skip Phase 1 completely. Immediately generate the Phase 2 beat blocks and submit the script to the Projects API for rendering.

---

## ⚙️ Orchestration with Chatterbox API

Once the directing plan is finalized, render the voiceover using the Projects API:

1. **Initialize Project**: Call `/api/v1/projects/prepare` with the topic.
2. **Set Requirements**: Configure format as `video_narration` or `audiobook` with English language.
3. **Submit Directed Script**: Call `/api/v1/projects/{project_id}/confirm-script` passing the compiled text with formatted inline pauses and scene boundaries.
4. **Render**: Trigger rendering through `/api/v1/projects/{project_id}/render`.
