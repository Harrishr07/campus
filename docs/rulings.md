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

### Pending confirmation (unsourced Body Type values removed from the P2-T01 seed; fix round 1)
UGC 2023 cl. 12 as summarised in docs/research/anna-university-autonomous-rules.md is silent on these. They were seeded first, then removed so no unsourced value blocks a save. Colleges set them on the Body Type.
| # | Body Type | Removed value |
|---|-----------|---------------|
| 1 | Academic Council | quorum 50%; "exactly 3" University Nominees (now at least 3, no maximum) |
| 2 | Board of Studies | term 3 years, 2 meetings a year, quorum 50%, at least 1 External Expert and 1 Alumni |
| 3 | Finance Committee | term 3 years, 2 meetings a year, quorum 50% |
| 4 | Non-statutory committees | no composition, term, meetings or quorum seeded |
Retained (sourced): Governing Body 5-year term, 2 meetings a year, quorum 50%, at least 1 University Nominee (mandatory for quorum); Academic Council at least 3 University Nominees, 3-year term, 2 meetings a year.
