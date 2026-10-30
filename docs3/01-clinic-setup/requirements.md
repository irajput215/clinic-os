# Clinic setup: requirements

**For:** the Practice Owner (and anyone holding `tenant:configure`) in a newly verified clinic.
**Manual:** quick-start "Practice manager — your first hour"; §15.1; §15.5 "Settings".

## User stories

- As a Practice Owner who has just verified my signup, I see what to do next instead of an empty Today.
- As a Practice Owner, I can tell at a glance which setup steps are done, and jump straight to each one.
- As a Practice Owner, I set who in my practice may stage script drafts, and how long records are kept.
- As staff without `tenant:configure`, I never see the setup checklist.

## Requirements

| # | Requirement | Manual |
|---|---|---|
| R1 | A **setup checklist** card appears at the top of Today for holders of `tenant:configure` until every required step is done. It can be collapsed per person; it cannot be marked done by hand | Quick-start PM |
| R2 | The steps, in order. Each is **derived from live data**, never a stored tick: | |
| | 1. Clinic name — `tenants.display_name` set *(required)* | §15.5 |
| | 2. Opening hours and slot length — an `appointment_settings` row exists *(required)* | §4.4 |
| | 3. Review the permission grid — the owner has opened Admin → Roles at least once (from the audit log) *(optional)* | §15.1 |
| | 4. Invite your team — at least one other active or invited account *(required)* | §15.2 |
| | 5. Prescribers ready — at least one prescriber whose onboarding pack is complete (feature 02) *(required)* | §15.2 |
| | 6. Practice workflow — R4 saved at least once *(required)* | §15.5 |
| | 7. Consent documents — a published version of each required consent (feature 03) *(required)* | §5.1, §12.3 |
| | 8. Share your booking page — shows the public link and copy button *(optional)* | §1.2 |
| | 9. Integrations — eScripts, Medicare, address search, SMS: each shown **"Not connected — awaiting approval"** until its vendor is approved (decisions D7) *(informational)* | §15.3 |
| R3 | Each step links to the screen where it is done. The card shows "N of M required steps done" | |
| R4 | **Practice workflow settings** (Settings → Practice): who may stage drafts — Nurse (default), Doctor, Reception (with product suggestions kept as notes, never selections) | §6.3, §15.5 |
| R5 | **Retention years** (Settings → Practice): adults ≥ 7 years; minors per policy (read-only "until age 25"). Shown and stored; enforcement is a later phase. Nothing is ever hard-deleted | §15.5, App. C |
| R6 | Saving R4 or R5 requires `tenant:configure`, is audited (`tenant.settings_updated` with before/after), and is refused for everyone else with `403` | INV-3, INV-4 |
| R7 | When every required step is done, the card is replaced once by "Your clinic is ready" with a link to the role quick-starts (feature 02 R3), then disappears | |

## Out of scope

Session rates and pay periods (Phase 8); Switch Kit and xlsx import (Phase 9); live integration setup
(decisions D7).
