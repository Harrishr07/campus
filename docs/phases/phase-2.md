# Phase 2 - Autonomy core (COE, Academic Governance, Faculty)

Goal: an autonomous college frames and approves its own curriculum through BoS → Academic Council →
Governing Body, plans faculty workload and timetables, and runs the full exam cycle from internal
assessment to results, revaluation, grade sheets and the convocation list. Each batch is graded by its own regulation.

BRD: M02-01..05, M06-01..08, M07-01..05, M07-07 (setup), M05-03.
Prerequisites (from Phase 1): app scaffold and test site (P1-T01), demo data (T02), company scoping (T03),
Institution Profile with `degree_awarding_body` (T04), Regulation model (T05), positions (T06),
approval engine (T07), verifiable documents (T08), bulk runner (T09), messaging (T10),
curriculum and course offerings/registration (T12, T13), attendance eligibility and attendance marks (T19),
`has_dues` (T24), portal shell (T26).
Rule reference: `docs/research/anna-university-autonomous-rules.md` (AU-R2021, SXCCE R2022, R2026).

Exit demo: BoS approves a new elective → AC → GB approval makes R2026 curriculum v2 effective for the 2026 batch →
HOD allocates courses, timetable generated → CIA entered and locked → exam registration with one SA
student blocked → hall tickets → seating → QP released at exam time → dummy numbers, double valuation →
result run (R2022 batch relative grading, R2026 batch absolute) → passing board approval → publication
at 10:00 → one revaluation changes a grade → grade sheet with QR → convocation list export.

---

## A. Academic governance (M02)

### P2-T01 Bodies, members and composition rules
BRD: M02-01, M01-06 (shared) | Depends on: P1-T06 | Size: M
Deliverables: Body Type (min meetings per year, term years, composition rule child: member category, min/max count, mandatory-for-quorum flag),
Body (company, type, department, members child with category, person (Employee / External Member), from/to), External Member (organisation, expertise, PAN, bank, linked Supplier).
Seed Body Types from UGC 2023 cl. 12: Governing Body (5-year term, 6-monthly, ≥50% quorum + university nominee), Academic Council (3 university nominees), Board of Studies, Finance Committee; non-statutory: Planning & Evaluation, Grievance, Examination, Admission, Library, ICC, Anti-Ragging, Class Committee, Course Committee, Passing Board, IQAC.
Acceptance criteria
1. Saving a Governing Body without a university nominee fails composition validation with the rule shown.
2. A member whose term has ended is excluded from quorum counts after the end date.
3. Report "Body composition compliance" lists violations across bodies.
Tests: U - composition validator. I - term expiry, report.

### P2-T02 Meetings, minutes, resolutions, action items
BRD: M02-03, M01-04 | Depends on: T01, P1-T10 | Size: M
Deliverables: Meeting (body, date, venue/online link, notice sent on, agenda child (item, proposal link, presenter), attendance child, quorum computed, minutes, resolutions child (number, text, decision, linked proposal)), Action Item (owner, due, status, action taken).
Notice via messaging. Prints: Notice, Agenda, Minutes, Resolution extract, Action Taken Report. E-sign: adapter interface only (provider in Phase 5).
Acceptance criteria
1. Notice can't be sent later than the Governance Settings notice-days before the meeting without an override reason.
2. Quorum shows Met/Not met using the body type rule. Resolutions can't be recorded when quorum isn't met.
3. Resolution numbers are unique per body per year.
4. Overdue action items notify their owners weekly.
Tests: U - quorum rule (50% + mandatory member). I - notice timing, resolution numbering, action reminder job.

### P2-T03 Academic proposals and effective curriculum
BRD: M02-02, M02-04 | Depends on: T02, P1-T07, P1-T12 | Size: L
Deliverables: Proposal Type (new course, syllabus revision, new elective, regulation change, new programme; route), Academic Proposal (type, department, regulation, linked Curriculum draft version, attachments with version history, stage, resolutions per stage).
Route BoS → Academic Council → Governing Body (per type), each stage needing a resolution from a quorate meeting of that body.
On final approval: Curriculum → Effective (for the regulation and listed batches), Regulation → Effective (if a regulation change), approving resolution linked on the record.
Reports: Proposal tracker, Syllabus revisions per year (AQAR 1.1.2, 1.2.1 data points).
Acceptance criteria
1. A proposal can't move to AC without a BoS resolution referencing it.
2. GB approval makes curriculum v2 Effective for the 2026 batch only. 2022-batch students still resolve to v1.
3. The comment trail and document versions are preserved and visible to IQAC.
Tests: I - full route with meetings, effective-version resolution per batch, block on missing resolution.

### P2-T04 External member honorarium
BRD: M02-05 | Depends on: T01 | Size: S
Deliverables: Honorarium Claim (member, meeting, honorarium, TA/DA, TDS section) → Purchase Invoice (Supplier) with TDS via india_compliance. Print: honorarium voucher.
Acceptance criteria
1. A claim creates a draft Purchase Invoice with TDS withheld per the section threshold.
Tests: I - PI creation and TDS amounts.

## B. Faculty (M07)

### P2-T05 Faculty profile, norms, sanctioned posts
BRD: M07-01, M07-06 (fields) | Depends on: P1-T03 | Size: M
Deliverables: Employee custom fields (blueprint 9.2). Faculty Norm (versioned: qualification by cadre, cadre ratio, student-faculty ratio), Sanctioned Post (department, cadre, year, count).
Qualification check against norm on Job Applicant / Employee. Reports: Faculty vs sanctioned posts (2.4.1), PhD faculty (2.4.2), Teaching experience (2.4.3), Cadre ratio, Student-teacher ratio (2.2.2).
Acceptance criteria
1. Appointing an Assistant Professor without the required qualification is flagged, and needs Principal override with a reason.
2. The reports reproduce the demo fixture numbers. Data point functions are registered for Phase 3.
Tests: U - norm checks. I - reports vs fixture.

### P2-T06 Course allocation and workload
BRD: M07-02 | Depends on: P1-T13, T05 | Size: M
Deliverables: Workload Norm (cadre → min/max hours per week), Course Allocation (term, department; rows: offering, faculty, L/T/P hours; approval by HOD), updates Student Group instructors.
Report: Workload balance (per faculty vs norm, department totals).
Acceptance criteria
1. An allocation over the max hours for the faculty's cadre warns. Over max + 2 blocks without Dean override.
2. Every offering for the term has ≥1 faculty before the allocation can be submitted.
Tests: U - workload calculation. I - submission checks, instructor sync.

### P2-T07 Timetable generation
BRD: M07-03 | Depends on: T06, P1-T09 | Size: L
Deliverables: Timetable Slot Template (days, periods, timings, breaks), Room custom fields (from blueprint 9.8), Timetable (term, section; grid rows), Timetable Generation Run (CP-SAT solver via OR-Tools, background job).
Hard constraints: no faculty/room/section clash, lab periods consecutive and in labs with capacity, faculty unavailability. Soft: spread a course across days, max periods per faculty per day, electives of a group in parallel.
Publish → creates Course Schedule entries for the term (education attendance works unchanged). Prints: class / faculty / room timetables. Report: clash checker.
Acceptance criteria
1. On demo data (2 programs × 4 years × 2 sections) the solver returns a clash-free timetable within 5 minutes or reports the unsatisfiable constraints.
2. Manual edits are validated against the hard constraints.
3. Re-publishing replaces only future Course Schedules for that timetable. Marked attendance is never deleted.
Tests: U - constraint validator on hand-built grids. I - solver on small demo, publish/re-publish safety.

### P2-T08 Leave and substitution
BRD: M07-03 | Depends on: T07 | Size: S
Deliverables: Substitution (original Course Schedule, absent faculty, substitute, reason) auto-proposed when a Leave Application is approved. Suggests free faculty of the same department. Substitute notified. Print: substitution order.
Acceptance criteria
1. Approving a 2-day leave lists affected periods and proposes substitutes without clashes.
2. The substitute can mark attendance for the substituted period.
Tests: I - proposal generation, attendance permission.

### P2-T09 Faculty achievements, FDPs and self-appraisal
BRD: M07-04, M07-05 | Depends on: T05 | Size: M
Deliverables: Faculty Achievement (type: FDP attended, conference, resource person, award, membership, certification; evidence; financial support amount), link to HRMS Training Event where applicable.
API Score Rule (versioned activity → points, caps). Self-Appraisal computes API from Faculty Achievement, publications (Phase 3), feedback (Phase 3) and workload, then creates/updates an HRMS Appraisal with KRA scores. HOD review via approval engine.
Reports: FDP participation (6.3.4), Conference financial support (6.3.2), Faculty profile print (CV).
Acceptance criteria
1. Self-appraisal totals match the rule caps (e.g. FDP points capped per year).
2. The HRMS Appraisal shows the computed KRA scores and can't be edited by the faculty after HOD submission.
Tests: U - API scoring. I - appraisal creation, report counts.

### P2-T10 Payroll setup for aided and self-financing staff
BRD: M07-07 | Depends on: T05 | Size: S
Deliverables: Configuration guide + fixtures: salary components (Basic, DA, HRA, AGP), salary structures per `oc_funding_mode`, increment rule via Employee Promotion, PF/ESI/PT via india_compliance/HRMS. A Salary Structure Assignment helper by funding mode.
Acceptance criteria
1. Payroll Entry for demo staff produces correct slips for one aided and one self-financing employee per fixture.
Tests: I - salary slip amounts vs fixture.

### P2-T11 Faculty portal pages
BRD: M07, M06-08 | Depends on: T07, T13 (CIA) | Size: M
Deliverables: In `/campus-portal`: My timetable, Mark attendance (for own or substituted periods), CIA mark entry (T13), Course plan, Leave apply, My students (mentees).
Acceptance criteria
1. Faculty can act only on their own offerings or substituted periods (server-side checks).
2. Attendance entry for a 60-student class works on a phone in under 1 minute (bulk present with exceptions).
Tests: I - API permission tests. M - mobile UAT.

## C. Examinations / COE (M06)

### P2-T12 Exam rule engine and seeds
BRD: M06-05, M05-03 | Depends on: P1-T05 | Size: L
Deliverables
- Exam Rule Set (per regulation and course type): CIA/ESE max and weights, ESE minimum %, total minimum %, internal-only pass %, attempt rules (from attempt N: ESE ≥ X% alone), CIA carry-forward, absent handling, max attempts, revaluation eligibility by course type, withdrawal rules.
- Grading Scheme (per regulation): grade rows (letter, grade point Float, min, max, is_pass), result codes (U, SA, WD/WC, AB), method per course type (absolute / relative_boxcox with min cohort / online table), online-course table.
- Classification Rule (per regulation): class name, CGPA min, first-appearance required, max years, break of study included, Honours/Minor variants.
- Pure-Python engine `examinations/rules.py`: `pass_status()`, `grade()`, `relative_grade_bands()` (Box-Cox via scipy), `sgpa()`, `cgpa()`, `classify()`.
- Seeds: AU-R2021, R2022, R2026 from the research note.
Acceptance criteria
1. Fixture table (≥40 cases) of marks/attempts/course types gives the expected pass/fail and grades for each regulation (R2026 B = 6.5, C+ = 6; R2022 O vs R2026 S).
2. R2022 third-attempt rule: ESE 50%, total 48% → pass. ESE 47%, total 55% → pass on first attempt (ESE ≥45%).
3. Relative grading is applied only when passed students > 30 for that course, labs and projects always absolute. Bands are reproducible (deterministic) for the same input.
4. SGPA/CGPA exclude U, additional courses and mandatory courses per regulation, to 2 decimals. % = CGPA × 10.
5. Rule records are immutable once Effective.
Tests: U - full fixture table per regulation, Box-Cox determinism, CGPA exclusions, classification cases (distinction with a withdrawal, break of study).

### P2-T13 CIA templates, mark entry, lock and consolidation
BRD: M06-08, M03-03 (data) | Depends on: T12, P1-T19 | Size: L
Deliverables: CIA Component Template (per regulation and course type; components with max, weight, conversion; for theory-with-lab per L-T-P pattern), CIA Schedule (term, offering, component dates, entry deadline), CIA Mark Entry (offering, component, question-wise marks with CO tag and Bloom level, absent flags), lock at deadline, Unlock Request (approval), CIA Consolidation (per student per offering → converted CIA marks incl. R2026 attendance marks from `attendance_marks()`).
Permissions: faculty edit only own offerings until lock. HOD read. COE read all. Every change versioned.
Reports: CIA status by offering, CIA marks audit trail.
Acceptance criteria
1. R2022 theory: two assessments of 100 (40 assignment + 60 test) → 40, rounded to nearest integer, matching the fixture.
2. R2022 lab: 75 observation/record + 25 test → 60. R2026 theory includes attendance marks per band.
3. After the deadline, edits require an approved unlock. The unlock and edits appear in the audit report.
4. CO-tagged question marks are stored for Phase 3 attainment.
Tests: U - consolidation formulas per template. I - lock/unlock, permission tests, audit trail.

### P2-T14 Exam session, registration, eligibility, exam fee
BRD: M06-01 | Depends on: T12, P1-T19, P1-T24 | Size: L
Deliverables: Exam Session (company, term, exam types, dates, status, notification print), Exam Schedule (course, date, slot), Exam Registration (bulk-created: current-semester courses + arrears (U/WD) + dropped re-registered; eligibility per course: SA from attendance run, dues scope Exam, detention, malpractice debarment), exam fee invoice (Exam Fee Rate, late fee slabs), student confirmation in the portal.
Acceptance criteria
1. Bulk registration for 480 students completes via the bulk runner. Re-running adds only missing courses.
2. An SA student's current courses are marked "Not eligible (SA)". Arrears remain registrable (R2022 cl. 15.1).
3. A student with exam dues is blocked from hall ticket generation, not from registration.
4. Late registration applies the correct late fee slab.
Tests: U - eligibility matrix. I - bulk idempotency, fee invoices, dues gating.

### P2-T15 Hall tickets
BRD: M06-02 | Depends on: T14 | Size: S
Deliverables: Hall Ticket generation (bulk) with photo, courses, dates, QR (verifiable). Withheld list with reasons. Portal download after release date.
Acceptance criteria
1. Withheld students get no hall ticket and see the reason in the portal.
2. A hall ticket QR verifies and shows the exam session and registration status.
Tests: I - bulk generation, withheld logic, verification.

### P2-T16 Halls, seating, invigilation, exam attendance, malpractice
BRD: M06-02 | Depends on: T14 | Size: M
Deliverables: Exam Hall (Room + rows × columns), Seating Plan generator per date/slot (interleave programs/courses, skip blocked seats), Invigilation Duty roster (fair distribution, no invigilating own course), attendance sheets (print with barcodes), Exam Attendance capture (scan/mark absent), Malpractice Report (category, evidence, committee decision → debarment rule).
Prints: Seating chart, Hall attendance sheet, Invigilation order, Script barcode labels.
Acceptance criteria
1. No two adjacent seats (row/column) have the same course when the mix allows it. Capacity is never exceeded.
2. Invigilation duties are balanced within ±1 per faculty per session type.
3. An absent mark flows to the result run as AB.
Tests: U - seating algorithm properties. I - roster balance, attendance → result.

### P2-T17 Question paper workflow (confidential)
BRD: M06-03 | Depends on: P1-T07 | Size: L
Deliverables: QP Setter Nomination (course, setters, scrutiniser, deadline; confidential), Question Bank Item (course, CO, Bloom, marks, difficulty; restricted), Question Paper (pattern/blueprint, sets A/B, moderation status, encrypted attachment, release-at), QP Access Log (view/download/print with user, time, IP).
Role "Exam Confidential" only. Downloads are possible only within the release window (e.g. 30 min before the slot). Watermark with user and time.
Acceptance criteria
1. Nobody, including System Manager via the UI, can open a QP before release-at. Attempts are logged.
2. A blueprint check validates CO coverage and Bloom-level distribution against the pattern.
3. The print log shows the count of copies printed per hall.
Tests: I - time-window access, role restriction, logging, blueprint validation.

### P2-T18 Dummy numbers, scripts, valuation
BRD: M06-04 | Depends on: T16 | Size: L
Deliverables: Dummy Number Map (restricted), Answer Script Bundle (packet, course, count, movement log), Valuation Allocation (examiner internal/external, bundle, deadline), Valuation Entry (dummy no, question-wise marks, valuation round 1/2/3), auto third valuation when |V1 − V2| > threshold (rule set), final ESE mark per rule (average of the two closest or as configured).
External examiner portal page: only allocated bundles by dummy number.
Acceptance criteria
1. Examiners never see register numbers or names. Only Exam Confidential can join dummy → register.
2. A difference above the threshold creates a third-valuation allocation automatically.
3. A bundle can't be marked complete with missing scripts.
Tests: I - permission isolation, third valuation trigger, final mark rule.

### P2-T19 Result processing, passing board, publication
BRD: M06-05, M06-06 (publication) | Depends on: T12, T13, T18 | Size: L
Deliverables: Mark Moderation (proposed adjustments by course with justification), Result Run (session + program; bulk; combines CIA (carried forward for arrears) and ESE, applies grace if the rule allows, pass rules, grading method incl. relative bands per course, SGPA/CGPA, arrear counts; versioned), Student Result (per student per session; course rows; SGPA, CGPA, result), Passing Board approval (Meeting of Body Type Passing Board resolution, or approval engine), Result Publication (release-at; portal and SMS/WhatsApp at release; permission query hides results before release).
Acceptance criteria
1. A full demo session (2 programs, 480 students, mixed R2022/R2026 batches) processes in under 10 minutes and matches the hand-checked fixture for 20 sampled students.
2. Re-running before publication replaces the draft version. After publication, it creates a new version with a change log, and old versions stay readable to COE.
3. Students can't fetch results (API or portal) before release-at.
4. Grace marks applied are listed in the Grace audit report with the rule reference.
Tests: U - combination and carry-forward. I - end-to-end run, versioning, release permission, performance timing.

### P2-T20 Photocopy, revaluation, review
BRD: M06-06 | Depends on: T19 | Size: M
Deliverables: Revaluation Application (type Photocopy / Revaluation / Review; courses; fee; window from publication), faculty justification step for photocopy → revaluation (R2022 16.4), Revaluation Outcome (new marks → new Student Result version, grade change, notification). Only theory and theory-with-lab are eligible (rule set).
Reports: Revaluation change stats, Evaluation grievances vs appeared (AQAR 2.5.2).
Acceptance criteria
1. A lab-course revaluation request is rejected per the rule.
2. Review is allowed only for students who applied for revaluation for that course.
3. An upward change regenerates the grade sheet and updates CGPA, with the version history visible.
Tests: I - window, eligibility, result versioning, report.

### P2-T21 Withdrawal, break of study, rejoin
BRD: M06-01, M05-03 | Depends on: T14, P1-T05 | Size: M
Deliverables: Exam Withdrawal Application (once per programme, within 10 days, HOD recommend → Principal approve; code WD/WC per regulation; not counted as an attempt for distinction), Break of Study (max 1 year (+1 exceptional), approvals), Rejoin (regulation change via P1-T05 history, bridge courses list).
Acceptance criteria
1. A second withdrawal in the programme is rejected. A withdrawal 11 days after the exam is rejected unless the special-case override is used.
2. A rejoining student moves to the regulation in force with bridge courses added to the next registration.
Tests: U - withdrawal rules. I - rejoin regulation change and registration impact.

### P2-T22 Grade sheets, certificates, transcripts, convocation
BRD: M06-07, M05-03 | Depends on: T19, P1-T08 | Size: M
Deliverables: Prints (QR via T08): Semester grade sheet, Consolidated grade sheet (CGPA, % = CGPA × 10, classification), Provisional certificate (issuer per `provisional_certificate_issuer`), Degree certificate (only if `degree_awarding_body` = College; otherwise a degree data sheet for the university), Transcript.
Classification computation per Classification Rule. Progression Run (term end: promote / detain / probation per Progression Rule). Convocation List (eligible graduates, export in the university's format) + Transcript Request.
Acceptance criteria
1. A distinction case, a first-class case (with arrears cleared) and a second-class case classify correctly for R2022 and R2026 fixtures.
2. With `degree_awarding_body` = University, the degree certificate print is not available and the convocation export is.
3. The consolidated grade sheet lists additional/Honours courses per regulation rules (excluded from CGPA unless Honours completed).
Tests: U - classification. I - prints render with QR, setting switch, convocation export columns.

### P2-T23 Examiner remuneration
BRD: M06-04 | Depends on: T17, T18 | Size: S
Deliverables: Remuneration Rate (activity → rate), Examiner Remuneration Claim (auto-computed from allocations, QP setting, invigilation) → Additional Salary (internal employees) or Purchase Invoice with TDS (externals). Remuneration register report.
Acceptance criteria
1. Claim amounts equal rates × counts from the source records. Internal staff payouts appear on the next payroll.
Tests: I - claim computation, posting by examiner type.

### P2-T24 COE reports and data points
BRD: M17-06; AQAR 2.5.1, 2.5.2, 2.6.3 | Depends on: T19, T20 | Size: S
Deliverables: Reports: Registration summary, Eligibility (withheld), Absentee, Valuation progress, Valuation difference, Result analysis (pass % by course/faculty/program), Rank list, Arrear list, Days exam-end to result, Malpractice register.
Data points: `days_exam_to_result`, `evaluation_grievances`, `students_appeared`, `final_year_passed`, `pass_percentage`.
Acceptance criteria
1. Data points match the reports and the demo fixture.
Tests: I - each data point.

### P2-T25 Student exam portal pages
BRD: M06, M16-04 | Depends on: T14, T15, T19, T20 | Size: M
Deliverables: In `/campus-portal`: Exam registration confirmation and fee payment, Hall ticket download, Results (after release), Grade sheets download, Revaluation application and status, Withdrawal application.
Acceptance criteria
1. All pages enforce release dates and ownership server-side.
2. A revaluation application with payment works end-to-end against the gateway sandbox.
Tests: I - API permission and timing tests. M - mobile UAT.

### P2-T26 Prerequisites and progression hooks
BRD: M03-04, M05-03 | Depends on: T19, P1-T13 | Size: S
Deliverables: Replace the P1-T13 prerequisite stub with a real check (`examinations.api.has_passed(student, course)`). Honours/Minor eligibility check (CGPA ≥7.5 up to semester III, no arrears for Honours, per regulation) in course registration.
Acceptance criteria
1. Registering for a course whose prerequisite isn't passed is rejected.
2. Honours registration is rejected for a student with an arrear, under R2022.
Tests: I - both checks with fixtures.

---

## Phase 2 exit checklist
- [ ] Exit demo run end to end on demo data. Results fixture matches.
- [ ] Confidentiality review: QP, dummy map and pre-release results tested with every non-exam role (including System Manager UI paths).
- [ ] Performance: result run for 2,000 students < 15 min, hall tickets for 2,000 < 5 min.
- [ ] Usage notes for governance, faculty, COE. Blueprint status updated.
