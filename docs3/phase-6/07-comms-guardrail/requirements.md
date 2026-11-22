# Communications guardrail: requirements

Australian law restricts advertising prescription medicines, including medicinal cannabis, to the
public (Therapeutic Goods Act; Therapeutic Goods Advertising Code). The roadmap asks that banned
product and brand terms are blocked on bulk sends **(manual §11: confirm)**. Whether a given message
is advertising is **REQUIRES LEGAL/REGULATORY VALIDATION**; this feature enforces a list, it does not
make that judgement.

| ID | Requirement | Source |
|---|---|---|
| R1 | A blocked-terms list (platform list plus a clinic's additions) is checked on every patient-facing template before it is saved: booking emails today, consent text (06), clinic forms (05), and campaigns when they exist | roadmap; D23 |
| R2 | A match refuses the save and names the term and where it appears; there is no override in the product | roadmap |
| R3 | Matching is case-insensitive and whole-word, and also catches simple spacing and punctuation evasions | — |
| R4 | Changing the list needs `tenant:configure` with step-up and is audited | build contract |
| R5 | Bulk sends, when built (Phase 9), cannot send a message that did not pass the check | roadmap |

Owner of the list's content: Compliance Lead (D23).
