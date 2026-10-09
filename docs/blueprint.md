# OneBook Campus - Solution Blueprint

Version 0.1 | 4 October 2026 | Companion to `AGENTS.md` and `docs/Frappe_Higher_Education_Layer_BRD.md`.
Requirement IDs (M06-03 etc.) refer to the BRD. Research notes: `docs/research/naac-reference-notes.md`.

This blueprint maps every BRD requirement to Frappe building blocks: what we reuse, and which
masters, transactions, settings, print formats, reports and integrations we build. It is the
working plan. Update the status column in section 12 as items ship.

---

## 1. Decisions

| # | Decision | Notes |
|---|---|---|
| D1 | One app `campus`, one Frappe module per BRD area | Split a module into its own app only for separate licensing, a different dependency set or a separate team. |
| D2 | Institution = ERPNext **Company**. Trust = parent (group) company. | Every college is a child Company. Academic Year and Academic Term stay shared. |
| D3 | Custom fields on upstream DocTypes use the `oc_` prefix | e.g. `oc_company`, `oc_credits`. Python helpers live under `campus.<module>`. |
| D4 | **Trust company owns the hostel** | The trust raises hostel and mess invoices directly to the student's Customer. No inter-company billing. Transport is assumed to work the same way (configurable, see D8). |
| D5 | New DocType names are plain English with no prefix, **checked for clashes** against frappe, erpnext, hrms and education before creation | `Vehicle`, `Driver`, `Room`, `Project` already exist upstream and are reused, not recreated. |
| D6 | Regulations, grading, exam rules, metric formulas and approval chains are **versioned records** | Rule records are immutable once published. Changes create a new version. |
| D7 | Modules talk to each other only through `campus.<module>.api` service functions | Not through direct imports of each other's controllers. Keeps a later split cheap. |
| D8 | Shared services (hostel, transport, library) are declared in a **Shared Service Agreement** record | It says which Company provides the service to which colleges, and which Company invoices. |
| D9 | **Grant accounting = deferred liability.** Grant receipts are credited to "Grant Received in Advance - <sanction>" (one liability account per sanction) (liability). Expenses are booked normally to expense accounts with the project dimension. A period-end Grant Income Recognition JE moves the amount spent from liability to grant income. Equipment is capitalised as an Asset, with the matching amount moved to a Deferred Capital Grant, released in line with depreciation. Interest on grant funds goes to liability by default (agency-configurable). | Matches restricted-grant reality (unspent amount is refundable, UC shows the unspent balance) and keeps expense reports normal. Confirm with the statutory auditor in the Phase 3 kickoff. |
| D10 | `india_compliance` (16.10, version-16) and `frappe_whatsapp` (shridarpatil, 1.0.12) are installed on education.localhost | GST/TDS for consultancy and examiner payments; WhatsApp channel for M16. |
| D11 | Degree issuer is a setting: `degree_awarding_body` (University / College, default University) and `provisional_certificate_issuer` on Institution Profile | UGC 2023 cl. 3.4 and SXCCE R2022/R2026 say the university awards the degree, with the college name. See `docs/research/anna-university-autonomous-rules.md`. |
| D12 | Aadhaar stored as the **full number**, in a Password-type (encrypted) field, masked in UI and prints, readable only by the "Aadhaar Viewer" role, every reveal logged | Site `encryption_key` must be backed up; losing it makes the values unrecoverable. |
| D13 | **Extend the education Vue portal**: `campus` ships its own Vue 3 + frappe-ui SPA at `/campus-portal`, which ports the existing edu-portal pages (Schedule, Attendance, Fees, Grades, Leaves) against education's APIs and adds campus pages. Student/Guardian/Faculty home redirects there. | Education core is untouched. Ported code is GPL-3, so the `campus` app is licensed GPL-3 (also the safest choice next to ERPNext). |
| D15 | Portal: the server-rendered /campus-portal (thin slice) is the one portal; the Vue SPA in D13 is deferred until after the pilot. | Avoids two parallel portals. |
| D14 | Grading and pass rules are data, with **pluggable methods**: absolute, relative (Box-Cox, cohort > 30), online-course table, attempt-aware pass clauses | SXCCE R2022 vs R2026 differ in letters, points (6.5), ranges, method and attendance. |

---

## 2. Architecture

### 2.1 App and modules

App: `campus` (requires `frappe`, `erpnext`, `education`, `hrms`). Optional: `frappe_whatsapp`, `india_compliance`.

| Frappe module | BRD | Phase | Pack (Institution Status) |
|---|---|---|---|
| Campus Platform | M17 | 1 | Always |
| Campus Messaging | M16 | 1 | Always |
| Curriculum | M03 | 1 (core), 3 (OBE) | Always; syllabus authoring needs Autonomous |
| Admissions | M04 | 1 | Always |
| Student Services | M05 | 1 | Always |
| Campus Finance | M09 | 1 | Always |
| Examinations | M06 | 2 | Autonomous / Deemed (Affiliated: CIA only) |
| Academic Governance | M02 | 2 | Autonomous / Deemed |
| Faculty | M07 | 2 | Always |
| IQAC | M01 | 3 | Always |
| Research | M08 | 3 | Always |
| Hostel | M10 | 4 | Optional pack |
| Transport | M11 | 4 | Optional pack |
| Labs | M12 | 4 (Nursing clinical: P0 for nursing) | Optional; Clinical sub-pack for Nursing |
| Placement | M14 | 4 | Always (Engineering default on) |
| Alumni | M15 | 5 | Optional |
| Library Integration | M13 | 5 | Optional |

Module names were checked against existing modules. ERPNext already has `Communication`, hence "Campus Messaging".

### 2.2 Code layout

```
apps/campus/campus/
  hooks.py
  campus_platform/        # M17: settings, approval engine, positions, verification
  campus_messaging/       # M16
  curriculum/             # M03
  admissions/             # M04
  student_services/       # M05
  campus_finance/         # M09
  examinations/           # M06
  academic_governance/    # M02 (Body, Meeting shared with IQAC)
  faculty/                # M07
  iqac/                   # M01 metric engine
  research/               # M08
  hostel/ transport/ labs/ placement/ alumni/ library_integration/
  integrations/           # adapters: pfms, whatsapp, koha, gps, biometric, digilocker ...
  fixtures/               # custom fields, roles, workflows, framework seeds
  patches/
```

Each module exposes `api.py` (whitelisted and service functions) and `rules.py` (pure rule
evaluation, unit-tested without the DB where possible).

### 2.3 Scoping model (Company)

- `oc_company` custom field (Link Company, mandatory, default = user's default company) on:
  Student, Student Applicant, Program, Course, Student Group, Program Enrollment, Course Schedule,
  Instructor, Room, Student Admission, Assessment Plan, Fee Schedule (already has company via structure).
- Users get **User Permission on Company**. College staff see their college; trust staff
  (warden, transport, accounts) get permission on all member colleges, restricted by DocType role
  permissions (read-only basics on Student).
- Shared masters (no company): Academic Year, Academic Term, Student Category, Gender, Funding Agency,
  Accreditation Framework.
- Reports always filter by Company. Trust-level reports aggregate across child companies.

### 2.4 Institution Status and packs

- **Institution Profile** (one per Company) holds `institution_status`, `segment` and enabled packs.
- On save, a hook applies the pack set: workspace visibility, role availability, and Approval
  Policies active or inactive. Doctypes stay installed. Controllers check
  `campus_platform.api.pack_enabled(company, "COE")` before acting.
- Graduation (Affiliated → Autonomous) = change status + effective date. Earlier batches keep their
  regulation (section 2.5), so no migration is needed.

### 2.5 Regulation-year model

- **Regulation** (e.g. `R2022`): company, applies-to programs, effective from batch (admission
  year), status Draft / Approved / Effective / Retired, approving resolution (from M02).
- Rule sets link to a Regulation: Curriculum, Exam Rule Set, Grading Scheme, Attendance Rule,
  Progression Rule, Attainment Policy.
- Every Student carries `oc_regulation` (set at enrollment from batch + program). Every rule lookup
  goes `student → regulation → rule set`. Never "current settings".

### 2.6 Cross-cutting engines (built in Campus Platform / IQAC)

| Engine | Purpose | Used by |
|---|---|---|
| Approval engine | Multi-level approvals, delegation, SLA escalation, comment trail | All modules (M17-03) |
| Position resolver | "HOD of ECE", "Class advisor of III-CSE-A", "Warden of Block B" resolved to users by date | Approvals, notifications |
| Metric engine | Framework → criterion → metric definitions, formula over data points, computed values with traceability | IQAC (M01-02), all modules feed it |
| Evidence registry | Files/URLs tagged to metrics, year, department, source record | All modules (principle 6) |
| Verifiable documents | Hash + QR + public `/verify/<code>` page | Certificates, mark sheets, UC (M17-04) |
| Messaging bus | `send(event_key, doc, audience)` with consent check, templates, channels, logging | All modules (M16) |
| Bulk job runner | Idempotent, resumable background runs with progress and per-row errors | Hall tickets, results, fees, allotments, metrics |
| Feedback engine | Forms, campaigns, anonymous responses, analysis | M01-05, M03 indirect attainment, M07-04, M15-04 |
| Body & Meeting | Committees, councils, boards, agenda, minutes, resolutions, action items | M01-04, M01-06, M02, M06 passing board |

---

## 3. Campus Platform (M17)

**Features**
- M17-01 multi-institution under one trust, shared services, separate academic records.
- M17-02 role model aligned to hierarchy; position holders with terms.
- M17-03 generic approval engine with delegation and SLA escalation.
- M17-04 document versioning (Frappe Version), e-sign hook, QR verification.
- M17-05 integration framework (adapter + settings + request log).
- M17-06 dashboards; regulator exports (each module ships its own).
- M17-07 migration toolkit (Data Import templates per legacy source).

**Reuse:** Company, Department, Designation, Employee, User Permission, Role, Workflow (simple
cases), Version, Data Import, Integration Request, Dashboard Chart, Number Card, Workspace,
Service Level Agreement (reference for SLA logic).

**Masters**
- Institution Profile: company, segment (Arts & Science / Nursing / Engineering),
  institution_status, autonomy conferred on, affiliating university, AISHE code, AICTE permanent
  ID, NAAC track ID, NIRF ID, principal, IQAC coordinator, COE, packs (child), public disclosure base URL.
- Module Pack: code, title, allowed statuses, workspaces, roles.
- Regulation (section 2.5).
- Shared Service Agreement: provider company, service (Hostel / Transport / Library), member
  companies (child), invoicing company, from/to.
- Position: title, scope type (Institution / Department / Student Group / Hostel / Body / Lab), role granted.
- Position Holder: position, scope value, employee/user, from/to.
- Approval Policy: document type, company, condition (safe_eval), levels (child: approver type
  Role / Position / User / Field / Reporting Manager, SLA hours, escalate to, min approvals,
  can edit fields), on-final action (submit / set field / call service).
- Approval Delegation: user, delegate, from/to, document types.

**Transactions**
- Approval Request: reference doctype/name, policy, current level, status, due at, actions
  (child: level, approver, on behalf of, action, comment, timestamp).
- Verifiable Document: reference doctype/name, print format, content hash, code, issued on,
  revoked, revocation reason.
- Migration Batch: source system, template, file, status, row errors.

**Settings:** Campus Settings (single): default attendance threshold (75, editable),
approval SLA check interval, verification base URL, data retention days, languages enabled
(en, ta), default company for trust users.

**Print formats:** QR verification block (Jinja macro reused by every certificate); Approval trail block.

**Reports:** Pending approvals by approver, Overdue approvals (SLA breach), Delegation log,
Sensitive record access log (exam/marks/health), Position holder register.

**Integrations:** adapter framework only (section 10).

**Key logic**
- Doctypes opt in via a mixin `ApprovableDocument`, which creates an Approval Request on submit-for-approval
  and blocks `docstatus=1` until final approval.
- Scheduler (hourly): escalate overdue levels, notify through the messaging bus.
- Delegation is resolved at action time, and the action records "on behalf of".
- Use plain Frappe Workflow only for simple fixed-state doctypes. The approval engine handles
  anything with dynamic approvers, SLA or delegation.

---

## 4. Campus Messaging (M16)

**Features:** M16-01 WhatsApp/SMS/email/push templates by event; M16-02 role/group broadcast with
consent and opt-out; M16-03 notices and circulars with approval before release; M16-04 PWA/mobile.

**Reuse:** Notification, Email Account, Email Template, SMS Settings, `frappe_whatsapp`
(WhatsApp Templates, WhatsApp Message), Frappe push notifications.

**Masters**
- Message Template: event key (e.g. `exam.result_published`), channels, language variants,
  WhatsApp template link, SMS DLT template ID, variables.
- Audience Rule: type (Role / Student Group / Program+Semester / Hostel / Route / Department /
  Guardians of …), filters.
- Communication Consent: party (Student / Guardian / Employee / Alumni), channel, purpose
  (transactional / promotional), status, source, timestamp.

**Transactions:** Broadcast (audience, template, schedule, approval, counts), Message Log
(recipient, channel, provider ID, status, error), Circular (audience, body, attachments, publish
window, approval, acknowledgement required), Circular Acknowledgement.

**Settings:** Messaging Settings: channel fallback order, quiet hours, rate limits, DLT entity ID,
default sender per company.

**Print formats:** Circular.

**Reports:** Delivery summary by channel and event, Consent register, Opt-out log, Circular
acknowledgement status, Failed messages.

**Integrations:** WhatsApp Business (Meta Cloud API via `frappe_whatsapp` or a BSP), SMS gateway (DLT
compliant), email, FCM push.

**Key logic:** every module calls `campus_messaging.api.send(event_key, doc, audience)`. That call checks
consent (transactional messages bypass promotional opt-out), renders the template, enqueues a job
with an idempotency key `(event, doc, recipient)`, and logs the outcome. The student/parent PWA extends
the existing Vue `edu-portal` (attendance, fees, results, hall ticket, outpass, grievances).

---

## 5. Curriculum & OBE (M03)

**Features:** M03-01 regulation-year curriculum with credits and categories; M03-02 PEO/PO/PSO/CO with
CO-PO/PSO matrices and approval; M03-03 assessment-to-CO mapping and attainment (direct + indirect,
configurable); M03-04 course registration with prerequisites, credit limits, seat caps,
add/drop; M03-05 credit transfer, honours/minor, lateral entry; M03-06 co-curricular/audit credits.

**Reuse:** Program, Course, Program Course, Academic Year/Term, Student Group (course-based group
= **course offering**), Course Enrollment, Program Enrollment.

**Custom fields**
- Program: `oc_company`, `oc_level` (UG/PG/Diploma/PhD), `oc_degree`, `oc_discipline`,
  `oc_duration_years`, `oc_total_semesters`, `oc_sanctioned_intake`, `oc_lateral_entry_allowed`,
  `oc_nba_accredited_until`.
- Course: `oc_company`, `oc_course_code`, `oc_course_type` (Theory / Lab / Theory+Lab / Project /
  Internship / Clinical / Audit), default `oc_lecture_hours`, `oc_tutorial_hours`, `oc_practical_hours`, `oc_credits`.
- Student Group: `oc_curriculum`, `oc_semester`, `oc_section`, `oc_course_category`.

**Masters**
- Course Category: code (PCC, PEC, OEC, BSC, ESC, HSMC, MC, Audit, Value-added …), counts toward credits.
- Curriculum: program + regulation + version, status, total credits, category credit minimums (child),
  courses (child Curriculum Course: semester, course, category, L/T/P/C, elective group,
  prerequisites, CIA/ESE max, exam type).
- Elective Group: curriculum, semester, choose N, seat cap per course.
- Program Educational Objective, Program Outcome, Program Specific Outcome (per program + regulation).
- Course Outcome: course + curriculum, code (CO1…), statement, Bloom level.
- CO-PO Matrix: course + curriculum, rows CO × PO/PSO with correlation 1/2/3, approval.
- Bloom Level.
- Attainment Policy (per regulation): direct/indirect weights (e.g. 80/20), direct split CIA/ESE
  (e.g. 40/60), student threshold % (e.g. ≥60% marks), level bands (e.g. L1 ≥40% students,
  L2 ≥50%, L3 ≥60%), indirect tools (course exit survey form), PO target.
- Registration Window: term, open/close, add/drop until, credit min/max.

**Transactions**
- Course Registration: student, term, selected courses, credits, advisor approval → Course
  Enrollment + Student Group membership.
- Add/Drop Request.
- Course Plan (teaching plan): course offering, planned topics by week, CO per topic; delivery
  updated from Course Schedule (feeds AQAR 2.3.4).
- CO Attainment Run: course offering, policy, results per CO (direct CIA, direct ESE, indirect,
  final, level, target met), snapshot of source marks.
- PO Attainment Run: program, batch, academic year, result per PO/PSO.
- Co-curricular Credit Record: student, activity, points, approved by.
- Credit Transfer: student, source (NPTEL/SWAYAM/ABC/other institution), course mapped, credits, approval.

**Settings:** Curriculum Settings: default credit limits, add/drop days, default attainment policy.

**Print formats:** Regulation & Syllabus book (PDF per program/regulation), Course Plan, CO-PO
matrix, Course attainment sheet (NBA course file), Curriculum structure summary.

**Reports:** Curriculum credit summary vs category minimums, CO-PO mapping coverage, CO
attainment by course/faculty, PO/PSO attainment by program/batch, Course registration status,
Elective seat fill, Course file completeness, NAAC 1.1.2/1.1.3/1.2.1/1.2.2/1.3.2/1.3.3/1.3.4 counts.

**Integrations:** NPTEL/SWAYAM credit import (file), ABC credit upload (P2).

**Key logic**
- CO direct attainment per tool = % of students scoring ≥ threshold on items mapped to that CO, mapped to a level band.
- CO direct = wCIA·CIA level + wESE·ESE level. CO final = wD·direct + wI·indirect.
- PO = Σ(CO final × correlation) / Σ correlation over mapped COs.
- All weights come from the student's regulation's Attainment Policy.
- Course Registration validates prerequisites (passed in M06 results), credit limits, seat caps and the window.

---

## 6. Admissions (M04)

**Features:** M04-01 pipelines for counselling, management quota, lateral entry and PG, with allotment
imports; M04-02 eligibility and document checklist with reminders; M04-03 live seat matrix;
M04-04 fee by quota/category, refund rules; M04-05 enquiry CRM with WhatsApp follow-up.

**Reuse:** Student Admission (admission round), Student Applicant, Student Category (community:
OC/BC/BCM/MBC/SC/SCA/ST etc. as data), Program Enrollment, Fee Structure (by category), ERPNext
Lead/Opportunity for enquiries.

**Custom fields on Student Applicant:** `oc_company`, `oc_admission_quota`, `oc_admission_type`
(Regular / Lateral / PG / Transfer), `oc_counselling_authority`, `oc_allotment_no`,
`oc_allotment_date`, `oc_rank`, `oc_cutoff`, `oc_first_graduate`, `oc_differently_abled`,
`oc_qualifying_marks` (child), `oc_documents` (child checklist), `oc_lead`.

**Masters:** Admission Quota (Government/Counselling, Management, NRI, Lateral, supernumerary flags),
Counselling Authority (TNEA, TN lateral entry, PG counselling; import template), Admission Document
Rule (document, required for quota/type/category, original retained, verification needed),
Eligibility Rule (program + regulation: subjects, min marks by category), Refund Rule (window
→ deduction %, per regulator norm).

**Transactions:** Seat Matrix (company, program, academic year; rows quota × category:
sanctioned / allotted / filled / vacant), Allotment Import (file → applicants, idempotent on allotment
no), Document Verification (applicant, item status, verifier, reminder schedule), Provisional
Admission (applicant → fee invoice → Student + Program Enrollment), Admission Cancellation
(refund computed by rule → Credit Note + Payment Entry), Enquiry (ERPNext Lead + `oc_` fields).

**Settings:** Admission Settings: active admission year, register/roll number format, application fee categories.

**Print formats:** Provisional admission letter, Fee challan, Original documents receipt, Admission register.

**Reports:** Live seat matrix/vacancy, Admissions by quota/category/gender/state (AQAR 2.1.1, 2.1.2;
NIRF), Pending documents, Enquiry funnel by source, Refund register, AICTE intake vs admitted.

**Integrations:** Counselling allotment import (CSV/Excel), payment gateway (application fee),
WhatsApp follow-up, DigiLocker fetch (P2), state student ID (UMIS) export (P2).

**Key logic:** the seat matrix is derived from submitted Program Enrollments (not hand-edited).
Eligibility is evaluated from rule records. Reminders run as a daily job for pending documents.

---

## 7. Student Services (M05)

**Features:** M05-01 onboarding; M05-02 attendance eligibility, condonation, medical leave, OD;
M05-03 progression and probation (GPA/CGPA computed in M06); M05-04 QR-verifiable certificates;
M05-05 scholarships and concessions; M05-06 grievance with escalation and SLA; M05-07 mentoring,
counselling, health, insurance; M05-08 clubs, NSS/NCC, events.

**Reuse:** Student, Guardian, Program Enrollment, Student Group, Student Attendance, Student
Attendance Tool, Student Leave Application, Student Log, Course Schedule.

**Custom fields**
- Student: `oc_company`, `oc_register_no`, `oc_roll_no`, `oc_regulation`, `oc_batch`,
  `oc_admission_quota`, `oc_current_semester`, `oc_section`, `oc_mentor`, `oc_class_advisor`,
  `oc_academic_status` (Active / Detained / Discontinued / Completed / Long Absent),
  `oc_hostel_resident`, `oc_transport_user`, `oc_abc_id`, `oc_first_graduate`, `oc_differently_abled`, `oc_lateral_entry`.
- Student Leave Application: `oc_leave_kind` (Leave / Medical / On Duty), `oc_certificate`.

**Masters:** Attendance Rule (regulation: min %, condonation band and fee, whether medical/OD
count), Progression Rule (regulation: arrear limits, year-back, probation), Certificate Type
(print format, approval policy, fee, validity, verifiable), Scholarship Scheme (government /
institutional, eligibility, renewal criteria, amount rule), Grievance Category (escalation
via Approval Policy + SLA), Club / Activity Unit (NSS, NCC, clubs; coordinator position).

**Transactions:** Onboarding Checklist (ID card, library, bus, hostel, mentor, code-of-conduct
acknowledgement, anti-ragging affidavit upload), Attendance Eligibility Run (term → % per student
per course, shortage flags), Condonation Request, Progression Run (term end → promote / detain /
probation), Certificate Request → issued certificate (Verifiable Document), Transfer Certificate,
Scholarship Application and Disbursement (sanction → credit to student ledger), Fee Concession,
Student Grievance, Mentor Meeting Log, Counselling Record (confidential), Health Record,
Insurance Policy, Activity Event and Participation.

**Settings:** Student Services Settings: certificate numbering, affidavit required, mentor ratio target.

**Print formats:** ID card, Bonafide, Conduct, TC (state format), Migration, Course completion,
Attendance shortage notice, Condonation form, Participation certificate.

**Reports:** Attendance % by course/student, Shortage list, Condonation register, Strength by
program/semester/category (extended profile 2.1), Scholarship beneficiaries (AQAR 5.1.1/5.1.2),
Grievance SLA, Mentor-student ratio (2.3.3), Progression/dropout, Diversity (gender, category,
state - NIRF), TC register.

**Integrations:** biometric/RFID attendance (push API), state scholarship portals (file
import/export), DigiLocker issue (P2).

**Key logic:** attendance % = (present + OD [+ medical if rule allows]) / conducted, per
course offering. Threshold, condonation band and counting rules come from the student's regulation.
Shortage blocks exam registration through `examinations.api.eligibility`.

---

## 8. Examinations / COE (M06)

**Features:** M06-01 calendar, notification, eligibility, registration (regular/arrear/
supplementary), exam fees; M06-02 hall tickets, seating, invigilation, attendance sheets,
malpractice; M06-03 question paper workflow with confidential release and print log; M06-04
dummy numbers, script tracking, valuation allocation, remuneration; M06-05 mark entry, moderation,
grace, results, grade sheets; M06-06 revaluation/photocopy/scrutiny, result publication with passing
board approval; M06-07 transcripts, provisional/degree certificates, convocation; M06-08 CIA
schedule, marks lock, audit; M06-09 OMR/on-screen valuation (P3).

**Reuse:** Grading Scale (+ `oc_grade_point`, `oc_is_pass` on Grading Scale Interval), Room,
Employee/Instructor, Sales Invoice (exam fee via Fee Category "Exam Fee"), HRMS Additional Salary
(internal examiner remuneration), Purchase Invoice (external examiners as Suppliers), Body & Meeting
(passing board).

Decision: education's Assessment Plan/Result is **not** the marks store. It is criterion-level only.
We build question-level CIA/ESE marks, and can optionally write a summary back to Assessment Result for the old portal.

**Masters:** Exam Rule Set (regulation: CIA/ESE weights, ESE min %, total min %, grace rules,
absent handling, max attempts, revaluation fee/window, third-valuation difference threshold,
moderation limits), Grading Scheme (Grading Scale + letter codes such as RA/AB/W/SA), Exam Type,
CIA Component Template (per course type: tests, assignments, quiz, model exam; max, weight,
conversion), Exam Hall (Room + rows × columns layout), Examiner (Employee or external member, subject
panel, bank details), Remuneration Rate (setting, scrutiny, per-script valuation, invigilation per
session, squad), Exam Fee Rate (course/type, late fee slabs), Malpractice Category (punishment
options), Dummy Number Series.

**Transactions**
- Exam Session (e.g. Nov 2026): company, term, exam types, dates (registration, fee, exams, result target), status.
- Exam Schedule: session, course, date, slot.
- Exam Registration: student, session, courses (regular + arrear), eligibility (attendance, dues,
  detention), fee → Sales Invoice. Bulk generation job.
- Hall Ticket (generated per registration; withheld if ineligible).
- Seating Plan (session/date/slot/hall allocations), Invigilation Duty, Exam Attendance (per script, barcode), Malpractice Report.
- QP Setter Nomination, Question Bank Item (course, CO, Bloom level, marks, difficulty; restricted),
  Question Paper (pattern, sets, moderation, encrypted file, release-at), QP Access Log.
- Dummy Number Map (restricted role), Answer Script Bundle (movement log), Valuation Allocation,
  Valuation Entry (dummy no, question-wise marks, valuation round), Examiner Remuneration Claim.
- CIA Schedule, CIA Mark Entry (course offering, component, question-wise per CO, lock at deadline,
  unlock request via approval), CIA Consolidation.
- Mark Moderation, Result Run (session + program; versioned, re-runnable), Student Result (per
  student per session: courses, marks, grade, grade point, result; SGPA, CGPA, arrears),
  Result Publication (release-at; passing board resolution link).
- Revaluation Application (photocopy / retotal / revaluation), Revaluation Outcome (new Student
  Result version).
- Transcript Request, Provisional Certificate, Degree Certificate record, Convocation List.

**Settings:** Examination Settings (per company): confidential roles, release approval required,
barcode on, dummy number format, result SMS on.

**Print formats:** Exam notification, Timetable, Hall ticket (photo + QR), Seating chart, Hall
attendance sheet, Invigilation order, QP cover and packet label, Script barcode labels, Grade
sheet (QR), Consolidated mark sheet, Provisional certificate, Degree certificate, Transcript,
Revaluation result letter, Remuneration bill, Malpractice report.

**Reports:** Registration summary, Eligibility (withheld) list, Exam attendance/absentee, Valuation
progress, First vs second valuation difference, Result analysis (pass % by course/faculty/program -
AQAR 2.6.3, NBA), Rank list, Arrear list, Days exam-end → result (2.5.1), Revaluation change and
complaint ratio (2.5.2), Grace mark audit, Remuneration register, Malpractice register.

**Integrations:** OMR import, barcode printing, on-screen valuation (P3), SMS/WhatsApp results,
DigiLocker/NAD mark sheet upload (P2), affiliating university result export.

**Key logic**
- Confidentiality: Dummy Number Map, Question Bank Item and Question Paper are readable only by
  "Exam Confidential". Marks fields use permlevel 1 until publication. A permission query hides
  Student Result from students before release-at. Every read of confidential docs is logged.
- Result Run applies the **student's regulation** Exam Rule Set: combine CIA + ESE, apply grace,
  grade from the Grading Scheme, then SGPA = Σ(credit × GP) / Σ credits (passed + failed per rule),
  then CGPA. Output is versioned. A re-run never mutates published results; it creates a new version.
- Bulk jobs (hall tickets, results) run in chunks, are idempotent per student, and report progress.

---

## 9. Remaining modules

### 9.1 Academic Governance (M02)

**Features:** M02-01 bodies and members with terms; M02-02 BoS → committee → AC → GC proposals
with versions; M02-03 meetings (notice, agenda, quorum, minutes, resolutions, actions, e-sign);
M02-04 approved syllabus becomes effective for a regulation/batch; M02-05 external members, honorarium, TA/DA.

**Masters:** Body Type (BoS, Academic Council, Governing Council, Finance Committee, IQAC,
Anti-Ragging, Grievance, ICC, SC/ST Cell, Disciplinary, Passing Board, IEC, …; min meetings per
year, required composition), Body (company, type, department, members child with category
internal/external expert/industry/alumni/student/university nominee and term), External Member
(organisation, expertise, PAN, bank; linked Supplier for payment), Proposal Type (route → Approval Policy).

**Transactions:** Academic Proposal (type, department, regulation, linked Curriculum draft,
versions, stage), Meeting (body, notice, agenda child linking proposals, attendance, quorum check,
minutes, resolutions child), Action Item (owner, due, status, action-taken note), Honorarium
Claim → Purchase Invoice with TDS.

**Settings:** Governance Settings (notice days, quorum rule, resolution numbering).
**Print:** Notice, Agenda, Minutes, Resolution extract, Action Taken Report, Honorarium voucher.
**Reports:** Proposal tracker by stage, Resolution register, Body composition compliance, Meeting
frequency vs required, Syllabus revisions (AQAR 1.1.2, 1.2.1).
**Integrations:** e-sign provider (Aadhaar eSign/DSC, P1), email/WhatsApp notices.
**Key logic:** GC approval of a curriculum proposal sets Curriculum status Effective for the
regulation and batches (M02-04).

### 9.2 Faculty (M07)

**Features:** M07-01 recruitment and qualification checks; M07-02 workload; M07-03 timetable with
constraints, leave and substitution; M07-04 API self-appraisal, student feedback, HOD review, CAS;
M07-05 FDPs and conferences with evidence; M07-06 profile with publications/patents/projects,
IRINS/ORCID/Scopus; M07-07 payroll for aided and self-financing staff.

**Reuse (HRMS heavy):** Employee, Employee Education, Job Requisition/Opening/Applicant,
Interview, Job Offer, Appointment Letter, Employee Promotion, Appraisal Cycle/Template/KRA,
Training Program/Event/Feedback, Leave Application, Attendance, Employee Checkin, Shift Type,
Salary Structure, Payroll Entry, Income Tax Slab, Additional Salary, Employee Grade.

**Custom fields on Employee:** `oc_staff_type` (Teaching / Non-teaching / Project), `oc_cadre`,
`oc_aicte_faculty_id`, `oc_highest_qualification`, `oc_phd_status`, `oc_phd_awarded_on`,
`oc_specialisation`, `oc_research_guide`, `oc_orcid`, `oc_scopus_id`, `oc_vidwan_irins_url`,
`oc_funding_mode` (Aided / Self-financing), `oc_pay_scale`, `oc_sanctioned_post`.

**Masters:** Faculty Norm (AICTE/UGC qualification by cadre, cadre ratio, student-faculty ratio;
versioned), Sanctioned Post (department, cadre, count, year), Workload Norm (cadre → hours),
Timetable Slot Template (periods, timings, breaks), API Score Rule (activity → points, caps; versioned).

**Transactions:** Course Allocation (term, offering ↔ faculty, L/T/P hours), Timetable (section
grid) → Course Schedule entries, Timetable Generation Run (solver job), Substitution (linked to
Leave Application), Faculty Achievement (FDP, conference, resource person, award, membership;
evidence), Self-Appraisal (computes API from records → HRMS Appraisal), CAS Application (P2).

**Print:** Workload statement, Timetable (class/faculty/room), Substitution order, Faculty profile
(CV), Appraisal summary, Experience certificate.
**Reports:** Workload balance, Faculty vs sanctioned posts (2.4.1), PhD faculty (2.4.2),
Experience (2.4.3), Cadre ratio, Student-teacher ratio (2.2.2), FDP participation (6.3.4),
Conference support (6.3.2), Timetable clashes, NIRF faculty sheet.
**Integrations:** biometrics via Employee Checkin API, ORCID/Scopus/IRINS sync (P1/P2), AICTE faculty export.
**Key logic:** timetable solver = constraint model (faculty availability, rooms/labs, consecutive lab
periods, max per day, electives in parallel) run as a background job using OR-Tools CP-SAT. Output
is written as Course Schedules so education attendance keeps working.

### 9.3 IQAC & Accreditation (M01)

**Features:** M01-01 evidence repository; M01-02 metric engine with versioned formulas; M01-03
AQAR/SSR/NBA SAR/NIRF exports with pre-validation; M01-04 IQAC calendar, minutes, ATR; M01-05
feedback surveys; M01-06 statutory committees; M01-07 regulator submission tracker.

**Masters**
- Accreditation Framework: code (NAAC-AQAR-RAF2017, NAAC-SSR-RAF2017, NAAC-DCF2025, NBA-SAR-UG,
  NIRF-2027 …), version, valid from/to, segments, status (Draft/Published/Retired; published = immutable).
- Framework Node (tree): code (2.6.3, 2.6.3.1), title, node type (Criterion / Key Indicator /
  Metric / Sub-metric / Profile), answer type (Number / Percent / Choice / Narrative / File / Table),
  choices, word limit, unit, period (AY / FY / last N years), formula (expression over data point
  keys), department-wise flag, evidence slots (child: name such as "Data Template", required, file types), owner role.
- Data Point: key (e.g. `students_admitted`), source method (registered function in
  `campus.<module>.metrics`), parameters, description. **This is the only code-level piece.** Formulas stay data.
- Feedback Form (questions: Likert / choice / text, CO link optional), Regulator Submission Type
  (AICTE EoA, affiliation renewal, AISHE, NIRF, NBA, autonomy extension; frequency, due rule, owner),
  Institutional MoU (shared with research/placement; partner, purpose, period, activities).

**Transactions:** Accreditation Cycle (framework, company, period, status Collecting → Validating
→ IQAC Review → Approved → Submitted), Metric Value (cycle, node, department, computed value,
manual override + reason, narrative, choice, status, source snapshot JSON with record links),
Evidence (file/URL, nodes, year, department, source dynamic link, public flag/URL), Feedback
Campaign (form, audience, window, anonymity) and Feedback Response, Regulator Submission (type,
period, due, status, documents), Perspective Plan and Annual Benchmark (6.2.1, P2). Meetings,
committees and ATR reuse Body & Meeting from M02.

**Settings:** IQAC Settings (default framework per segment, reminder cadence, lock after approval).
**Print/exports:** AQAR (Excel per template + PDF), SSR, NBA SAR, NIRF data sheets, per-metric Data
Template (Excel), Pre-validation report, IQAC minutes, ATR.
**Reports:** Readiness dashboard (metric completion %, evidence missing), 5-year metric trends,
Department contribution, Evidence register, Committee compliance, Feedback analysis, Regulator calendar.
**Integrations:** export-only for NAAC portal/DCF, NIRF DCS, AISHE (no official APIs assumed).
Official templates must be supplied. Until then, seed only AQAR RAF 2017 nodes from the SXCCE document structure.
**Key logic:** compute = evaluate each node's formula with data points (company, period, department)
via `frappe.safe_eval`, store value + snapshot. Overrides need a reason and approval. Pre-validation
checks required evidence slots, word limits and cross-metric consistency (e.g. 2.1.2 ≤ profile 4.1).

### 9.4 Research & Funded Projects (M08)

**Features:** M08-01 centres; M08-02 proposals; M08-03 sanction register; M08-04 budget heads and
re-appropriation; M08-05 project ledger in ERPNext; M08-06 UC/SOE; M08-07 PFMS EAT/UC
export/import; M08-08 progress, milestones, closure, asset handover; M08-09 project staff;
M08-10 consultancy with GST and revenue share; M08-11 IPR; M08-12 publications; M08-13 PhD scholars
(P2); M08-14 ethics (P2); M08-15 instrument booking (P2).

**Reuse:** Project (one per sanction), Project Task/Milestone, Cost Center, Budget (control by
project cost center and account), Purchase Order/Invoice, Payment Entry, Journal Entry, Asset,
Asset Movement, Supplier, Customer, Sales Invoice (consultancy), Employee + Salary Structure
(project staff/fellowships), Additional Salary (revenue share).

**Custom fields:** `oc_budget_head` on Purchase Order Item, Purchase Invoice Item, Journal Entry
Account, Expense Claim Detail; `oc_sanction` on Project; `oc_pfms_vendor_code` on Supplier.

**Masters:** Funding Agency (PFMS agency code, UC format), Funding Scheme (head template, overhead %,
instalment pattern, UC/SOE format), Grant Budget Head (Equipment, Consumables, Manpower, Travel,
Contingency, Overheads → Account/Item Group mapping), Research Centre, Journal (ISSN, indexing,
UGC-CARE flag), IPR Type.

**Transactions:** Research Call, Research Proposal (internal review via approval), Sanction (order
no/date, PI/co-PIs, duration, heads child, instalments child; on submit creates Project + Cost
Center + Budget), Grant Receipt (instalment → grant liability), Re-appropriation Request (agency
approval attachment → Budget update), Utilisation Certificate (period, opening, receipts, interest,
head-wise expenditure from GL, closing; versioned), Statement of Expenditure, PFMS Export Batch
(EAT expenditure/advance/transfer rows, vendor check, status import), Progress Report, Project
Closure (final UC, refund, asset handover), Consultancy Project (estimate, agreement, invoice,
revenue share), Invention Disclosure and Patent (lifecycle, costs, licensing), Publication (authors,
journal, indexing, DOI, citations), Research Scholar (P2), Ethics Approval (P2), Instrument Booking (P2).
Seed money (AQAR 3.1.2) = Sanction with agency "Institution".

**Settings:** Research Settings (grant liability and income accounts, overhead posting, interest handling, PFMS unique agency code).
**Print:** Sanction extract, UC (GFR 12-A + agency formats), SOE, Re-appropriation letter, Completion report, Consultancy agreement.
**Reports:** Sanction register, Project grant ledger (receipts/expenditure/balance by head),
Budget vs actual by head, UC due/overdue, PFMS export status, AQAR 3.2.1/3.2.2/3.2.3/3.2.4,
3.4.3/3.4.4/3.4.5/3.4.6, 3.5.1, patents, NIRF RPC sheets (3-year sponsored research and consultancy).
**Integrations:** PFMS (file adapter first, API adapter later), Crossref/Scopus/ORCID metadata, IRINS.
**Key logic:** UC and SOE are computed **only from GL** (project dimension + head→account map),
never typed. ERPNext Budget enforces head limits (Stop/Warn per scheme). Grant accounting method
(liability vs income) is a Research Settings choice. Confirm with the accountant.

### 9.5 Campus Finance (M09)

**Features:** M09-01 fee heads, concessions, refunds, fines, challan/receipt; M09-02 multi-account and
cost-centre mapping; M09-03 budgets; M09-04 student ledger across modules and companies;
M09-05 audit pack; M09-06 more gateways and e-challan.

**Reuse:** Fee Category (+ Item defaults per company), Fee Structure, Fee Schedule → Sales Invoice
(education already adds `student` on Sales Invoice), Payment Request, Payment Entry, Payment Gateway
Account, Budget, Cost Center, Accounting Dimension, Bank Statement Import, standard ledgers and day book.

**Custom fields:** Fee Category `oc_fee_head_type` (Tuition / Exam / Hostel / Mess / Transport /
Library / Lab / Development / Caution Deposit / Fine), `oc_refundable`, `oc_gst_applicable`;
Account `oc_naac_expense_class` (for AQAR 4.1.4, 4.4.1, profile 4.4).

**Masters:** Fine Rule (fee category, grace days, slabs), Fee Instalment Plan, Challan Format (bank).
**Transactions:** Fine Run (scheduled), Challan generation and bank collection import → Payment
Entry, Fee Refund (Credit Note + Payment Entry), Caution Deposit Refund, No-Dues Clearance.
**Settings:** Campus Finance Settings (per company: gateway, receipt series, fine posting account).
**Print:** Fee receipt, Bank challan, Demand notice, Refund voucher, No-dues certificate, Student ledger statement.
**Reports:** Student Fee Ledger (all companies by student), Collection by head/program/quota,
Outstanding aging, Concession/scholarship register, Department budget vs actual, Audit pack bundle,
NAAC/NIRF expenditure sheets.
**Integrations:** Razorpay (existing), PayU/Cashfree/BillDesk, SBI Collect/e-challan, bank file
import; recommend `india_compliance` for GST/TDS.
**Key logic:** `campus_finance.api.has_dues(student, scopes)` aggregates outstanding Sales Invoices
for the student's Customer across companies (college + trust). It is used by hall tickets, TC and certificates.

### 9.6 Hostel & Mess (M10) - trust-owned

**Features:** M10-01 hostel/block/floor/room/bed; M10-02 allotment by rules, transfers, waitlist;
M10-03 mess menu, attendance, monthly billing, rebates; M10-04 outpass with guardian alert, visitor
log; M10-05 warden dashboard, complaints, room inventory; M10-06 fee/refund and mess store stock.

**Reuse:** trust Company, Sales Invoice, Fee Category, Warehouse/Item/Material Request/Purchase
Receipt/Stock Entry (mess store), Asset (room furniture), Issue + SLA (complaints).

**Masters:** Hostel (company = trust, gender, served colleges via Shared Service Agreement),
Hostel Block, Hostel Floor, Hostel Room (type, capacity, AC, rate), Hostel Bed, Hostel Fee Rate
(per year/room type), Allotment Rule (priority order, gender, year, category, distance), Mess (type,
warehouse), Mess Menu Template (weekly cycle), Mess Plan (fixed / dividing / per meal; rebate rule),
Outpass Rule (approvers, curfew, guardian notification).

**Transactions:** Hostel Application, Allotment Run (bulk), Hostel Allotment, Room Transfer, Hostel
Vacating (inventory check, damages, deposit refund), Mess Leave/Rebate, Mess Billing Run (monthly;
dividing system = mess cost from stock issues + staff ÷ man-days) → Sales Invoice by trust, Outpass,
Gate Movement (out/in), Visitor Log, Night Roll Call, Room Inventory Check.

**Settings:** Hostel Settings (trust company, fee categories, curfew, rebate defaults).
**Print:** Allotment order, Room card, Outpass slip (QR), Mess bill, Vacating clearance.
**Reports:** Occupancy/vacancy, Allotment by college/program/year/category, Waitlist, Mess cost per
day, Outpass register and late returns, Complaint SLA, Hostel dues.
**Integrations:** RFID/biometric gate, WhatsApp guardian alerts.
**Key logic:** hostel users get User Permission on all member colleges but role-limited read on
Student. All invoices come from the trust company with `student` set, so they land in the
cross-company student ledger.

### 9.7 Transport (M11)

**Features:** M11-01 routes, stops, vehicles, drivers, allocation; M11-02 distance/zone fees,
passes; M11-03 GPS and ETA alerts (P2); M11-04 route optimisation (P2); M11-05 fuel, maintenance,
FC/insurance expiry, driver payroll.

**Reuse:** Vehicle (+ `oc_fc_expiry`, `oc_permit_expiry`, `oc_puc_expiry`, `oc_seating`), Driver,
Employee, Vehicle Log (fuel/odometer), Asset + Asset Maintenance, Fee Category "Transport".
**Masters:** Bus Stop (geo), Route (stops child: sequence, time, distance), Transport Fee Slab (zone/distance).
**Transactions:** Transport Registration (student/staff, stop, year) → fee invoice, Bus Pass (QR),
Route Change Request, Vehicle Incident, Trip Attendance (P2 RFID).
**Settings:** Transport Settings (provider company from Shared Service Agreement, fee basis).
**Print:** Bus pass, Route chart.
**Reports:** Route occupancy vs seats, Students by stop, Transport dues, Vehicle document expiry, Fuel efficiency.
**Integrations:** GPS vendor API (P2), OSRM/Google for optimisation (P2), WhatsApp ETA alerts.

### 9.8 Labs & Facilities (M12)

**Features:** M12-01 lab equipment, AMC, calibration; M12-02 slot allocation with conflict
detection; M12-03 consumables indent → purchase; M12-04 experiments, records, CO, viva marks;
M12-05 safety logs, incidents; M12-06 nursing clinical rotations, logbooks, preceptor sign-off,
INC records (P0 nursing); M12-07 facility booking.

**Reuse:** Room (+ `oc_room_type` Classroom/Lab/Seminar Hall/Skill Lab, `oc_ict_enabled`,
`oc_department`, `oc_block`), Asset, Asset Maintenance, Asset Repair, Location, Material Request,
Purchase Order, Stock Entry, Course Schedule.
**Masters:** Laboratory (room, department, in-charge, technician, courses), Experiment (course +
curriculum, CO, equipment), Safety Checklist Template, Clinical Site (hospital, wards, capacity,
MoU), Clinical Requirement (INC hours per area/year, procedure counts), Nursing Procedure.
**Transactions:** Lab Batch split, Lab Record (experiment marks, viva, CO → CIA practical
component), Safety Inspection, Lab Incident, Clinical Rotation Schedule (batch × site × ward ×
period; conflict check), Clinical Logbook Entry (procedure, count, preceptor sign-off), Facility Booking.
**Print:** Experiment list, Record certificate, Lab stock register, Rotation chart, INC logbook.
**Reports:** Lab equipment register (NBA), Equipment utilisation, AMC/calibration due, Consumables
by lab, Clinical hours vs INC requirement, Facility utilisation, ICT classrooms (4.1.3).

### 9.9 Placement & Internships (M14)

**Features:** M14-01 recruiters and drive pipeline; M14-02 eligibility and shortlisting; M14-03
offers, packages, analytics, higher studies; M14-04 internships, MoUs, capstone projects; M14-05
certifications and training; M14-06 industry MoUs.

**Masters:** Recruiter (industry, contacts, MoU), Placement Eligibility Template, Certification
Type (NPTEL, vendor), Institutional MoU (shared).
**Transactions:** Placement Drive (roles, CTC, eligibility: CGPA, standing arrears, branches, batch;
rounds), Drive Registration (auto eligibility from M06), Round Result, Placement Offer (CTC, offer
letter, accepted, joined), Higher Studies Record (exam, score, admitted institution), Internship
(org, period, mentor, report, marks → credit), Capstone Project (team, guide, reviews, marks),
Training Attendance, Certification Record.
**Settings:** Placement Settings (one-offer rule, dream-offer threshold).
**Print:** Drive notice, Offer register, Internship certificate, NOC.
**Reports:** Placement by department/gender/package (AQAR 5.2.1; NIRF median salary), Higher
studies (5.2.2), Competitive exams (5.2.3), Internships (1.3.4), Recruiter-wise offers, Eligible
but not placed, NBA placement table.

### 9.10 Alumni (M15)

**Features:** M15-01 registration, verification, directory, chapters; M15-02 events, newsletters,
jobs, mentorship; M15-03 donations with 80G; M15-04 feedback and contribution evidence.

**Masters:** Alumni (student link, verified, employer, location, chapter), Alumni Chapter, Donation Campaign.
**Transactions:** Alumni Registration (web form → department verification), Alumni Event and
Attendance, Mentorship Pairing, Alumni Job Post, Donation (payment, 80G receipt, Form 10BD data),
Alumni Contribution (non-financial), Alumni Feedback (Feedback Campaign).
**Print:** 80G receipt, Alumni ID, Event certificate.
**Reports:** Directory, Contribution summary (5.4.2 bands), Donation register and 10BD export, Chapter activity.

### 9.11 Library Integration (M13)

**Features:** M13-01 Koha/SOUL integration (member sync, dues to fee ledger, usage stats);
M13-03 e-resource subscriptions; M13-04 repository/Shodhganga links. M13-02 (own ILMS) is not planned.
**Masters/Settings:** Library Integration Settings (system, endpoint, credentials, schedule), E-Resource (N-LIST, DELNET, IEEE; cost, period).
**Transactions:** Member Sync Job, Library Dues Import → Sales Invoice, Usage Stats Import.
**Reports:** Library usage per day (4.2.4), Book/journal expenditure (4.2.3), E-resources (4.2.2), Library no-dues.

---

## 10. Integrations inventory

Pattern: `<System> Settings` (per company where needed) + adapter class in `campus/integrations/<system>.py`
+ Frappe Integration Request log + idempotent background job. Each adapter has a file mode first.

| System | Module | Mode (first) | Later | Priority |
|---|---|---|---|---|
| PFMS EAT / UC / SOE | M08 | Structured file export/import | API adapter if agency access | P0 |
| WhatsApp Business | M16 | `frappe_whatsapp` / BSP API | - | P0 |
| SMS (DLT) | M16 | Gateway API | - | P0 |
| Payment gateways | M09, M04 | Razorpay (existing) | PayU, Cashfree, BillDesk, SBI Collect | P0 |
| Counselling allotment (TNEA etc.) | M04 | File import | - | P1 |
| State scholarship portals | M05 | File import/export | - | P1 |
| Biometric / RFID | M05, M07, M10 | Device push API → Student Attendance / Employee Checkin / Gate Movement | - | P2 |
| ORCID / Scopus / Crossref / IRINS | M07, M08 | API/import | - | P2 |
| DigiLocker / NAD / ABC | M05, M06, M03 | Export files | API | P2 |
| GPS | M11 | Vendor API | - | P2 |
| Koha / SOUL | M13 | Koha REST / SOUL file | - | P3 |
| OMR / on-screen valuation | M06 | File import | - | P3 |
| Regulator portals (NAAC, NIRF, AISHE, AICTE) | M01 | Export only | - | P0 (exports) |

---

## 11. Roles

| Role | Scope | Notes |
|---|---|---|
| Campus Admin | Trust | Settings, packs, policies |
| Principal | Company | Approvals, dashboards |
| Dean (Academic / Research / Student Affairs) | Company | Via Position |
| HOD | Department | Via Position (department scope) |
| Faculty | Own offerings | Extends education "Instructor" |
| Class Advisor / Mentor | Student Group | Via Position, not a role |
| IQAC Coordinator / IQAC Member | Company | Metric values, evidence |
| COE / Exam Cell | Company | Exam operations |
| Exam Confidential | Company | QP, dummy numbers, pre-release marks |
| External Examiner | Assigned bundles | Portal user |
| Admission Officer / Registrar | Company | Admissions, certificates |
| Accounts User / Manager | Company/Trust | ERPNext roles |
| Research Dean / PI | Company / own projects | |
| Warden / Mess Manager | Hostel | Trust company |
| Transport Officer | Trust | |
| Lab In-charge | Lab | |
| Librarian | Company | |
| TPO | Company | |
| Alumni Officer | Company | |
| Student / Guardian / Alumni | Self | Portal |
| Auditor / Assessor (read-only) | Scoped | Evidence portal, time-bound |

---

## 12. Build sequence and status

| Phase | Deliverable | Key DocTypes | Status |
|---|---|---|---|
| 1.0 | Scaffold `campus`, fixtures, Company custom fields | Institution Profile, Module Pack, Campus Settings | Not started |
| 1.1 | Regulation model, positions, approval engine | Regulation, Position, Position Holder, Approval Policy/Request/Delegation | Not started |
| 1.2 | Messaging bus | Message Template, Consent, Broadcast, Message Log, Circular | Not started |
| 1.3 | Curriculum core | Course Category, Curriculum, Elective Group, Course Registration | Not started |
| 1.4 | Admissions | Admission Quota, Seat Matrix, Allotment Import, Document Verification | Not started |
| 1.5 | Student services core + finance core | Attendance Rule, Eligibility Run, Certificate Type, Fine Rule, Student Fee Ledger | Not started |
| 2.x | COE, Governance, Faculty | Exam Session … Student Result; Body, Meeting, Proposal; Course Allocation, Timetable | Not started |
| 3.x | IQAC, OBE, Research | Framework, Node, Data Point, Metric Value, Evidence; CO/PO attainment; Sanction … UC | Not started |
| 4.x | Hostel, Transport, Labs, Placement | per section 9 | Not started |
| 5.x | Alumni, Library, Nursing and Deemed packs | per section 9 | Not started |

Vertical slices from AGENTS.md §9 that run alongside: **M08 funded project** (Sanction → Budget →
Project/Cost Center ledger → UC/SOE export) and **M06 exam skeleton** (Session → Registration →
Hall Ticket → Mark Entry → Result).

---

## 13. Open questions

Resolved 4 Oct 2026: grant accounting (D9), apps (D10), degree issuer (D11), Aadhaar (D12), portal (D13),
Anna University rules (D14 + `docs/research/anna-university-autonomous-rules.md`).

Still open:
1. Transport: trust-owned like hostel? (Assumed yes, configurable via Shared Service Agreement.)
2. Pilot college's current regulations: we use SXCCE R2022 and R2026 as reference fixtures until the pilot shares its own.
3. Official templates: NAAC DCF 2025, NBA SAR (current), NIRF DCS, agency UC/SOE formats, PFMS EAT file spec.
4. Auditor sign-off on D9 grant accounting.

Phase task docs: `docs/phases/`.
