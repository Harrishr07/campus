# Thin vertical slice: pilot demo

Goal: one end-to-end path that can be shown to a pilot college (SXCCE-like autonomous engineering college):

> admit → fees → course registration → attendance eligibility → internal + end-semester marks → result → student portal → one live AQAR metric with drill-down

Already built (Phase 1): admit, fees and fines, course registration, regulations, approvals, messaging, circulars, QR verification, demo data.
This slice adds the minimum of attendance (T19 core), examinations (Phase 2 core), portal (T26 core) and IQAC (Phase 3 core). Paused Phase 1 work is on branch `wip/p1-t18-onboarding`; the remaining Phase 1 tasks resume after pilot feedback.

Rules for the slice (lighter than Phase 1):
- Build only what the demo path needs. No condonation workflow, relative grading, dummy numbers, question papers, valuation or revaluation.
- Rule values still come from records (regulation-linked), seeded for R2022 and R2026 from `docs/research/anna-university-autonomous-rules.md`.
- Tests: rule maths gets unit tests; each task gets one integration test of its happy path plus permission checks where student data is exposed.
- Review: one Sonnet review per task. Fix only Critical/Important findings, at most two fix rounds; everything else is deferred.

---

### S1 Attendance eligibility (core of P1-T19)
Deliverables
- Attendance Rule (regulation link): formula `sum_based` | `course_average`, overall_min_pct, medical_band_min_pct, per_course_min_pct (0 = none). Seed R2022 (sum_based, 75, 65, 0) and R2026 (course_average, 80, 70, 75).
- `campus.student_services.api.attendance_summary(student, academic_term)` → per offering: conducted, attended, pct; overall pct; status Eligible / Medical band / Shortage (SA). Source: education Student Attendance for the student's course-based Student Groups (offerings) in the term.
- Script report "Attendance Shortage" (company, term, program filters; company-scoped).
Acceptance
1. The same raw attendance gives the hand-computed outcome under R2022 vs R2026 (fixture of ≥6 scenarios).
2. Report lists only shortage/medical-band students of permitted companies.

### S2 Marks and results (core of Phase 2 COE)
Deliverables
- Grading Scheme (regulation): grade rows (letter, grade_point Float, min_mark, max_mark, is_pass) + result codes (U, SA, AB). Seed R2022 (O 10 … C 5, U) and R2026 (S 10, A+ 9, A 8, B+ 7, B 6.5, C+ 6, C 5, U) from the research note.
- Exam Rule Set (regulation): per course type (Theory / Lab / Theory with Lab / Project) cia_max, ese_max, ese_min_pct (45), total_min_pct (50). Seed R2022 and R2026.
- Exam Session (company, academic term, status Draft / Marks Entry / Published, publish_at).
- Mark Sheet Entry (exam session + course offering; rows: student, cia, ese, absent) — faculty of the offering edit while status is Marks Entry.
- Result Run (exam session + program, button / whitelisted POST): for each student and course → SA if S1 status is Shortage, else AB if absent, else pass/fail by rule → grade + grade point from the student's regulation scheme → Student Result (per student per session: course rows with marks, grade, GP, result; SGPA = Σ(credits×GP)/Σ credits over passed courses; CGPA across Student Results).
- Publication: Student Result visible to the student/guardian only when the session is Published and now ≥ publish_at (permission query + has_permission).
- Print format "Grade Sheet" with oc_qr_block.
Acceptance
1. Fixture: an R2022 student and an R2026 student with the same marks get the regulation-correct grades (e.g. 63 → B+ 7 under R2022, B 6.5 under R2026); ESE 44% with total 60% fails; SA/AB codes applied.
2. SGPA/CGPA match hand calculation to 2 decimals.
3. A student can't read results before publication or another student's results.

### S3 Student portal (core of P1-T26)
Deliverables
- Server-rendered pages under `/campus-portal` (Frappe www, Jinja + minimal JS; the Vue SPA comes later): Dashboard, Fees (Sales Invoices with `student`, outstanding by company), Attendance (S1 summary), Results (published Student Results + grade sheet download), Circulars (T11 get_my_circulars + acknowledge).
- Guardian view: switch between linked students. Student/Guardian home redirects to `/campus-portal`.
- All data via whitelisted methods with server-side ownership checks (student → own; guardian → linked students only).
Acceptance
1. Student A can't fetch student B's fees/attendance/results via any method (tests per method).
2. Pages render at 360 px width (manual check noted in the report).

### S4 IQAC live metric (core of Phase 3)
Deliverables
- Accreditation Framework + Framework Node (tree: code, title, node type, formula over data point keys) — seed "NAAC-AQAR-RAF2017" with criteria 2, key indicator 2.6, metrics 2.1.1 and 2.6.3 (placeholder titles).
- Data point registry: `@campus_metric("key")` decorator; implement `students_admitted` (submitted Program Enrollments in the academic year) and `final_year_passed` / `final_year_appeared` (from S2 Student Results), each returning {value, records}.
- Accreditation Cycle (framework, company, academic year) + Metric Value (node, value, snapshot JSON with record links), "Compute" button (safe_eval of the node formula).
- Desk page/report "Metric Drill-down": metric value + the list of source records (links).
Acceptance
1. 2.6.3 pass % on demo data equals the hand count, and the drill-down lists exactly those Student Results.
2. A formula can't reach anything outside the data-point namespace (safe_eval test).

### S5 Demo builder and walkthrough
Deliverables
- `campus.tests.demo.make_demo(scale="slice")`: on top of "small", run the whole path — 5 applicants admitted (one management quota), fees invoiced and 4 paid, course registration approved, 8 weeks of attendance with one shortage and one medical-band student, CIA + ESE marks, Result Run, publish, AQAR cycle computed. Idempotent.
- One end-to-end integration test running the slice path.
- `docs/DEMO.md`: logins (student, guardian, faculty, COE, IQAC), click-path script for a 15-minute pilot demo, what's real vs stubbed.
Acceptance
1. Fresh campus-test: `make_demo("slice")` then the walkthrough works without manual data entry.
