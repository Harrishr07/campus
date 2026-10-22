# Phase 1 - Foundation

Goal: a college (and its trust) can be configured, admit students, run classes with registration and
attendance, bill and collect fees across companies, issue verifiable certificates, message students and
parents, and students/parents can use the portal. It also lays the platform engines every later phase uses.

BRD: M17-01/02/03/04/06/07 (partial), M16-01/02/03, M03-01/04 (+M03-06 data model), M04-01..05,
M05-01..06, M09-01/02/04/06.
Prerequisites: bench + site from `docs/phases/README.md`. Read the README conventions first.

Exit demo (end of phase, manual UAT): admit 3 counselling students and 1 management-quota student into
B.E. CSE R2026 → invoice and collect fees (one by gateway) → course registration → 4 weeks of attendance →
shortage list and condonation → bonafide certificate issued and verified by QR → guardian WhatsApp/SMS
on fee due → student sees fees, attendance and certificate in `/campus-portal`.

---

## A. Platform

### P1-T01 App scaffold, test site, test runner
BRD: - | Depends on: - | Size: S
Deliverables
- `bench new-app campus` (title OneBook Campus, licence GPL-3), modules from blueprint 2.1 (empty), `required_apps = ["erpnext","hrms","education","india_compliance"]`.
- Site `campus-test.localhost` with all apps and `allow_tests: 1`. Dev site `education.localhost` gets `campus` installed.
- `campus/tests/utils.py`: base test class with demo-data loader. `Makefile`/script `scripts/test.sh` running all tests on the test site.
- `pyproject.toml` with ruff config. Pre-commit hooks (ruff, prettier for JS/Vue).
Acceptance criteria
1. `bench --site education.localhost list-apps` shows `campus`.
2. `scripts/test.sh` runs and passes with a sample test, using only `campus-test.localhost`.
3. Uninstalling `campus` from the test site leaves erpnext/education functional (no core edits).
Tests: I - smoke test that every module imports and hooks load.

### P1-T02 Demo data builder
BRD: - | Depends on: T01, T03, T04, T05 | Size: M
Deliverables: `campus/tests/demo.py` `make_demo(scale="small"|"full")` building the README demo data (companies,
institution profiles, programs, regulations, years/terms, departments, employees/instructors, users per
role, students). Idempotent. A `bench --site … execute campus.tests.demo.make_demo` entry point.
Acceptance criteria
1. Running twice creates no duplicates.
2. "full" scale creates 60 students per program batch with valid regulation, quota and category spread.
3. Every later test can call `make_demo()` in `setUpClass` in under 60 s for "small".
Tests: I - idempotency, record counts per doctype.

### P1-T03 Company scoping on academic records
BRD: M17-01 | Depends on: T01 | Size: M
Deliverables
- `oc_company` (Link Company, reqd, default user's default company, in standard filter) on Student, Student Applicant,
  Program, Course, Student Group, Program Enrollment, Course Schedule, Instructor, Room, Student Admission,
  Assessment Plan, Fee Schedule.
- `before_validate` hooks: derive `oc_company` from parent links where possible (Program Enrollment ← Program,
  Course Schedule ← Student Group, Student Group ← Program).
- Validation: linked records must share the company (e.g. a Student Group of College A cannot hold a student of College B).
- Patch: back-fill existing records to the site's default company.
Acceptance criteria
1. A user with User Permission on College A sees only College A students/programs/groups in lists, links and reports.
2. Creating a Program Enrollment linking a College B student to a College A program fails with a clear message.
3. Trust users with permissions on both colleges see both.
4. Patch is re-runnable and sets company on all pre-existing rows.
Tests: I - list visibility per user, cross-company link rejection, patch idempotency.

### P1-T04 Institution Profile, Module Packs, Campus Settings, Shared Service Agreement
BRD: M17-01, BRD 4.3 | Depends on: T01 | Size: M
Deliverables
- DocTypes: Institution Profile (one per Company, fields from blueprint section 3 plus `degree_awarding_body`,
  `provisional_certificate_issuer`), Module Pack (+ seed fixture: COE, GOVERNANCE, HOSTEL, TRANSPORT, LABS,
  CLINICAL, PLACEMENT, ALUMNI, LIBRARY, RESEARCH, IQAC), Institution Pack (child), Campus Settings (single),
  Shared Service Agreement.
- `campus_platform.api.pack_enabled(company, code)`, `get_institution(company)`, `service_provider(service, company)`.
- Pack toggling: workspace and Desktop Icon visibility via role restriction per pack.
Acceptance criteria
1. Status Affiliated hides the COE and Governance packs. Switching to Autonomous with an effective date enables them without data change.
2. `pack_enabled` is cached and invalidated on profile save.
3. `service_provider("Hostel", "Demo College of Engineering")` returns the trust company.
4. Only one Institution Profile per Company.
Tests: U - pack rules by status. I - toggling, cache invalidation, agreement lookup.

### P1-T05 Regulation model
BRD: M02-04 (data model), principle 4 | Depends on: T03 | Size: M
Deliverables
- DocType Regulation (code, company, programs child, effective from admission year, status Draft/Approved/Effective/Retired,
  approving resolution link (filled in Phase 2), notes).
- Student fields `oc_regulation`, `oc_batch`. Child "Regulation History" on Student (from regulation, to regulation, date, reason, bridge courses note).
- `campus_platform.api.get_regulation(student)` and `get_rule(student, rule_doctype)` that resolves the rule set for the student's regulation.
- Auto-assign the regulation at Program Enrollment from program + admission year.
Acceptance criteria
1. A 2023 batch student resolves to R2022, a 2026 batch student to R2026, a 2021 batch student to AU-R2021.
2. Changing a student's regulation (rejoin after break) writes a history row and needs the Dean Academics role.
3. An Effective regulation cannot be edited (only amended to a new version).
Tests: U - resolution by batch/program. I - auto-assign on enrollment, edit lock, history.

### P1-T06 Positions and holders
BRD: M17-02 | Depends on: T03 | Size: S
Deliverables: Position, Position Holder DocTypes (blueprint section 3). `campus_platform.api.resolve_position(code, scope, on_date)` → users.
Seed positions: Principal, Dean Academics, Dean Student Affairs, HOD, Class Advisor, Mentor, COE, IQAC Coordinator, Warden.
Holder assignment grants the position's role and removes it at the end date (daily job).
Acceptance criteria
1. "HOD of CSE on 2026-10-04" resolves to the current holder. On a past date it resolves to the holder at that time.
2. Ending a holder removes the role the next day unless another active holding grants it.
3. Overlapping holders for a single-holder position are rejected.
Tests: U - date-range resolution. I - role grant/revoke job.

### P1-T07 Approval engine
BRD: M17-03 | Depends on: T06 | Size: L
Deliverables
- DocTypes: Approval Policy (+ Approval Level child), Approval Request (+ Approval Action child), Approval Delegation.
- Mixin `ApprovableDocument` with `request_approval()`. Whitelisted `approve`, `reject`, `return_for_changes` with comment.
- Approver types: Role, Position (scoped by a field on the doc, e.g. department), User, Field (user in a doc field), Reporting Manager.
- SLA: `due_at` per level. Hourly job escalates to `escalate_to` and notifies via messaging (T10, falls back to email until T10 lands).
- Delegation resolution at action time, with an "on behalf of" record.
- Desk: "Approvals" workspace with a My Pending list. Form sidebar shows the approval trail.
Acceptance criteria
1. A 3-level policy (HOD → Dean → Principal) on a test doctype moves level by level. Submit (`docstatus=1`) happens only after the final approval.
2. Policy `condition` (e.g. `doc.amount > 50000`) selects between two policies. With no match, the document submits directly.
3. An overdue level escalates once, notifies the escalation approver, and keeps the original approver able to act.
4. A delegate can approve during the delegation window. The trail shows "X on behalf of Y". Outside the window they can't.
5. Rejection returns the doc to draft with a mandatory comment.
6. All actions are immutable (no edit or delete of Approval Action rows).
Tests: U - policy selection, level progression state machine, SLA due calculation. I - full flow on a dummy doctype, escalation job, delegation window, permission checks (non-approver gets PermissionError).

### P1-T08 Verifiable documents and QR
BRD: M17-04, M05-04 | Depends on: T01 | Size: M
Deliverables: Verifiable Document DocType. `issue(doc, print_format)` stores a SHA-256 of the rendered PDF and a random 10-char code.
Jinja macro `oc_qr_block(doc)`. Public page `/verify/<code>` showing issuer, type, holder name (partly masked), issue date and status (valid/revoked). Rate-limited.
Acceptance criteria
1. A certificate printed with the macro shows a QR. Scanning opens `/verify/<code>` with the correct details.
2. Revoking shows "Revoked on … reason …" publicly.
3. An unknown code returns "not found" without leaking data. More than 30 requests per minute per IP are throttled.
Tests: I - issue, verify, revoke, rate limit, hash stability for the same render.

### P1-T09 Bulk job runner
BRD: NFR performance | Depends on: T01 | Size: M
Deliverables: Bulk Run DocType (type, parameters JSON, status, total, done, failed, started/finished) and Bulk Run Row Error child.
Helper `run_bulk(run_type, items, handler, chunk=200)` enqueued on the long queue, resumable from the last committed chunk,
idempotency via a handler-provided key. Realtime progress to the form.
Acceptance criteria
1. A 5,000-item dummy run completes. Killing the worker mid-run and re-queuing resumes without duplicates.
2. Per-item failures are logged and the run ends "Completed with errors".
3. Progress updates live on the Bulk Run form.
Tests: I - resume after simulated crash, idempotency, error capture.

## B. Messaging (M16)

### P1-T10 Messaging core: templates, consent, send API, channels
BRD: M16-01, M16-02 | Depends on: T01, T09 | Size: L
Deliverables
- DocTypes: Message Template (event key, channels, language rows en/ta, WhatsApp template link from `frappe_whatsapp`, SMS DLT template ID),
  Communication Consent, Message Log, Messaging Settings.
- `campus_messaging.api.send(event_key, doc, recipients, context=None)`. Recipients can be Student/Guardian/Employee/User/phone.
- Channel adapters: email (Frappe), SMS (SMS Settings, DLT IDs), WhatsApp (`frappe_whatsapp` send), push (Frappe push, optional).
- Fallback order per Messaging Settings. Quiet hours (non-urgent messages queued until morning).
- Idempotency key `(event_key, doc, recipient, channel)`.
Acceptance criteria
1. `send("fees.due", invoice, [guardian])` sends WhatsApp. If WhatsApp fails, it falls back to SMS and logs both attempts.
2. A promotional template is not sent to an opted-out guardian. A transactional one (fee due) still is, per consent purpose.
3. Re-sending the same event for the same doc and recipient is a no-op.
4. Tamil variant used when the recipient's language is `ta`.
5. Delivery status webhooks from WhatsApp update the Message Log.
Tests: U - template rendering, consent decision table, fallback ordering. I - send with mocked adapters, idempotency, webhook status update.

### P1-T11 Broadcasts and circulars
BRD: M16-02, M16-03 | Depends on: T07, T10 | Size: M
Deliverables: Audience Rule, Broadcast (bulk via T09), Circular (approval via T07, publish window, attachments,
acknowledgement), Circular Acknowledgement. Reports: Delivery summary, Consent register, Circular acknowledgement status.
Acceptance criteria
1. A broadcast to "Guardians of III year CSE" resolves the correct recipient count before sending and requires approval if configured.
2. A circular is invisible to the audience until approved and the publish time is reached. Afterwards it shows in the portal and is notified.
3. Acknowledgement status per recipient is reportable.
Tests: I - audience resolution, approval gating, publish window, acknowledgement.

## C. Curriculum core (M03)

### P1-T12 Curriculum masters
BRD: M03-01 | Depends on: T05 | Size: M
Deliverables
- Custom fields on Program and Course (blueprint section 5).
- DocTypes: Course Category (seed HSMC, BSC, ESC, PCC, PEC, OEC, EEC, MC, AC, VAC), Curriculum (+ Curriculum Course child,
  + Category Credit Requirement child), Elective Group.
- Curriculum statuses Draft / Approved / Effective (Approved → Effective linked to the Governance resolution in Phase 2; for now manual by Dean Academics).
- Credits derived from L-T-P using the regulation's credit rule (R2022: L 1, T 1, P 0.5) with manual override flag.
- Print: Curriculum structure (semester-wise table with L-T-P-C and category totals).
Acceptance criteria
1. Total credits and per-category credits are computed and validated against the regulation range (R2022: 165-170).
2. An Effective curriculum is read-only. Changes go through a new version.
3. A course can appear once per curriculum unless flagged as repeatable.
4. Credit derivation: 3-0-2 gives 4 credits under R2022.
Tests: U - credit derivation, category totals. I - version lock, duplicate prevention, print renders.

### P1-T13 Course offerings and course registration
BRD: M03-04 | Depends on: T12 | Size: L
Deliverables
- Student Group custom fields (`oc_curriculum`, `oc_semester`, `oc_section`, `oc_course_category`). Offering generator: for a term, create course-based Student Groups per curriculum semester and section.
- Registration Window (term, open/close, drop-until days, max credits, add limits).
- Course Registration (student, term, rows: course, type Regular/Arrear/Dropped/Additional/Honours/Minor, credits; approvals: advisor → HOD via T07).
- Rules (from the regulation): max credits per semester (36, excluding arrear/withdrawal), drop ≤6 credits within 30 days, add ≤6 credits / 2 courses from semester V, elective minimum enrolment (10) and seat cap, prerequisites (Phase 2 results; stub returns True until then).
- On approval: Course Enrollment rows and Student Group membership.
Acceptance criteria
1. A registration over 36 credits (excluding arrears) is rejected with the regulation clause in the message.
2. Dropping 7 credits, or dropping after 30 days, is rejected.
3. An elective at its seat cap rejects new registrations. Below the minimum enrolment at window close, it is flagged on the HOD report.
4. An approved registration adds the student to the right offering groups exactly once.
Tests: U - each registration rule with R2022 values. I - approval → enrollment, idempotency, seat cap concurrency (two parallel registrations for the last seat: one wins).

## D. Admissions (M04)

### P1-T14 Admission masters and applicant fields (incl. Aadhaar)
BRD: M04-01, M04-02, M04-04 | Depends on: T03 | Size: M
Deliverables
- DocTypes: Admission Quota, Counselling Authority (+ import column mapping child), Admission Document Rule, Eligibility Rule, Refund Rule.
- Student Applicant custom fields (blueprint section 6). `oc_aadhaar` as **Password** fieldtype on Student Applicant and Student.
- Aadhaar handling: masked display (XXXX-XXXX-1234) via a read-only `oc_aadhaar_masked` field, `reveal_aadhaar(doctype, name)` whitelisted for the "Aadhaar Viewer" role only,
  every reveal logged (Access Log), Verhoeff checksum validation.
Acceptance criteria
1. An invalid Aadhaar checksum is rejected. A valid one is stored encrypted (not visible in DB `tab` table), and only the masked value shows in forms, lists and prints.
2. A non-"Aadhaar Viewer" user calling reveal gets PermissionError. A viewer gets the number and an access log row is written.
3. Applying the Eligibility Rule for B.E. (HSC with Maths/Physics/Chemistry, category minimum marks) marks the applicant eligible or ineligible with reasons.
Tests: U - Verhoeff, masking, eligibility evaluation per category. I - encryption at rest, reveal permission and logging.

### P1-T15 Seat matrix, allotment import, document verification
BRD: M04-01, M04-02, M04-03 | Depends on: T14, T09 | Size: L
Deliverables
- Seat Matrix (company, program, academic year, rows quota × category: sanctioned, allotted, filled, vacant; filled is computed).
- Allotment Import (file, counselling authority, mapping; bulk job creating/updating applicants keyed by allotment no).
- Document Verification (checklist from Admission Document Rule per applicant, status per item, originals retained, verifier). Daily reminder job for pending items via messaging.
- Reports: Live seat matrix, Pending documents.
Acceptance criteria
1. Importing the same TNEA file twice creates no duplicates and updates changed ranks.
2. Filled seats recompute from submitted Program Enrollments only. Cancellation frees the seat.
3. Admission into a full quota/category row is blocked unless the user has the "Admission Override" role (logged).
4. An applicant with a pending mandatory document can't be admitted. Reminders go out daily until cleared.
Tests: I - import idempotency, seat recompute on admit/cancel, override permission, reminder job selection.

### P1-T16 Admission, fees, cancellation and refund
BRD: M04-01, M04-04 | Depends on: T15, T23 | Size: M
Deliverables: "Admit" action on an approved applicant: create Student (+ Customer via education), Program Enrollment with regulation (T05), roll/register number per format, fee invoice from the quota/category Fee Structure.
Admission Cancellation: refund computed from the Refund Rule by date → Credit Note + Payment Entry draft for accounts approval.
Prints: Provisional admission letter, Original documents receipt. Reports: Admissions by quota/category/gender/state, Refund register.
Acceptance criteria
1. Admit creates Student, Program Enrollment and invoice in one transaction. Failure leaves nothing half-created.
2. Register numbers follow the configured pattern without gaps under concurrency.
3. Cancellation before the cut-off refunds per the rule slab (e.g. full minus processing fee). After the cut-off, the configured deduction applies.
4. The admissions-by-category report matches the AQAR 2.1.1 and 2.1.2 counts on demo data.
Tests: U - refund slab calculation. I - admit transaction rollback, numbering concurrency, cancellation accounting entries.

### P1-T17 Enquiry CRM with WhatsApp follow-up
BRD: M04-05 | Depends on: T10 | Size: S
Deliverables: Lead custom fields (`oc_program_interest`, `oc_source_campaign`, `oc_applicant`), web form for enquiries, auto WhatsApp acknowledgement, follow-up task rules, "Convert to Applicant".
Report: Enquiry funnel by source.
Acceptance criteria
1. A web enquiry creates a Lead, sends a WhatsApp acknowledgement, and assigns it to an admission officer by round robin.
2. Convert to Applicant copies contact and program, and links back.
Tests: I - web form → Lead → message → conversion.

## E. Student services (M05)

### P1-T18 Student profile fields and onboarding
BRD: M05-01 | Depends on: T05, T06 | Size: M
Deliverables: Student custom fields (blueprint section 7). Onboarding Checklist Template + Onboarding Checklist
(ID card, library, bus, hostel, mentor, code-of-conduct acknowledgement, anti-ragging affidavit upload, induction programme).
Mentor allocation tool (HOD assigns N students per mentor). Mentor and class advisor resolved via Position Holder.
Print: Student ID card (photo, QR via T08).
Acceptance criteria
1. Admission creates the onboarding checklist from the template. Completion % is shown on the student form.
2. The mentor allocation tool distributes students evenly and the result is visible to mentors (permission query).
3. The ID card prints with photo and a verifiable QR.
Tests: I - checklist creation, mentor permission query, ID card print.

### P1-T19 Attendance rules, eligibility and condonation
BRD: M05-02 | Depends on: T05, T13 | Size: L
Deliverables
- Attendance Rule (per regulation): formula `sum_based` (R2022: attended / (periods per week × 15)) or `course_average` (R2026),
  overall minimum (75 / 80), medical band (65-74 / 70-79), per-course minimum (none / 75), whether OD/medical count, attendance-mark bands (R2026: 80-85, 86-90, 91-95, >95 → marks up to 5).
- Student Leave Application custom field `oc_leave_kind` (Leave / Medical / On Duty) + certificate.
- Attendance Eligibility Run (term, program, semester → per student per course %, overall %, status Eligible / Condonation / Detained (SA)). Bulk via T09.
- Condonation Request (approval via T07; fee via Fee Category "Condonation").
- Reports: Attendance % by course/student, Shortage list, Condonation register. Shortage notice print. Guardian alert below threshold.
Acceptance criteria
1. Same raw attendance gives different outcomes under R2022 (75% sum-based) and R2026 (80% average and 75% per course), matching hand-computed fixtures.
2. A medical-band student becomes Eligible only after the condonation is approved. Below the band, the student is SA with no condonation option.
3. R2026 attendance marks are computed per course and exposed via `student_services.api.attendance_marks(student, offering)` for CIA (Phase 2).
4. The run is idempotent and re-runnable until the term is locked.
Tests: U - fixture table of 12 attendance scenarios × 2 regulations. I - run, condonation approval flow, guardian alert.

### P1-T20 Certificates and transfer certificate
BRD: M05-04 | Depends on: T07, T08, T24 | Size: M
Deliverables: Certificate Type (seed Bonafide, Conduct, Course Completion, Migration, Medium of Instruction, TC), Certificate Request (student/portal, purpose, fee if any, approval via T07), issue → Verifiable Document.
TC: sets Student `date_of_leaving`, `leaving_certificate_number`, academic status, and requires no-dues (T24). State TC print format.
Report: Certificates issued, TC register.
Acceptance criteria
1. A student requests a bonafide in the portal. After approval the PDF with QR is downloadable and verifies at `/verify`.
2. A TC is blocked while dues exist in any company (college or trust).
3. Issued certificate numbers are sequential per type per company per year.
Tests: I - request → approve → issue → verify, TC dues gate, numbering.

### P1-T21 Grievance redressal with SLA
BRD: M05-06 | Depends on: T07 | Size: S
Deliverables: Grievance Category (escalation policy link, confidential flag), Student Grievance (category, description, attachments, status, resolution).
SLA and escalation use the approval engine levels. Report: Grievance SLA.
Acceptance criteria
1. An evaluation grievance escalates from HOD to COE to Principal when SLA hours pass.
2. Confidential categories (e.g. ICC) are visible only to the committee roles, not to the HOD.
Tests: I - escalation timing, confidentiality permission.

### P1-T22 Scholarships and fee concessions
BRD: M05-05 | Depends on: T23 | Size: M
Deliverables: Scholarship Scheme (government/institutional, eligibility rule, renewal criteria, amount rule), Scholarship Application (student, scheme, year, status, sanctioned amount), Disbursement (credit to the student's receivable via Journal Entry / Payment Entry by source), Fee Concession (applied as a discount line on the fee invoice).
Reports: Scholarship beneficiaries (AQAR 5.1.1 government, 5.1.2 institutional), Concession register.
Acceptance criteria
1. A government scholarship sanctioned for ₹50,000 reduces the student's outstanding when disbursed and appears in the 5.1.1 report.
2. A concession applies only to the configured fee categories and needs approval.
3. Renewal is blocked if the eligibility rule fails (e.g. arrears or attendance), with reasons.
Tests: U - eligibility and renewal rules. I - disbursement accounting, concession on invoice, report counts.

## F. Finance (M09)

### P1-T23 Fee heads, structures, fines, challans, receipts
BRD: M09-01, M09-02 | Depends on: T03 | Size: L
Deliverables
- Fee Category custom fields (`oc_fee_head_type`, `oc_refundable`, `oc_gst_applicable`). Seed categories: Tuition, Exam, Development, Library, Lab, Hostel, Mess, Transport, Caution Deposit, Fine, Condonation, Certificate.
- Item defaults per company (income account, cost center). Caution Deposit posts to a liability account.
- Fee Structure by program + academic year + quota + category (custom fields on Fee Structure `oc_admission_quota`).
- Fine Rule (category, grace days, slabs). Daily Fine Run creates fine invoices (idempotent per invoice per slab).
- Challan Format and bank challan print. Bank collection file import → Payment Entry matching by challan number.
- Fee receipt print (company-specific letterhead, receipt series).
Acceptance criteria
1. Fee schedule generation for 120 students creates 120 Sales Invoices with the `student` field set, the correct company, accounts and cost centres.
2. A late invoice gets exactly one fine per slab crossed. Re-running the job adds nothing.
3. A bank file with 50 rows reconciles 48 matched and 2 unmatched (reported), and no duplicate Payment Entries on re-import.
4. Caution deposit never hits income.
Tests: U - fine slab calculation. I - fee schedule generation, accounting entries per category, bank import idempotency.

### P1-T24 Student fee ledger, dues gate, no-dues
BRD: M09-04 | Depends on: T23 | Size: M
Deliverables: Report "Student Fee Ledger" (all companies, by student: invoices, payments, credit notes, balance by company and head).
`campus_finance.api.has_dues(student, scopes=None)` → `{total, by_company, by_head}`.
No-Dues Clearance (student, departments/offices sign-off rows: accounts, library, hostel, lab; auto-checks dues), No-dues certificate print.
Acceptance criteria
1. A student with a college tuition balance and a trust hostel balance shows both, with the correct company split.
2. `has_dues(..., scopes=["Exam"])` considers only exam-related heads (used by the hall ticket in Phase 2).
3. The no-dues certificate can't be issued while any mandatory sign-off is pending or dues exist.
Tests: I - cross-company ledger totals vs GL, scoped dues, clearance gating.

### P1-T25 Refunds, deposits, payment gateways
BRD: M09-01, M09-06 | Depends on: T23 | Size: M
Deliverables: Fee Refund (Credit Note + Payment Entry), Caution Deposit Refund (on TC/vacating, minus damages). Payment Gateway Account per company (Razorpay first) with portal "Pay now" through ERPNext Payment Request.
Gateway adapter interface for PayU/Cashfree (implemented in Phase 5).
Acceptance criteria
1. Paying in the portal for a trust (hostel) invoice uses the trust's gateway account. A college invoice uses the college's.
2. Gateway success marks the invoice paid via webhook. A duplicate webhook does not create a second Payment Entry.
3. A refund requires accounts approval and posts the reversal correctly.
Tests: I - gateway webhook idempotency (mock), company routing, refund entries.

## G. Portal and reporting

### P1-T26 Campus portal (extends the education Vue portal)
BRD: M16-04 (PWA basics), M05 | Depends on: T10, T19, T20, T24 | Size: L
Deliverables
- `campus/frontend` Vue 3 + frappe-ui SPA served at `/campus-portal`, PWA manifest, installable.
- Ported pages from education's portal (Schedule, Attendance, Fees, Grades, Leaves) calling education's existing APIs.
- New pages: Dashboard, Certificates (request/download), Grievances, Circulars (acknowledge), Fee payment (T25), Profile (masked Aadhaar), language toggle en/ta.
- Guardian view: switch between linked students.
- Role home redirect: Student and Guardian land on `/campus-portal`. `/edu-portal` still works.
Acceptance criteria
1. A student sees only their own data. A guardian sees only linked students (server-side checks, not just UI).
2. Every ported page shows the same data as `/edu-portal` for the same student.
3. Lighthouse PWA installable. Usable at 360 px width.
4. Fee payment completes end-to-end against the gateway sandbox.
Tests: I - API permission tests for each whitelisted method (student A can't read student B). M - UAT script for each page on mobile width.

### P1-T27 Phase 1 data points and reports
BRD: M17-06, principle 6 | Depends on: T15, T16, T19, T22 | Size: S
Deliverables: `campus.<module>.metrics` functions (registered for the Phase 3 metric engine): `students_admitted`, `reserved_seats_filled`,
`total_students`, `outgoing_students`, `programmes_offered`, `courses_offered`, `seats_earmarked_reserved`, `scholarship_beneficiaries_govt`, `scholarship_beneficiaries_institution`, `mentor_ratio`.
Each takes `(company, period, department=None)` and returns `{value, records}`.
Acceptance criteria
1. Each function returns the value and the list of source record names, matching the corresponding report on demo data.
Tests: U/I - each function vs a hand-computed demo fixture.

### P1-T28 Initial data import templates
BRD: M17-07 (partial) | Depends on: T03, T12, T18 | Size: S
Deliverables: Data Import templates and validation scripts for Programs, Courses, Curriculum rows, Students (with guardians, quota, category, regulation), Employees/Instructors, Opening fee balances.
Pre-import validator report (missing masters, bad Aadhaar checksums, duplicate register numbers).
Acceptance criteria
1. A 500-student legacy sheet imports with a validator report first. Fixing the flagged rows and re-importing succeeds without duplicates.
Tests: I - validator catches each error class; import idempotency by register number.

---

## Phase 1 exit checklist
- [ ] All tasks meet their acceptance criteria. `scripts/test.sh` green.
- [ ] Exit demo (top of this doc) run on `education.localhost` and recorded.
- [ ] Fixtures exported, `bench --site campus-test.localhost reinstall` + install campus + `make_demo()` works from scratch.
- [ ] Usage notes for platform, messaging, curriculum, admissions, student services, finance, portal.
- [ ] Blueprint section 12 status updated.
