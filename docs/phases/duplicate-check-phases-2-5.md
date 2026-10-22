# Duplicate check: Phases 2-5 (2026-10-06)

Checked the ~170 DocTypes planned in phase-2.md … phase-5.md against every DocType installed on education.localhost (frappe, erpnext, hrms, education, india_compliance, frappe_whatsapp, campus).

## Exact name matches: all are thin-slice DocTypes we built (reuse and extend, never recreate)
| Planned in | Already built (slice) | What the phase task becomes |
|---|---|---|
| P2-T12 Exam rule engine | Exam Rule Set, Grading Scheme, examinations/rules.py | Extend: attempt-aware pass clauses, relative (Box-Cox) grading, online-course table, Classification Rule. |
| P2-T14 / P2-T19 Sessions, results | Exam Session, Mark Sheet Entry, Student Result, Result Run (POST + bulk) | Extend: registration, hall tickets, CIA templates, moderation, versioned results. Mark Sheet Entry stays the ESE/CIA entry point; CIA Mark Entry becomes question-wise detail on it rather than a parallel DocType. |
| P2-T22 Grade sheets | Grade Sheet print + Verifiable Document | Add consolidated sheet / provisional / transcript prints only. |
| P3-T01..T03 IQAC engine | Accreditation Framework, Framework Node, Accreditation Cycle, Metric Value, `@campus_metric` registry | Extend: evidence slots, clone/publish lock, overrides with approval. "Data Point" DocType = sync of the existing registry (no second registry). |

## Names that collide in meaning or confuse with upstream: rename or reuse
| Planned | Upstream | Ruling |
|---|---|---|
| Journal (P3-T12) | ERPNext Journal Entry family | Rename **Indexed Journal**. |
| Route (P4-T06) | Website Route*, Route History | Rename **Transport Route** (and Route Change Request → Transport Route Change). |
| Meeting / Action Item (P2-T02) | ERPNext Quality Meeting (+Agenda, Minutes) — tied to Quality Review | Keep own **Body Meeting** (governance quorum/resolutions don't fit Quality Meeting); rename to avoid "Meeting" ambiguity. Action Item → **Meeting Action Item**. |
| Progress Report (P3-T19) | ERPNext Project Update | Reuse **Project Update** for project progress; no new DocType. |
| Feedback Form/Campaign/Response (P3-T07) | ERPNext Quality Feedback (+Template), HRMS Training Feedback | Keep own (anonymity + CO links aren't supported upstream); names don't clash. |
| Exam Hall (P2-T16), Laboratory (P4-T08), Facility Booking (P4-T11) | education Room | Reuse **Room** with `oc_room_type` + layout fields; Laboratory links a Room (no separate room master). |
| Faculty Achievement (P2-T09) | HRMS Training Event / Employee Skill Map | Keep Faculty Achievement for non-training items; FDP attendance stays in Training Event (link, don't copy). |
| Vehicle, Driver, Vehicle Log (P4-T06) | ERPNext/HRMS | Reuse (already planned). |
| Sanction → Project/Cost Center/Budget (P3-T14) | ERPNext | Reuse (already planned). |
| Hostel complaints (P4-T05) | ERPNext Issue | Reuse Issue (already planned). |
| Donation (P5-T03) | none in v16 | New. |

## Process
Before each phase starts, run this same check (script: compare planned names with `frappe.get_all("DocType")` plus a semantic review) and update that phase doc. Every task brief carries the "no duplicate DocTypes" constraint.
