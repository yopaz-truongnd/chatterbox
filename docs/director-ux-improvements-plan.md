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
| A1 | Advanced options section in create form (auto_accept_qc_pass, mixing/mastering profile, retry_budget, allow_resource_substitute) | Script creation flow | TODO | These policy fields already exist on the backend (`WorkflowPolicy`) but are only reachable via raw API calls today |
| A2 | Script preview + character count before submit | Script creation flow | TODO | Script is immutable once the workflow starts; typos currently mean starting over |
| B1 | Fix misleading attempt "da chon" label vs. real approval | Director Console / review gate | TODO | Root UX cause behind the ISSUE-0005 confusion: selection and explicit approval look identical in the UI |
| B2 | Toast feedback when an action has no effect (e.g. resume blocked by an unmet gate) | Director Console | TODO | Currently silent; user has no way to tell why nothing happened |
| B3 | Per-beat render progress detail | Director Console | TODO | Scope to what the existing job data can show (current beat / attempt), not a new ETA subsystem |
| B4 | Bulk "Bo qua tat ca" for recommended resource gaps | Director Console / resource gate | TODO | Today each recommended gap must be skipped one at a time |
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
