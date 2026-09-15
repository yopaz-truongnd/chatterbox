# Director Console UX Improvements Plan

Tracking document for the Director Console + script-creation-flow UX pass proposed
on 2026-09-16, after hands-on testing of the whole production pipeline (see
`docs/known-issues.json` ISSUE-0001..0005 for the bugs found during that same pass).

## Scope

- Branch: `feature/director-ux-improvements`
- Target page: `webui/material_dashboard.html` (`#director-console`) and its
  create-project form
- Backend changes only where needed to expose data the UI already has a use for
  (no new product surface beyond what's listed below)

## Status

Use one status per item: `TODO`, `IN PROGRESS`, `DONE`, `SKIPPED` (with reason).

| # | Item | Area | Status | Notes |
|---|---|---|---|---|
| A1 | Advanced options section in create form (auto_accept_qc_pass, allow_resource_substitute, mastering_profile, retry_budget) | Script creation flow | DONE | Collapsible `<details>` section. Skipped exposing `mixing_profile` -- `rules/mixing.yaml` only defines one profile, a dropdown would be meaningless until more are added. Verified live: submitted with `auto_accept_qc_pass=false` + `mastering_profile=podcast`, API echoed both correctly. |
| A2 | Script preview + character count before submit | Script creation flow | DONE | Live char/word counter under the textarea + toggleable preview panel. Verified live: "69 ky tu . 12 tu" matched typed text exactly. |
| B1 | Fix misleading attempt "da chon" label vs. real approval | Director Console / review gate | DONE | Button now shows 3 distinct states: neutral (not selected), amber "can duyet" (selected but status != passed), green "check da duyet" (status == passed). Verified live: amber before click, flipped to green + API status changed needs_review->passed after clicking. |
| B2 | Toast feedback when an action has no effect (e.g. resume blocked by an unmet gate) | Director Console | DONE | resumeDirectorWorkflow() now polls (up to 6x700ms) for the settled state instead of trusting the immediate HTTP response, which fires before the background re-check runs. First implementation was itself wrong (compared the immediate response, giving a false "success" toast) -- caught and fixed during live verification. Verified live both ways: warning toast when bouncing back to the same gate unresolved, success toast (workflow ran to completion) after actually approving first. |
| B3 | Per-beat render progress detail | Director Console | TODO | Scope to what the existing job data can show (current beat / attempt), not a new ETA subsystem |
| B4 | Bulk "Bo qua tat ca" for recommended resource gaps | Director Console / resource gate | DONE | Bulk button appears when 2+ skippable (non-required) gaps exist. Found and fixed a real concurrency bug during live verification: firing the omit requests in parallel raced multiple writers against the same project.yaml, failing with "[WinError 5] Access is denied" on Windows' atomic rename -- one of two omits silently lost. Fixed by running sequentially; applied the same fix to the pre-existing bulk pronunciation-confirm button, which had the identical latent bug. Verified live: 2/2 gaps omitted correctly after the fix (0 remaining), vs. 1/2 before. |
| B5 | Search box in the production list | Director Console | TODO | Helps once the list is long; filters already added in a prior pass |

## Non-goals

- Rebuilding the "idea-to-script" (two-gate) creation flow -- out of scope for this pass.
- A full progress/ETA subsystem with time estimates -- B3 is scoped to showing which
  beat/attempt is in flight, not predicting completion time.
- A new "development plan" tab inside the app itself -- this markdown file is the
  tracking surface instead, consistent with how `docs/known-issues.json` already
  tracks bugs found during this same session.

## Change log

- 2026-09-16: Plan created, all items TODO.
- 2026-09-16: A1 and A2 done and verified live against the running server.
- 2026-09-16: B1 done and verified live against the running server.
- 2026-09-16: B2 done; first attempt had a bug (false success toast) caught by live verification and fixed before commit.
- 2026-09-16: B4 done; live verification caught a Windows file-write race condition in the bulk-omit (and pre-existing bulk pronunciation-confirm) buttons, fixed by running sequentially instead of in parallel.
