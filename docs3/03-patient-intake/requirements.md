# Patient intake: requirements

**For:** new patients applying online, and the reception / clinical staff who review them.
**Manual:** §5.1 (six steps), §5.2 (booking), §5.4 (applications queue, briefing note), §3.5, §12.3.
**Builds on:** the public booking page `/book/<clinic-slug>` and `patients.match_or_create_for_booking`
(`docs2/sdlc/04-calendar-and-booking`).

## User stories

- As a new patient, I apply on my phone in about two minutes: about me, health, history, consents,
  pharmacy and a signed declaration — then pick a time with a doctor.
- As reception, I see every new application in one queue with its flags, and accept or reject it with a reason.
- As a doctor, before the first consult I read a one-glance briefing built from the patient's own answers.
- As the practice, I can prove which version of each consent a patient agreed to, and when.

## Requirements

### The public application (six steps)

| # | Requirement | Manual |
|---|---|---|
| R1 | `/book/<clinic-slug>` becomes a **six-step application** followed by the existing slot picker. One step per screen with progress; required fields gate the next step; back keeps answers in memory only (never in the URL or storage) | §5.1 |
| R2 | **Step 1 · About you:** given name, family name, date of birth, sex, mobile (AU), email, street address (line, suburb, state, postcode). Under 18 → **hard stop** with a plain explanation; no data is sent | §5.1 |
| R3 | **Step 2 · Health screen:** primary condition (closed list kept by the clinic), secondary conditions as tags, current medicines, and the safety questions. The manual does not list them; the question set is **proposed by the Clinical Safety Officer** before build (e.g. psychosis history, pregnancy / breastfeeding, heart condition). A "yes" is a **soft flag** for the doctor, never a stop | §5.1 |
| R4 | **Step 3 · Cannabis history:** used before (y/n); forms used, how long, side effects, what felt effective — all optional free choice lists (D5) | §5.1 |
| R5 | **Step 4 · Consents:** privacy (APP 5 collection notice), telehealth, treatment. Each shows its **current published version**; each must be ticked. The THC driving advice is part of the treatment consent | §5.1, §12.3 |
| R6 | **Step 5 · Pharmacy:** partner pharmacies first (clinic's directory, name and suburb only); or "my own pharmacy" with a caution and name, suburb, email, phone, address, provider number | §5.1, §8.1 |
| R7 | **Step 6 · Declaration:** the patient types their full name; it must match step 1 (case- and space-insensitive). Stored with the server timestamp | §5.1 |
| R8 | **No product or brand names** anywhere on the public page, including suggestions, examples and errors. Pricing shows the consult fee from clinic settings only when configured | §5, App. C |
| R9 | On submit the patient sees "Intake complete — choose a time" and the **existing** slot picker. The booking and the application are one submission (one transaction); payment is not taken (D7b) | §5.2 |
| R10 | One answer for every outcome a stranger could probe: an existing patient, a duplicate application and a new one all see the same confirmation (no enumeration) | D-008 pattern |
| R11 | Rate limited per address as the booking page is today; CAPTCHA only if D7f is approved | |

### Inside the clinic: the applications queue

| # | Requirement | Manual |
|---|---|---|
| R12 | **Patients → Online applications** lists `SUBMITTED` applications oldest first, with flags as chips. Visible to `patient:create` holders; doctors see it read-only | §5.4 |
| R13 | Each card opens the full answers, the held appointment (if any) and the duplicate check: the patient record it matched or created (`match_or_create_for_booking`, D6) | §5.4 FAQ |
| R14 | **Accept** (`patient:create`): in one transaction — sets the patient `CURRENT` (feature 04); records each consent against the version signed; files the declaration; sets the preferred pharmacy, adding an own-pharmacy to the directory; fills sex and address on a **new** record only (an existing record is never overwritten by a public form); creates the **intake briefing note**; marks the application `ACCEPTED`. Audited | §5.4 |
| R15 | **Reject** (`patient:create`) requires a reason from a closed list plus free text; cancels the held appointment; marks the application `REJECTED`; a patient record created by this application becomes `ARCHIVED` with the reason. Audited. The patient is told by email in neutral words, with no clinical reason | §5.4 |
| R16 | An application cannot be decided twice (`409`). Applications are never deleted | App. C |
| R17 | The **intake briefing note** shows: presenting condition and tags · what has been tried · current medicines and safety flags · cannabis history · pharmacy choice · the signed declaration. **No range suggestion in Phase 5** (D11). Visible only to holders of `clinical_record:read` with a care relationship (D-007); shown on the patient record and the Today schedule | §5.4 |

### Consent versions

| # | Requirement | Manual |
|---|---|---|
| R18 | `tenant:configure` holders publish consent documents per kind (`PRIVACY`, `TELEHEALTH`, `TREATMENT`); each publish is a new immutable version | §12.3 |
| R19 | A patient's consent records the exact version, how (online application / in clinic) and when. Publishing a materially changed version flags every patient on the older version for **re-consent** (a chip on the record) | §12.3 |
| R20 | A clinic with no published version of a required kind **cannot accept applications** — the public page shows "Online applications are not open yet" (fail closed) | |

## Out of scope

Payment at booking (D7b), the returning-patient SMS portal (D7a), range suggestions (D11), forms and
instruments beyond the six steps (Phase 6), xlsx import (Phase 9).
