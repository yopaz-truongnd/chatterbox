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
3. **SFX Decision System**: Each suggested SFX cue must serve one of 5 dramatic functions:
   - *Atmosphere* (wind, cave drone)
   - *Transition* (whoosh, riser)
   - *Physical* (actions like footsteps, fire)
   - *Emphasis* (impact boom, bass hit)
   - *Emotional* (mood shifts)
   If it cannot be justified, use **`SILENCE`**.
4. **Silence as a Decision**: Explicitly treat silence as an active sound design choice. Prefer silence for emotional, philosophical, or important reveal lines to give the voice breathing room.
5. **SFX Necessity Scoring**: Rate each cue's necessity from 0.0 to 1.0:
   - `< 0.40` -> Discard (set to `SILENCE`)
   - `0.40–0.65` -> Ambient/subtle only
   - `0.65–0.80` -> Light SFX
   - `> 0.80` -> Prominent SFX allowed
6. **SFX Placement / Timing**: Specify timing placement for each cue:
   - `PRE` (before speech starts)
   - `UNDER` (during speech)
   - `POST` (immediately after speech with offset in seconds)
   - `BRIDGE` (transitional element between beats)
7. **Director Notes**: Beneath the table, provide a short bulleted list of Director Notes describing the delivery.
8. **Phase Ending**: Always conclude Phase 1 with the exact phrase:
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

## 📦 Resource Manager & Pronunciation Validation

Before rendering any script, the director must execute the **Resource Checker** logic:
1. **Pronunciation Scanner**: Scan the script for complex mythological or foreign terms/names (e.g., *Zhulong, Shan Hai Jing, Taotie*). Cross-check them against the local dictionary in `assets/pronunciation/`. If a term is missing or marked `verified: false`, flag it as `🔴 REQUIRED` and generate a suggested phonetic spelling.
2. **SFX/Ambience Matcher**: Map requested SFX intents against `assets/sfx_manifest.yaml` using tags and intensity. If a sound is missing, classify it by severity:
   - `🔴 REQUIRED`: Narrator voice profile, critical name pronunciations.
   - `🟡 RECOMMENDED`: Critical SFX/Transitions (`necessity > 0.80`) like risers or thematic wind.
   - `⚪ OPTIONAL`: Ambient layers or music (`necessity < 0.65`).
3. **Voice Profile Check**: Validate that `voice-profile.yaml` exists for the designated narrator character.

If any `🔴 REQUIRED` resources are missing, the rendering phase is **BLOCKED**. The agent must output a **Missing Resource List (Shopping List)** containing:
* The name and purpose of the missing asset.
* A bulleted list of search keywords (e.g., *cinematic tension riser, cold wind transition*).
* Preferred duration, intensity, and style preferences.

---

## ⚙️ Orchestration with Chatterbox API

Once the directing plan is finalized and all `🔴 REQUIRED` assets are ready, render the voiceover using the Projects API:

1. **Initialize Project**: Call `/api/v1/projects/prepare` with the topic.
2. **Set Requirements**: Configure format as `video_narration` or `audiobook` with English language.
3. **Submit Directed Script**: Call `/api/v1/projects/{project_id}/confirm-script` passing the compiled text with formatted inline pauses and scene boundaries.
4. **Render**: Trigger rendering through `/api/v1/projects/{project_id}/render`.

