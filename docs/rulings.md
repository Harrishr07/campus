# Rulings made during autonomous execution

## Phase 1 (/workspace/.superpowers/sdd/phase-1/progress.md)
- | T01 | Says "base test class with demo-data loader" but the demo builder is T02. Ruling: T01 provides a base class with a hook (no-op loader) that T02 fills. |
- | T05 | "approving resolution link (filled in Phase 2)": Resolution doctype doesn't exist yet. Ruling: Data field `approving_resolution` now, converted to Link in Phase 2 by patch. |
- | T10 | Push channel "optional". Ruling: implement adapter interface + email/SMS/WhatsApp; push adapter stub only. |
- | T25 | Razorpay: real sandbox credentials unavailable. Ruling: mocked gateway in tests; sandbox UAT left for user. |
- - Ruling: execution order T01, T03, T04, T05, T06, T02, T07, T08, T09, T10, T11, T12, T13, T14, T23, T15, T16, T17, T18, T19, T24, T25, T20, T21, T22, T26, T27, T28 — dependencies stated in the plan require it — cost if wrong: none (numbering only).
- - Ruling: T03 skips `oc_company` on Fee Schedule and uses its existing `company` field — avoids a duplicate company field — cost if wrong: one extra field to add later.
- - Ruling: T01 base test class has an overridable demo loader hook; T02 implements it — keeps T01 small — cost if wrong: trivial refactor.
- - Ruling: T05 `approving_resolution` is a Data field until Phase 2 adds Resolution — no target doctype exists yet — cost if wrong: one patch in Phase 2.
- - Ruling: T10 push channel is an interface stub only — plan marks push optional — cost if wrong: small adapter later.
- - Ruling: T25 gateway tests use mocks; real sandbox UAT is the user's — no sandbox credentials — cost if wrong: gateway bugs found at UAT.
- - Ruling: parallelism — implementers run one at a time (shared bench, site, DB and git repo; parallel migrations would corrupt state). Parallelism used where safe: the task reviewer for task N runs while the implementer for task N+1 works, when N+1 doesn't build on code N's review could change — cost if wrong: a fix round on N may need rebasing onto N+1's commits.
- - Ruling: work on branch `phase-1` of the new campus repo; `main` holds only the bench-generated scaffold commit — new repo, no shared branch — cost if wrong: none.
- Ruling: T04 moves generic test helpers (make_company, make_user) from test_company_scope.py to campus/tests/factories.py — every later task needs companies/users; avoids copy-paste — cost if wrong: small merge conflict if a T03 fix round edits the same test file.
- Ruling: T04 ambiguity — degree_awarding_body default University, provisional_certificate_issuer default College; pack→status rules stored on Module Pack; COE/GOVERNANCE allowed Autonomous/Deemed — D11 + blueprint 2.4 — cost if wrong: config change.
- Ruling: custom fields on upstream doctypes are defined in code via create_custom_fields (ERPNext/india_compliance idiom), not exported fixture JSON — the back-fill patch needs the fields before fixture sync runs in migrate — cost if wrong: switch to fixtures later. Global constraints updated.
- Ruling: T03 criterion 1 "reports" — no Phase 1 reports exist yet; standard report views are covered by Frappe User Permission on the oc_company Link; each later script report must filter by company (carried as a constraint) — cost if wrong: a later report leaks across companies (caught by reviews).
- Ruling: T04 pack toggling = navigation visibility via boot_session filter (not access control); data access stays with DocType role permissions plus controller pack_enabled() checks — brief asks for visibility only — cost if wrong: add Workspace role restriction later.
- Ruling: T04 Module Pack seeds as idempotent after_install/after_migrate code, not a fixture file — consistent with the custom-field ruling; never overwrites edits — cost if wrong: none.
- Ruling: T05 regulation resolution = latest Effective regulation of the student's company covering the program with effective-from Academic Year ≤ batch year; oc_batch links Academic Year; regulation change only via whitelisted change_regulation (Dean Academics) — brief + blueprint 2.5 — cost if wrong: resolution query change.
- Ruling: T06 role sync only revokes roles it granted (tracked), never manual roles; Hostel/Body/Lab scopes stored as Data until those doctypes exist — avoids clobbering admin role setup — cost if wrong: migration of scope fields later.
- Ruling: keep working on local branch phase-1, never push; user decides merge/push at finish — pushing to a shared remote is outside this loop's authority — cost if wrong: user merges phase-1 into main themselves.
- Ruling: T02 "small" scale = 10 students per program for 2026-27 only; "full" = 60 per program per batch 2022-23..2026-27; quota skipped until T14 adds the field — keeps tests fast (<60 s) while meeting the README data set at full scale — cost if wrong: extend builder later.
- Ruling: Regulation document name must be unique per company, not global — a trust's colleges each have "R2022" — name = "{code}-{company abbr}" (code field stays the user-facing code, unique per company); existing records renamed by patch; cost if wrong: one more rename later. Assigned to the T02 implementer as an extra commit (load-bearing for every rule lookup), reviewed with T02.
- Ruling: T07 notifications go through one internal notify() helper (email/system notification) until T10 replaces it; approval applies to submittable doctypes only; escalation adds approvers once — brief + blueprint — cost if wrong: helper swap in T10.
- Ruling: T08 QR macro shows an existing Verifiable Document only (issuing via issue(), never during print render) and hash falls back to rendered HTML if PDF bytes aren't deterministic — avoids hash recursion and flaky hashes — cost if wrong: re-issue mechanism change.
- Ruling: self-approval is not allowed in the approval engine — separation of duties for an accreditation/audit product — cost if wrong: add a per-policy allow flag.
- Ruling: T07 trail rendered via form dashboard section (not sidebar) accepted — brief says "form sidebar shows trail"; dashboard section is the v16 idiom and equally visible — cost if wrong: small JS move.
- Ruling: T07 notify() fallback via system Notification Log (email subject to user settings) accepted until T10 messaging — cost if wrong: missed emails pre-T10 (no production use yet).
- Ruling: T10 consent default — transactional allowed without a record, promotional requires explicit opt-in (DPDP-friendly); push = stub; WhatsApp via frappe_whatsapp "WhatsApp Message" with status sync hook; notify() routes through messaging when "approval.notification" template exists — cost if wrong: consent default flip is a config change.
- Ruling: T10 multiple documented recipient formats accepted (relaxes "one format"); extra send(now=False) param accepted — useful, harmless — cost if wrong: none.
- Ruling: T11 Hostel/Route audience types declared but raise "not available until Phase 4"; Broadcast + Circular use ApprovableDocument (approval only when a policy matches) — modules don't exist yet — cost if wrong: none, Phase 4 adds resolvers.
- Ruling: T12 credit rule + total-credit range live on a new "Curriculum Rule" doctype linked to Regulation (resolved via get_rule) — "regulation values are records" — cost if wrong: field move later.
- Ruling: Circular Acknowledgement unique per (circular, user) accepted — brief's "party" maps to the acknowledging portal user — cost if wrong: shared-user households collapse to one ack.
- Ruling: T12 "Superseded" status accepted — needed so v(n+1) can become Effective without editing a locked Effective record — cost if wrong: none.
- Ruling: Curriculum looks up Curriculum Rule by regulation directly (not get_rule) — get_rule resolves via a student; curricula have no student — cost if wrong: none.
- Ruling: T13 registration limits live on a regulation-linked "Registration Rule" (36/6/30/5/6/2/10 for R2022); prerequisites stubbed via campus.curriculum.api.prerequisites_met until Phase 2 — "regulation values are records" — cost if wrong: field move.
- Ruling: T13 no seeded Approval Policy for Course Registration — a policy with unresolvable approvers would block every registration; colleges configure it — cost if wrong: one fixture later.
- Ruling: T14 round 2 also adds internal copy_aadhaar() helper — P1-T16 needs a sanctioned gated copy path; doing it now keeps all Aadhaar code reviewed together — cost if wrong: none.
- Ruling: Aadhaar access log written on a separate DB connection, committed immediately, failing closed — only robust durability against caller rollback — cost if wrong: one extra connection per reveal (rare action).
- Ruling: bank import runs with chunk=1 so each row's invoice lock precedes ERPNext's plain outstanding reads — closes the internal stale-snapshot gap without changing ERPNext — cost if wrong: slower imports (acceptable for bank files of hundreds of rows).
- Ruling: T15 quota/category with no Seat Matrix row is not enforced — colleges configure only the rows they control; documented — cost if wrong: one-line strict switch.
- Ruling: T16 admit = one transaction (savepoint rollback on failure) with copy_aadhaar as the only Aadhaar path; register numbers via Frappe naming series — brief + T14/T15 constraints — cost if wrong: number gaps on rollback (documented).
- Ruling: seat enforcement uses a live locking count of submitted enrollments under the Seat Matrix lock; matrix lock taken first in PE before_submit/before_cancel and in checks (fixed lock order avoids deadlock); `filled` becomes a display cache — supersedes the implementer's counter design — cost if wrong: slightly heavier admit transaction.
- Ruling: no user switching in request paths — accounting docs created with ignore_permissions + targeted flags, posting_date today, frozen-period checks respected — cost if wrong: officers may need extra Accounts perms for edge cases.
- Ruling: seat count = blocking LOCK IN SHARE MODE read on a new composite index, matrix lock taken in an extend_doctype_class override of submit/cancel/save before Frappe's row lock — fails closed (deadlock abort) instead of overselling — cost if wrong: more lock contention during admission peaks.
- Ruling: Admission Officer gets READ-only perms on those accounting masters/docs (company-scoped by User Permissions) — needed because ERPNext account/item checks ignore ignore_permissions; no write/submit rights granted — cost if wrong: officers can view invoices/PEs of their company.
- Ruling: bulk runner turns a dead-savepoint/deadlock item into a recorded failure after a full rollback and continues; allotment import chunk=1; admit retries once on deadlock — fail closed but don't strand runs — cost if wrong: earlier chunk items redone only when chunk>1 (allotment now chunk=1).
- Ruling: empty-company Lead hiding applies only to saved docs and to campus-admission-only users; ERPNext Sales roles unaffected — keeps ERPNext flows intact — cost if wrong: admission officers holding Sales roles see company-less leads.
- Ruling: review tiers — haiku/sonnet reviewers for low-risk tasks (T21, T22, T27, T28, T18, T19 rules core uses sonnet), opus only for security/concurrency-heavy (T24 ledger/no-dues, T25 gateways, T26 portal permissions, T20 certificates/TC dues gate if needed).
- Ruling: fix rounds only for Critical/Important; Minor findings go straight to the deferred list for the final review (no fix round for minors alone).
- Ruling: batches — B1 = T21 grievances + T22 scholarships (one implementer, one review); B2 = T27 data points + T28 import templates. Remaining order: T18 (running), T17 round 2, T19, T24, T25, T20, B1 (T21+T22), T26, B2 (T27+T28).

## Thin slice
- Ruling: Phase 1 T17 round-2 finding (Lead has_permission vs Sales Users) parked — not on the demo path; resume with Phase 1 — cost if wrong: Sales Users can't create company-less Leads until then.
- Ruling: P1-T18 partial work parked on branch wip/p1-t18-onboarding, unreviewed.
- Ruling: portal is server-rendered www for the slice (Vue SPA later) — speed — cost if wrong: rework pages into SPA later.
- Ruling: review = one Sonnet review per task; only Critical/Important fixed, max 2 fix rounds; minors deferred.
- Ruling: missing desk buttons (Admit on Student Applicant, Issue Grade Sheet on Student Result/Exam Session) are Important for a pilot demo — to be added in the S5 fix round — cost if wrong: demo relies on console calls.
- Ruling: final fix wave also locks Student read for Student/Guardian roles to own/linked records (reviewer's "declined" upstream exposure; root cause of I1) — privacy before any real pilot — cost if wrong: an Education feature relying on students reading other Student rows breaks (none on the demo path).

## Phase 2

### P2-T12 fix round 1 (coordinator rulings)
- Ruling: once the ESE-alone rule applies (R2022, from the 3rd attempt) a pass is graded on the better of the total and the ESE % — a higher CIA never gives a lower grade — `rules.graded_mark(..., ese_alone_applies)`.
- Ruling: classification takes the entry type; a Classification Rule Class row has `max_years_lateral` (0: `max_years` applies). R2022 distinction: 5 years regular, 4 years lateral.
- Ruling: a degenerate relative cohort (a non-positive mark, fewer than 3 distinct marks, or a Box-Cox lambda at the ±5 search bound) is graded absolutely instead of raising.

### Pending confirmation (unsourced values seeded by P2-T12 / P2-T13; source: docs/research/anna-university-autonomous-rules.md is silent)
| # | Item | Seeded value |
|---|------|--------------|
| 1 | R2022 relative grade SD cut-offs | O ≥ +1.5, A+ ≥ +0.5, A ≥ -0.5, B+ ≥ -1.0, B ≥ -1.5 SD; C takes the rest |
| 2 | AU-R2021 grade mark ranges | the R2022 ranges (O 91-100 … C 50-55, U < 50); no Theory with Lab row |
| 3 | Grading of an ESE-alone pass | the better of total % and ESE % (fix round 1 ruling above) |
| 4 | Absence counts as an attempt | yes, in AU-R2021, R2022 and R2026 |
| 5 | Maximum attempts | 0 (no cap beyond the programme duration) in all three |
| 6 | CIA carry-forward | R2022 only (1); AU-R2021 and R2026 0 |
| 7 | R2022 ESE-alone rule course types | every course type (Theory, Theory with Lab, Lab, Project) from attempt 3 at 50% |
| 8 | Classification year limits | R2022 5 years incl. break of study (lateral distinction 4); AU-R2021 and R2026 no limit; Honours first class 7.5 in R2022 |
| 9 | Online-course grade tables | not seeded (the note gives only end rows) |
| 10 | GPA exclusions | MC excluded in all three; additional courses count once Honours/Minor is completed in R2022 and R2026, not in AU-R2021 |
| 11 | x.5 boundary rounding of a total to a grade | half up to a whole mark before the grade range lookup (deferred ruling) |
| 12 | CIA conversion rounding (P2-T13) | weighted assessments rounded half up to a whole mark, then attendance marks added |
| 13 | R2026 theory CIA split (P2-T13) | R2022's two assessments (40 assignment + 60 test each) scaled to 35, plus up to 5 attendance marks |
| 14 | Theory with Lab / Project / R2021 and R2026 lab CIA templates (P2-T13) | not seeded |

### P2-T19 fix round 1 (coordinator rulings)
- Ruling: grace marks take the smaller need of the total basis and, from the attempt where it applies, the ESE-alone basis.
- Ruling: an arrear registered in a session without a mark sheet row stays Pending (owed, outside the SGPA, counted as an arrear); the student's other courses are graded.
- Ruling: a Passing Board resolution names its Exam Session; the meeting is Held, sits after the session's last Result Run finished, and is not recorded by the publisher.
- Ruling: a re-run after publication makes a pending version; the published version stays the latest until a Result Ratification (approval engine, no self-approval) publishes it and notifies the student; relative bands are frozen at publication and reused by every later re-run.

### P2-T19 fix round 2 (coordinator rulings)
- Ruling: one input-change guard at publication: refused when any Student Result, Mark Sheet Entry or Mark Moderation of the session changed after the last clean Result Run finished or after the Passing Board meeting (datetimes); the latest run of each programme must be clean.
- Ruling: a Meeting Resolution's recorder is stamped by the server when numbered and never changes, nor does its Exam Session; neither the recorder nor the meeting's owner publishes on it.
- Ruling: the first result version made after publication is pending ratification too; the bands frozen at publication are those the last run graded on.

### P2-T19 fix round 3
- Ruling: publication compares Mark Sheet Entries and Mark Moderations with the earliest start of the latest clean runs (cohorts are shared across programmes), and each programme's Student Results with its own run's finish.
- Ruling: a teacher cannot change the marks of a student who has a Student Result in the session, nor delete such a sheet; the COE can change them and must re-run.
- Deferred (dev data only): sessions published before fix round 2 have no recorded bands, so their post-publication re-runs grade on live bands and only produce pending versions; Result Ratification items listed before fix round 2 have an empty fingerprint and are not published (list them again).

### Pending confirmation (P2-T19)
| # | Item | Applied |
|---|------|---------|
| 1 | Grace marks per regulation | grace off in every seeded Exam Rule Set (limits are records once a value is given) |
| 2 | Arrear CIA under a regulation without CIA carry-forward (AU-R2021, R2026) | the CIA on the new session's sheet when entered, else the last earlier attempt's CIA (ruling pending with the user) |

### Pending confirmation (unsourced Body Type values removed from the P2-T01 seed; fix round 1)
UGC 2023 cl. 12 as summarised in docs/research/anna-university-autonomous-rules.md is silent on these. They were seeded first, then removed so no unsourced value blocks a save. Colleges set them on the Body Type.
| # | Body Type | Removed value |
|---|-----------|---------------|
| 1 | Academic Council | quorum 50%; "exactly 3" University Nominees (now at least 3, no maximum) |
| 2 | Board of Studies | term 3 years, 2 meetings a year, quorum 50%, at least 1 External Expert and 1 Alumni |
| 3 | Finance Committee | term 3 years, 2 meetings a year, quorum 50% |
| 4 | Non-statutory committees | no composition, term, meetings or quorum seeded |
Retained (sourced): Governing Body 5-year term, 2 meetings a year, quorum 50%, at least 1 University Nominee (mandatory for quorum); Academic Council at least 3 University Nominees, 3-year term, 2 meetings a year.

### Pending confirmation (P2-T04 fix round 1: TDS on external member honorarium)
| # | Item | Rule applied |
|---|------|--------------|
| 1 | TDS base (194J / new-Act professional fees) | the gross: honorarium + DA + TA (CBDT Circular 715 treats reimbursements billed with the fee as part of it) |
| 2 | TA exemption | TA is left out of TDS only when "TA at Actuals" is ticked AND the travel bill is attached; DA is always taxed |
| 3 | TDS section | always the Supplier's Tax Withholding Category (kept by Accounts); a claim is refused when the Supplier has none |

### P2-T17 fix round 2: confidential question papers (coordinator rulings)
| # | Item | Ruling |
|---|------|--------|
| 1 | System Manager configuration paths (backups, Jinja in Notification/Print Format/Webhook, Customize Form, Server Script, self-granted roles) | Known residual: System Manager is Administrator-equivalent for exam confidentiality. Guards added: no Version, Notification or Webhook on the confidential DocTypes |
| 2 | Question paper key | Environment `CAMPUS_QP_KEY`, else a key file outside sites/ (`campus_qp_key_file`), else site_config `campus_qp_key` with a migrate warning. Never regenerated while sealed files exist |
| 3 | Bank items while a sealed paper is closed | The whole bank of the course is hidden and locked (no oracle of which items are on the paper) |
| 4 | Download lead | At most 120 minutes; release_at is always the slot start |
| 5 | Withdrawal | COE or System Manager of the paper's company, with a reason; a withdrawn sealed paper stays closed for good |
| 6 | Deferred | Encrypting Question Bank question text at rest; unsealing a paper for edits; portal access for setters |
| 7 | Withdrawal retires the bank items (fix round 3) | Withdrawing a sealed paper disables its bank items for good (retired_by_withdrawal); a replacement paper cannot use them |
| 8 | Deferred (fix round 3) | A denial inside a request that rolls back only to a savepoint (not the whole transaction) is not replayed; the download window snapshot does not follow a later schedule change: on postponement, withdraw the paper and seal a new one |

### P2-T21 fix round 1: withdrawal, break of study, rejoin (coordinator rulings)
| # | Item | Ruling |
|---|------|--------|
| 1 | Regulation of a rejoining student | the regulation of the cohort joined: admitted in the rejoin year less the years completed when the break started; the student's batch moves to that cohort |
| 2 | Withdrawal courses | courses of the term only (Current, Dropped); an arrear or bridge course is not withdrawn (thin cut) |
| 3 | Bridge courses | registered (kind Bridge, attendance applies) only when offered in the term; unoffered ones stay pending, not registered or charged |
| 4 | Students on a break | exam registration and the Result Run skip a student whose academic status is Break of Study |
| 5 | No Approval Policy | withdrawal, break and rejoin are never submitted without one (fail closed) |

### Pending confirmation (P2-T21)
| # | Item | Implemented |
|---|------|-------------|
| 1 | Withdrawal window: before or after the exam | after: an application up to the Exam Rule Set's days (10) after the course's exam date is in time, per the P2-T21 acceptance criterion; any time before the exam is in time. The AU text reads "within 10 days prior to the commencement of the examination" |

### Pending confirmation (P2-T22)
| # | Item | Implemented |
|---|------|-------------|
| 1 | Honours / Minor credits | 18 for R2022 (note: "+18 credits") and for R2026 (the note says only "+additional courses"); 0 (no variant) for AU-R2021 |
| 2 | Additional courses in the CGPA | Additional, Honours and Minor registrations count only once the Honours or Minor credits are passed and the Grading Scheme counts them |
| 3 | Progression Rule values | not seeded (the note gives none): each college sets the arrear limit and probation CGPA per regulation |
| 4 | Convocation export format | placeholder columns (register no, name, date of birth, programme, regulation, CGPA, %, class, completion term) until the university's format is known |
| 5 | Degree credit total | the regulation's Curriculum Rule Minimum Total Credits, checked against passed core credits (additional / Honours / Minor excluded); not checked when unset |
| 6 | Withdrawn / SA / Pending courses at graduation | arrears until passed, as in arrears.py (T21: a withdrawal is no attempt or appearance but the course is owed) |

### P2-T20 photocopy, revaluation, review
- Ruling: a revaluation outcome's ESE replaces the mark sheet's in the Result Run (moderation and grace on top); the mark sheet stays as published. After publication the change is a pending Student Result version through Result Ratification; ratification revokes the replaced version's Grade Sheet and issues one for the new version.
- Ruling: the new mark stands whether it is higher or lower; no difference threshold is applied to a revaluation (the third-valuation threshold is for double valuation only).
- Ruling: the window for all three types is counted from the release of the results (publish_at), per the brief.
- Ruling: a grievance about evaluation (AQAR 2.5.2) is a submitted Revaluation or Review application; a photocopy request alone is not one. Student Grievances of the Evaluation type are not counted (deferred).

### Pending confirmation (P2-T20)
| # | Item | Applied |
|---|------|---------|
| 1 | Application window | 15 days from the release for every seeded regulation (the note gives no figure) |
| 2 | Photocopy and justification before revaluation | R2022 only (cl. 16.4); AU-R2021 and R2026 go straight to revaluation |
| 3 | Review window | the same window from the release, so a revaluation finished late leaves no time for a review |
| 4 | Fees | none seeded: each college sets them on its Exam Fee Rate |

## Roadmap rulings (2026-10-22, delegated by the user)
- **Scope**: our BRD stays the scope; section 16 (v0.2) adds requirements taken from an external team's review. Plan: docs/phases/roadmap-2026-10.md (Waves 0-5 complete the project).
- **L-02 joining gate**: adopted. Admission approval no longer creates Program Enrollment, tuition invoice or ID; Joining Confirmation does, and sets the attendance start date. Pre-joining money is an advance (Payment Entry against the applicant's customer), not an invoice. Existing admitted records are left as they are; a patch marks them joined on their enrollment date.
- **P4-T18 concession model v2**: built configurable. Seeded default: one of each concession sub-type per admission, fee subhead and semester; combined cap 100% of the subhead; order = fixed-amount sub-types first, then percentages on the remainder. Pending confirmation by the pilot college.
- **Pending values** in this file stay as seeded defaults and stay marked "Pending confirmation"; no new work waits for them.
- **Test sites**: four lanes, campus-test, campus-test2, campus-test3 and the new campus-test4. campus-test is rebuilt from scratch (stale payroll seed and leaked fee structures). All test runs go through the shared test guard.
- **L-01 lifecycle statuses** (accepted after review): Detained is no longer a status; it is the flag Student.oc_detained and the student stays Active. Long Absent migrates to Active. A TC moves the student to Withdrawn, only while on roll. Convocation List gives Study Completed then Award Eligible; the COE's Mark Graduated gives Graduated. One status per student, not per enrollment; each transition records its Program Enrollment.
- **Test sites, update**: campus-test5 added (lane E) so the L-01 fix round does not wait for a lane.
- **P3-T10 attainment access**: IQAC Coordinator reads CO/PO runs and their aggregate figures (needed for AQAR 2.6.2 and NBA); per-student marks behind a run are readable only by System Manager, Controller of Examinations and Dean Academics. Choice papers ("answer any N") are handled only by "no mark row = not attempted" plus a Choice Paper flag; full choice-group modelling is deferred.
- **X-01 affiliated mode**: Examination Mode is an explicit Institution Profile field (override per Exam Rule Set); an affiliated exam is its own Exam Session (unique per company + term + mode); the Controller of Examinations is the exam-cell role; CIA counts as final once the offering's CIA Schedule is locked; imported results take grade points from our Grading Scheme. The Examinations workspace follows Examination Mode, so an affiliated college sees CIA and the university exchange (its internal result run stays refused). SXCCE (the pilot audience) is autonomous.
- **X-03 completion**: a thin Credit Recognition register (waiver, transfer, equivalence; M03-09 cut) counts a cleared course once, and L-05 extends it later. Honours and Minor credits are shown but do not block the degree, which is then awarded without the variant. No Effective curriculum means the check is Incomplete. No disciplinary hold is checked until confidential cases (P4-T16) exist. Alumni follows graduation after 30 days by default (placeholder, Completion Settings).

## PR-02 Pilot setup kit (2026-10-22)
- Ruling: the kit is data-driven (campus/setup/profiles/<name>.json, validated before any write); a second college is a second file. Exam rules reuse `campus.examinations.seed` by regulation code; Curriculum, Registration and Attendance Rule values are the R2022 ones already used by the demo (research note section 3).
- Ruling: passwords. A fixed TEST password is set only on developer-mode or `campus_demo_site` sites; on any other site no password is stored and each new user gets a one-time "password expired" reset link, so the first login sets their own. Cost if wrong: admins distribute links instead of one password.
- Ruling: master-data import templates already exist (`legacy_import.TEMPLATES`); only a "Fee Structures" template was added. Course Offerings are generated from the curriculum, not imported.
- Ruling: locked records (Effective regulation and its rules, submitted Fee Structure) are never edited by a re-run; a difference is reported in the run's notes.

### Pending confirmation (PR-02 synthetic profile values)
| # | Item | Seeded value |
|---|------|--------------|
| 1 | Programme intake | 60 per programme (B.E. CSE, ECE, EEE, MECH, CIVIL; B.Tech IT) |
| 2 | Quota shares | Government 65%, Management 35% |
| 3 | Government quota category split | OC 31, BC 30, MBC 20, SC 18, ST 1 (Tamil Nadu community reservation, grouped); Management all OC |
| 4 | Fee amounts | Placeholders per quota; the college supplies its approved schedule |
| 5 | Autonomy date of the college | not set |
| 6 | Attendance Rule R2022: condonation fee | Rs 500; unsourced |
| 7 | Attendance Rule R2022: OD and medical leave count towards attendance | both count (od_counts, medical_counts = 1); unsourced |
| 8 | Attendance Rule R2022: per-course minimum | 0 (none); the note gives only the overall 75% and the 65% medical band |
| 9 | Registration Rule R2022: Honours | CGPA 7.5 up to semester 3, no arrears (sourced for 7.5; the semester and arrears rule are the college's to confirm) |
| 10 | Registration Rule R2022: windows and caps | drop window 30 days, add from semester 5, add up to 6 credits / 2 courses, drop up to 6 credits, elective minimum enrolment 10, 36 credits a semester; unsourced except 36 |
| 11 | Curriculum Rule R2022 | 165-170 total credits, L 1 / T 1 / P 0.5 credit per period |

Rule values of Curriculum, Registration and Attendance Rule now live in one module (`campus/curriculum/rule_seed.py`), used by the demo data and by the pilot kit.

- **X-04 certificate reissue**: the duplicate fee applies to Damaged, Lost and Duplicate reissues; a correction of particulars is free. Damaged, Lost and Duplicate print DUPLICATE; a correction prints REISSUED; both print "In place of No. ...". A duplicate reprints the original record; a correction freezes the current one. Reissue is requested at the desk only. A reissued TC never runs the lifecycle change again.
- **L-08 record corrections**: one field per correction request. Locked against direct edit by default: date of birth, Aadhaar, register number, roll number (configurable in Student Correction Settings, override role System Manager). Identity and academic-identifier corrections need COE then Principal; other categories COE. Students and guardians may raise Personal, Contact and Guardian corrections from the portal; Contact needs no evidence. A new Aadhaar number is stored encrypted and only masked values appear in history.
- **PR-05 permissions**: Placement Officers keep delete on Round Result so shortlists can be corrected before results are final.
- **L-07 attendance**: a past session still in Scheduled counts as held (only Cancelled, Rescheduled-away and Makeup-replaced sessions drop out; marking sets Conducted). The attendance start date is the earliest of the student's submitted Program Enrollments and applies only inside the term's counted window. On Duty counts as present and Medical counts only in the medical band, per the Attendance Rule; covering leave is applied when counting, without writing attendance rows. The 48-hour correction cut-off runs from the period's first marking. Session states are changed at the desk.
- **Approvers can read what they approve**: the approval engine drops approvers who cannot read the record (with their company User Permissions) and refuses a level only when too few readable approvers remain. The Principal gets company-scoped read on Examiner Remuneration Claim and Certificate Request, as on Scholarship Application, because the Principal approves them.
- **L-03 reporting and no-shows**: a no-show gets the whole unallocated pre-joining advance back (net of refunds already paid, excluding scholarship disbursements), with no Refund Rule deduction because nothing was invoiced; the refund is a draft payment for Accounts to submit. Joining after the reporting deadline needs an approved late-joining request for that exact date. Admit stamps the deadline on the Student so each round keeps its own; a programme can override it. A temporary clearance for pending documents is granted before Admit. A no-show is referred as a draft Admission Cancellation; nothing is cancelled until an officer submits it.
