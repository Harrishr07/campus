# Roadmap and task board (22 October 2026)

Replaces the remaining order of phases 3-5. Done work stays as is. New requirements come from BRD section 16 (v0.2).
State at start: branch `phase-1` HEAD 2db5547. Phase 1 done, Phase 2 25/26, Phase 3 14/22.

Lanes (unchanged): A = campus-test (examinations), B = campus-test2 (admissions, lifecycle, IQAC/OBE), C = campus-test3 (research, finance).
Model: Opus for money, student data and security; Sonnet elsewhere. Every task: implementer -> review -> fix rounds (Critical/Important only) -> re-review.
Status: `todo`, `ready` (fix write-up exists), `blocked` (needs user decision).

## Wave 0 - Stabilise (start here)

Goal: close every open fix round, fix the defects the external review confirmed, and get one clean full suite. Tag `p2-done` at the end.

| ID | Task | BRD | Lane | Model | Status | Done when |
|---|---|---|---|---|---|---|
| R-01 | P3-T07 feedback privacy fix round 3 (residual 500 paths) | M01-05 | B | Opus | ready | Re-review passes; no Error Log can hold answers with a user |
| R-02 | P3-T18 PFMS fix round 3 (any change after export -> held for review) | M08-07 | C | Opus | ready | Re-review passes |
| R-03 | P3-T19 closure fix round 2 (recognition cancel on closed grant, PE deductions on cancel) | M08-08 | C | Opus | ready | Re-review passes |
| R-04 | P2-T26 prerequisites evaluated from published results, transfers, waivers | M03-07 | A | Opus | todo | Unmet prerequisite holds the registration with a reason |
| R-05 | Course registration bound to its own enrollment; cumulative term credits; deadline on amendments | M03-08 | B | Sonnet | todo | Apply/cancel never touch another enrollment; tests for two enrollments |
| R-06 | Seat matrix strict mode (missing row blocks unless logged override) | M04-08 | B | Opus | todo | Missing-row admission refused; override logged; intake unchanged |
| R-07 | Mandatory approval list (no matching policy blocks submit for listed doctypes) | NFR mandatory approval | B | Opus | todo | Listed doctype without a policy cannot submit; others unchanged |
| R-08 | Result run pre-validation (course type and rules complete) | M06-12 | A | Opus | todo | Run refuses with the list of incomplete courses |
| R-09 | campus-test data: clear stale payroll seed and leaked fee structures, or rebuild the site | - | coordinator | - | blocked (user) | Payroll and fee tests green |
| R-10 | Full suite on a quiet tree, triage, tag `p2-done` | - | coordinator | - | todo | Suite green except listed known issues |

## Wave 1 - Student lifecycle hardening (new, Phase L)

Goal: the admission-to-alumni spine is correct and auditable. Runs mainly in lane B.

| ID | Task | BRD | Depends | Lane | Model | Size |
|---|---|---|---|---|---|---|
| L-01 | Lifecycle state model: statuses, permitted transitions, effective dates, transition log | M05-09 | Wave 0 | B | Opus | M |
| L-02 | Joining confirmation gate: admission approval no longer creates enrollment/invoice; Joining Confirmation creates Program Enrollment, invoice, ID, attendance start; pre-joining advance; idempotent retry | M04-09 | L-01 | B | Opus | L |
| L-03 | Reporting deadlines, temporary clearance, late joining, no-show referral to cancellation/refund | M04-10 | L-02 | B | Sonnet | M |
| L-04 | Bulk candidate upload with preview and row outcomes; duplicate candidate detection and link review | M04-06, M04-07 | Wave 0 | B | Opus | M |
| L-05 | Lateral entry: program rules, intake, entry semester, curriculum mapping, waivers/bridge courses, remaining credits | M04-11, M03-09 | L-02 | B | Opus | M |
| L-06 | Discontinuation, readmission, semester reallocation/repeat (extends P2-T21 rejoin) with curriculum matching and fee adjustment | M05-10 | L-01, L-05 | B | Opus | L |
| L-07 | Attendance start date per enrollment; session states (conducted, cancelled, rescheduled, makeup); on-duty/leave treatment; correction approval | M05-12 | L-02 | A | Opus | M |
| L-08 | Student record correction workflow and student 360 view with role-scoped sections | M05-11, NFR history | L-01 | B | Sonnet | S |
| L-09 | Mentoring notes restricted; parent interaction records | M05-13 | - | C | Sonnet | S |

## Wave 2 - Exams, completion and records (new, Phase X)

Goal: affiliated colleges can use the exam side, and completion produces correct official records. Runs mainly in lane A.

| ID | Task | BRD | Depends | Lane | Model | Size |
|---|---|---|---|---|---|---|
| X-01 | Affiliated mode: university exam registration export, result import with row validation, acknowledgements | M06-10 | Wave 0 | A | Opus | L |
| X-02 | Improvement exams; former-student arrear registration within attempt and duration rules | M06-11 | X-01 | A | Opus | M |
| X-03 | Completion: credit completion, study-completed vs award-eligible, degree-authority validation, alumni transition | M05-15 | L-01 | A | Opus | M |
| X-04 | Certificate correction, supersession and reissue; TC status change via lifecycle approval | M05-14 | L-01 | A | Sonnet | S |
| X-05 | ABC/NAD export file with identifier mapping, validation, correction tracking | M17-08 | X-03 | A | Opus | M |
| X-06 | Official document register with validity and expiry alerts (extends P3-T08 regulator tracker); AISHE dataset | M01-08, M01-09 | - | B | Sonnet | M |

## Wave 3 - Finish Phase 3

| ID | Task | BRD | Depends | Lane | Model | Size |
|---|---|---|---|---|---|---|
| P3-T10 | Attainment policy and runs (direct + indirect, versioned policy, input snapshots) | M03-03 | P3-T09 | B | Opus | L |
| P3-T11 | Course plan and adherence; add syllabus coverage linked to conducted sessions (L-07) | M03-03, M05-12 | L-07 | B | Sonnet | M |
| P3-T20 | Consultancy | M08-10 | Wave 0 | C | Opus | M |
| P3-T21 | IPR and publications | M08-11, M08-12 | - | C | Sonnet | M |
| P3-T22 | Research reports and data points | M08-12 | T20, T21 | C | Sonnet | S |

## Wave 4 - Campus operations (Phase 4, extended)

Existing P4-T01 to P4-T14 stay in order. Added:

| ID | Task | BRD | Lane | Model | Size |
|---|---|---|---|---|---|
| P4-T15 | Student projects: teams, guides, reviews, submission, viva, marks transfer; industrial visits | M14-07 | A | Sonnet | M |
| P4-T16 | Confidential cases: anti-ragging, internal complaints, disciplinary, with restricted access and higher review | M01-06a | B | Opus | M |
| P4-T17 | Activities (clubs, NSS/NCC, sports, events) and achievements | M05-08a | C | Sonnet | S |
| P4-T18 | Concession model v2 (subhead, semester, sub-types, order, caps) | M09-07 | C | Opus | M, blocked until pilot policy confirmed |

## Wave 5 - Extend and go-live (Phase 5, reordered)

Pulled forward to run before any pilot go-live: P5-T15 Migration toolkit and P5-T18 Production hardening (backup/restore drill, role-permission matrix review, acceptance testing).
The rest of Phase 5 keeps its order. P5-T09 DigiLocker/NAD/ABC now covers the API only; the file export is X-05.

## Lane plan at restart

| Lane | First | Then |
|---|---|---|
| A (campus-test) | R-04, R-08 | L-07, X-01 to X-05 |
| B (campus-test2) | R-01, R-05, R-06, R-07 | L-01 to L-06, L-08, X-06, P3-T10, P3-T11 |
| C (campus-test3) | R-02, R-03 | L-09, P3-T20 to P3-T22, Phase 4 finance items |
| Coordinator | R-09 (after user decision), R-10 | Full suite after each wave |

## Decisions needed from the user

1. R-09: delete the stale payroll seed records and leaked fee structures on campus-test, or rebuild the site.
2. L-02 changes the Phase 1 Admit flow (enrollment and invoice move to joining). Confirm.
3. P4-T18: concession policy values from the pilot college.
4. Pending values in `docs/rulings.md` (regulation seeds, quorums, TA/DA TDS, CIA rounding, honours credits, revaluation window).

## Reorder for pilot readiness (22 October 2026, user decision)

Goal: put the core path in front of one pilot college before adding more modules. New breadth stops once the work in flight lands. Deferred tasks keep their place in the waves above and resume when the pilot asks for them.

### Finish in flight (no new scope)
X-01 affiliated exam mode, L-02 joining gate, X-03 completion, X-04 certificate reissue, L-08 record corrections and student 360, P4-T08 labs. Open fix rounds: P3-T10 (fix 2), P3-T20, L-09 (fix 3), P4-T13.

### Kept for the pilot (core path)
- L-07 attendance start date and session states (attendance is core).
- L-03 reporting deadlines, late joining, no-show (admission season).

### Deferred until after the pilot
- Lifecycle: L-05 lateral entry, L-06 discontinuation / readmission.
- Exams: X-02 improvement exams, X-05 ABC/NAD export file.
- Phase 3: P3-T11 course plan, P3-T22 research reports.
- Phase 4: P4-T02 to T07 (hostel allotment, mess, outpass, hostel operations, transport, GPS), P4-T09 to T12 (consumables, experiments, facility booking, nursing), P4-T14 to T18 (offers, projects, confidential cases, activities, concession v2).
- Phase 5: all, except T15 migration and T18 hardening, which move into Wave P.

### Wave P - Pilot readiness

| ID | Task | Done when |
|---|---|---|
| R-10 | Full suite on a quiet tree, triage, tag `p2-done` | Suite green except listed known issues |
| PR-01 | Navigation sweep: every DocType and report has one home; one workspace per role | test_navigation green; each role sees only its areas |
| PR-02 | Pilot setup kit: idempotent seed (trust and college companies, academic year and terms, programmes, regulations, fee structures, roles, users) and master-data import templates | A fresh site is configured for a college in one run, re-runnable |
| PR-03 | SXCCE demo dataset and migration toolkit: a generated, realistic but synthetic dataset for St. Xavier's Catholic College of Engineering (autonomous, Anna University affiliation; B.E./B.Tech programmes, R2022 regulation, two batches, faculty, fee structures, a term of attendance, CIA, ESE and results), loaded through the same import path a real college would use (dry run, row outcomes, re-import changes nothing) | One command loads the demo on a fresh site; every role has something to do |
| PR-04 | Core path end-to-end test on a fresh site: enquiry, admission, joining, fee payment, timetable and attendance, CIA, exam registration and hall ticket, valuation, result, certificate; then AQAR and AISHE exports from that data | One automated test passes from start to finish |
| PR-05 | Production hardening (from P5-T18): role-permission matrix review, backup and restore drill, developer mode and telemetry off, scheduler, email and WhatsApp checks, Error Log watch | Checklist signed off on the staging site |
| PR-06 | Role guides: short how-to per role (office, faculty, HOD, COE, accounts, student and guardian portal) in docs/usage | One page per role, matching the screens |
| PR-07 | Staging site `campus.localhost` (new; developer mode, telemetry and request recorder off) set up with the kit and the SXCCE demo dataset; demo walkthrough script for the SXCCE presentation | The presentation runs end to end on campus.localhost |
| PR-08 | Intern UAT: test accounts per role on campus.localhost, a UAT script per role, and in-app feedback capture (role, steps, expected vs actual, severity, screenshot) into a tracked list | Interns can run every script and file feedback the coordinator can triage |

### Decisions (22 October 2026)
- Pilot audience: St. Xavier's Catholic College of Engineering (SXCCE). No real college data yet, so the demo runs on a generated synthetic dataset (PR-03).
- Staging: a new site `campus.localhost` (PR-07), created once the tree is quiet after R-10.
- UAT: an intern team runs the scripts (PR-08).
- PR #2 is marked ready for review once the work in flight and its fix rounds are approved and R-10 is green.

### Needed from the user
Razorpay sandbox test, mobile UAT, official regulator templates (AISHE, university exam formats), confirming the pending values in docs/rulings.md, the presentation date with SXCCE.
