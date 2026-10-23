# OneBook Campus: 15-minute pilot demo

One command builds a whole college-semester of data, so the demo needs no manual data entry. It follows the
thin-slice path: admit, fees, course registration, attendance eligibility, internal and end-semester marks,
result, student portal, one live AQAR metric with drill-down.

## Prerequisites

- A bench with `frappe`, `erpnext`, `hrms`, `education` and `campus` installed on the site, and the site migrated
  (`bench --site <site> migrate`).
- `bench start` running (the desk, the portal and the QR verification page are served by it).
- **Demo site only**: `make_demo` refuses to run unless `developer_mode` is on, the site config has `"campus_demo_site": 1`, or `allow_on_production=True` is passed. A login that already has a password keeps it; only logins without one get the demo password. The builder sets one known password on demo logins and creates a company hierarchy.
  Never run it on a production site.

## Build the data

```bash
bench --site <site> execute campus.tests.demo.make_demo --kwargs "{'scale':'slice'}"
```

- Takes about 15 seconds. It is idempotent: a second run creates nothing and repairs a half-built set.
- `scale` "small" and "full" build only the college set-up (companies, programs, regulations, rules, 30 or 900
  placeholder students); "slice" is "small" plus everything below.
- On a fresh site the first run also needs the Education/ERPNext defaults of a set-up site (a Company chart of
  accounts, fiscal years); on `education.localhost` this is already the case.

### What the builder creates

| Step | Data |
| --- | --- |
| College | Demo Educational Trust with Demo College of Engineering (autonomous) and Demo Arts & Science College; B.E. CSE, B.E. ECE, M.E. CSE; regulations AU-R2021, R2022, R2026 |
| Admissions | Seat Matrix for B.E. CSE 2026-27 (Government and Management quota), Eligibility Rule, Admission Document Rule, five admitted applicants (one under Management quota), one more applicant left **Approved** for you to admit live |
| Fees | Fee structures (Rs 65,000; Management quota Rs 1,55,000); one Sales Invoice per admitted student; four paid by Payment Entry, the Management-quota student's invoice left due |
| Curriculum | R2026 Curriculum Rule and Registration Rule, an **Effective** B.E. CSE R2026 curriculum of four semester-1 courses (14 credits), Registration Window, course offerings (section A) taught by hod_cse, faculty_1, faculty_2, faculty_3 |
| Registration | A submitted Course Registration of all four courses for each admitted student |
| Attendance | 8 weeks of Course Schedules (Mon/Wed/Fri, 24 sessions per course) and a Student Attendance row per student, session and course |
| Marks and result | Exam Session (Published, publish_at yesterday), CIA and ESE marks for every student and course, Student Results (SGPA, CGPA), one issued Grade Sheet with QR |
| IQAC | Accreditation Framework NAAC-AQAR-RAF2017, an Accreditation Cycle for 2026-27 for the college, Metric Values for 2.1.1 and 2.6.3 |

### The five students

| Login or name | Student | Fee | Attendance (R2026) | Result |
| --- | --- | --- | --- | --- |
| student_1 / Aarav Kumar | slice-1, OC, Government quota | paid | 95.8%, Eligible | all pass, SGPA 9.00 |
| Meena Lakshmi | slice-2, BC | paid | 91.7%, Eligible | fails Matrices and Calculus (ESE 40%, grade U), SGPA 7.60 |
| Karthik Raja | slice-3, MBC | paid | 58.3%, **Shortage** | SA in every course, SGPA 0.00 |
| Divya Bharathi | slice-4, SC | paid | 70.8% raw, 83.3% with approved medical leave: **Medical band** | all pass, SGPA 6.86 |
| Sanjay Prakash | slice-5, OC, **Management quota** | **Rs 1,55,000 due** | 87.5%, Eligible | absent (AB) in Matrices and Calculus, SGPA 8.00 |
| Nithya Shree | slice-6, BC | not admitted yet | none | none |

R2026 attendance rule: course-average overall 80%, medical band 70%, 75% in every course. The marks are the
same under any regulation; the R2026 grade scale applies (S 10, A+ 9, A 8, B+ 7, B 6.5, C+ 6, C 5, U).

### The final-year flag (read this before showing the AQAR metric)

The demo data has no real final-year batch. The builder flags the one Exam Session as `is_final_year`, so the
2.6.3 metric (final-year pass percentage) has results to count. Of the four students who sat an exam
(Karthik was SA throughout), two passed every course: **2.6.3 = 2 / 4 = 50%**. Say this when you show it.

## Logins

All logins are `<name>@demo.campus.test` with the password **`Campus@Demo2026`**, plus `Administrator` / `admin`.
Desk: `http://<site>:<port>/desk`. Students and guardians land on the portal, `/campus-portal`.

| Login | Role | Use in the demo |
| --- | --- | --- |
| `admissions` | Admission Officer | admit the sixth applicant |
| `accounts` | Accounts User | fees, invoices, payments |
| `student_1` | Student | portal: own fees, attendance, results |
| `guardian_1` | Guardian | portal: the same student, as a parent |
| `hod_cse` | HOD, Instructor | course registrations, Attendance Shortage report, teaches Matrices and Calculus |
| `faculty_1`, `faculty_2`, `faculty_3` | Instructor | their own offerings and mark sheets |
| `coe` | COE | Exam Session, Student Results, Grade Sheet |
| `iqac` | IQAC Coordinator | Accreditation Cycle, Metric Drill-down |
| `principal` | Principal | everything of the college, read |
| `warden`, `exam_confidential` | other roles | not used in this path |

Every desk login is limited to Demo College of Engineering by a Company User Permission.

## Where to click (desk navigation)

The desk home (`/desk`) shows one **OneBook Campus** tile. Click it to open a pop-up of area tiles; each tile opens that
area's workspace page, and its sidebar lists the same masters, transactions, reports and settings under
**Masters / Transactions / Reports / Settings**. A login sees only the areas its roles allow.

| Login | Area tiles shown | Where the demo step lives |
| --- | --- | --- |
| `admissions` | Admissions, Academics, Student Services, Examinations, Communication, Approvals | Admissions > Applications > **Student Applicant**; Admissions > Seats & Allotment > **Seat Matrix** |
| `accounts` | Fees and Finance, Approvals | Fees and Finance > Billing > **Student Invoices**; Fees and Finance > Collections > **Payment Entry** |
| `hod_cse`, `faculty_*` | Academics, Student Services, Examinations, Communication, Approvals | Academics > Registration > **Course Registration**, **Student Group**; Student Services > Reports > **Attendance Shortage**; Examinations > Internal Assessment > **Mark Sheet Entry** |
| `coe` | Academics, Student Services, Examinations, Communication, Approvals | Examinations > Registration & Hall Tickets > **Exam Session**; Examinations > Results > **Student Result** |
| `iqac` | the same as `coe`, plus IQAC | IQAC > Accreditation > **Accreditation Cycle**; IQAC > Reports > **Metric Drill-down** |
| `principal` | every area except IQAC, plus Administration | read-only view of the college |
| Administrator | all nine areas | Administration > Documents & Jobs > **Verifiable Document**, **Bulk Run** |

(`hod_cse`, `coe`, `iqac` and `admissions` also hold Academics User, the general staff role, which is why they see
the Academics, Student Services, Examinations and Communication tiles.) Students and guardians have no desk; they
land on `/campus-portal`. Each workspace page opens with shortcuts for the most used actions, then link cards.

## 15-minute click-path

Replace `<site>` with your host and port, for example `http://education.localhost:8003`. Use separate browser
profiles or private windows to switch users quickly. Each URL is also a click in the sidebar (see the table above); the
shortcuts at the top of each workspace page are the quickest route.

| Min | Who | Do this | Show |
| --- | --- | --- | --- |
| 0-2 | `admissions` | `/desk/student-applicant`: open **slice-6 (Nithya Shree)**, note Approved and Eligible, with the checklist document Submitted. Click **Admit** (shown for Approved applicants to an Admission Officer) and confirm; on the Student it opens, click **Confirm Joining** and keep today's date | Admit creates only the admitted Student (no enrollment, number or invoice: M04-09). Confirm Joining creates the enrollment, register number (for example DCE26CSE0006) and fee invoice in one step, and the Seat Matrix (`/desk/seat-matrix`) counts the seat |
| 2-4 | `accounts` | `/desk/sales-invoice`: filter on the students; open the invoices | five paid or due fee invoices; Sanjay Prakash's Management-quota invoice of Rs 1,55,000 is the only one outstanding; `/desk/payment-entry` shows the four receipts |
| 4-6 | `hod_cse` | `/desk/course-registration`: open one registration; `/desk/student-group`: open an offering | Effective R2026 curriculum, 14 credits, registration rules from the regulation, the student placed in the four offerings |
| 6-8 | `hod_cse` | `/desk/query-report/Attendance Shortage`: Company = Demo College of Engineering, Academic Term = 2026-27 (Odd) | only Karthik Raja (Shortage, 58.33%) and Divya Bharathi (Medical band, 70.83%); the other three are eligible and not listed |
| 8-9 | `faculty_1` | `/desk/mark-sheet-entry`: open the Engineering Physics sheet | CIA and ESE per student. The grid may look editable, but the session is Published (not Marks Entry), so an edit is refused when you try to save; marks are entered only while the session is in Marks Entry |
| 9-11 | `coe` | `/desk/exam-session`: open the session; `/desk/student-result` | status Published, Final Year ticked; Student Results per student: SA, AB, U codes and SGPA/CGPA to 2 decimals. **Run Results** stays after publication: a re-run there makes a new result version with a change log, never an in-place edit (P2-T19); the run was done by the builder, which publishes without a Passing Board meeting |
| 11-12 | `coe` or Administrator | open Aarav Kumar's Student Result, **Print**, format **Grade Sheet**; then open the public page `<site>/verify/<code>` in a private window (the code is on `/desk/verifiable-document` as Administrator, or scan the QR). Another sheet: click **Issue Grade Sheet** on a Student Result as `coe`; it opens the verify page | the QR code and the "Valid" verification page |
| 12 | Administrator, then `coe` | once: an **Approval Policy** for Certificate Request with condition `doc.certificate_type in ("Consolidated Grade Sheet", "Provisional Certificate", "Degree Certificate", "Degree Data Sheet")` and one level, Position COE scoped by company; then a **Certificate Request** (Provisional Certificate) for a final-year student, **Request Approval**, and approve it as `coe` | the draft preview says DRAFT - NOT VALID; once approved it is issued with a number and a QR that verifies |
| 12 | `coe` | new **Convocation List** for the college, save, **Get Graduates**, then **Download** (CSV in the placeholder column format set on the list) | the final-year students without arrears, with CGPA, % and class |
| 12-14 | `student_1`, then `guardian_1` | log in: the home page is `/campus-portal`. Dashboard, Fees, Attendance, Results (Grade Sheet download). The guardian sees the same student | own data only; Aarav's fees show nothing outstanding, attendance Eligible, SGPA 9.00 |
| 14 | `student_1`, then `guardian_1` | portal **Certificates**: request a Bonafide for "Bank account"; **Grievances**: raise one (optionally attach a PDF/JPG/PNG, kept private); **Leave**: apply for Medical leave; **Dashboard**: onboarding status; **Fees**: an unpaid invoice shows **Pay online** only when its company has a payment gateway, else a plain message (none in the demo) | each form posts and the list shows the new row as Pending/Open/Requested; the Bonafide goes to the Principal (policy "Demo Certificate Approval", seeded by the builder); the guardian does the same for the ward only |
| 14-15 | `iqac` | `/desk/accreditation-cycle`: open the 2026-27 cycle, **Compute**; then `/desk/query-report/Metric Drill-down` with Metric Value = `<cycle>-2.6.3` | 2.6.3 = 50.00 and the exact Student Results behind it (final_year_passed: Aarav and Divya; final_year_appeared: four); 2.1.1 (students admitted) |

Notes for the presenter:

- If the live admission is done before a rehearsal, run the builder again: it does nothing to an admitted
  applicant, and slice-6 stays Admitted (joined or not). To reset completely use a fresh demo site.
- The 2.1.1 value counts every submitted Program Enrollment of the college in 2026-27: the 30 placeholder
  students of the "small" set, the five admitted applicants, and any applicant you admit live (35 before, 36 after).
- The admission, the shortage report and the portal do not depend on the worker process. **Compute** and the
  grade sheet issue run inline.

## Real versus stubbed

| Area | Real (built, rule-driven) | Stubbed or not in the slice |
| --- | --- | --- |
| Admissions | Admit transaction (Student, Program Enrollment, register number, fee invoice in one step), Seat Matrix quota and category checks, eligibility and document rules | no counselling import in the demo; legacy data import (templates and Import Check) is built but not used in the demo |
| Fees | Fee structures by quota and category, invoices, Payment Entry, outstanding by company | The four payments are created by the builder (UTR `DEMO-UTR-...`), not through bank challan import or a gateway. Online payment gateways are built, but the demo has no Payment Gateway Account; refunds, caution deposits, concessions, scholarships and no-dues clearance are built but have no demo data |
| Course registration | Effective curriculum, credits from L-T-P, regulation Registration Rule, window, offerings, seat membership | No approval policy exists in the demo, so registrations submit directly; prerequisites always pass |
| Attendance | S1 rules (formula, overall, medical band, per-course minimum) from the Attendance Rule of the regulation, shortage report | Attendance rows are generated by the builder (a real college marks them in the desk); Education's holiday check is skipped; the condonation workflow (Condonation Request) is built but has no demo request |
| Marks and results | Grading Scheme and Exam Rule Set per regulation, Mark Sheet Entry, Result Run (SA/AB/U codes, SGPA, CGPA), publication gating, Grade Sheet with QR verification | The builder runs the Result Run synchronously (the button queues it for a worker); one exam session; no relative grading, dummy numbers, valuation or revaluation; the session is flagged final year (see above) |
| Portal | `/campus-portal` Dashboard, Fees, Attendance, Results, Circulars, Certificates, Grievances, Leave, onboarding status, with server-side ownership checks for students and guardians | Server-rendered pages, not the later Vue app (deferred); the Pay online button needs a Payment Gateway Account for the invoice's company (none in the demo, so a message shows instead) |
| IQAC | Framework and nodes, data point registry, Accreditation Cycle compute (safe-eval sandbox), Metric Value snapshot and drill-down | Only metrics 2.1.1 and 2.6.3 with placeholder titles; no SSR document export |
| Data | Company hierarchy, regulations R2022 and R2026 values from the research note | R2026 Curriculum Rule has no minimum total credits (one semester is loaded); R2026 Registration Rule copies the R2022 values; all people and marks are invented |
| Messaging | Broadcast, circular and approval engines exist | No WhatsApp or SMS provider is connected in the demo |

## Manual checklist

Run after building the data and before a pilot demo.

- [ ] `bench --site <site> execute campus.tests.demo.make_demo --kwargs "{'scale':'slice'}"` finishes without an error; run it a second time and confirm it finishes in a few seconds.
- [ ] Log in as each user in the table above with `Campus@Demo2026`; students and guardians land on `/campus-portal`, staff on the desk.
- [ ] As `admissions`, admit slice-6 with the **Admit** button; confirm the new Student, register number and invoice.
- [ ] As `hod_cse`, the Attendance Shortage report lists exactly Karthik Raja and Divya Bharathi.
- [ ] As `coe`, the Exam Session is Published and every Student Result opens; Aarav's Grade Sheet prints with a QR code.
- [ ] The public `<site>/verify/<code>` page shows Valid for that code when logged out.
- [ ] As `student_1`, Fees, Attendance and Results show only Aarav Kumar; a student id of another student in the URL (`?student=...`) is refused.
- [ ] As `guardian_1`, the same single student appears.
- [ ] As `iqac`, **Compute** on the 2026-27 cycle gives 2.6.3 = 50 and the drill-down lists four appeared and two passed Student Results.
- [ ] **Portal at 360 px:** open `/campus-portal` as `student_1` in Chrome, open DevTools, switch on the device toolbar and set the width to 360. Check the Dashboard, Fees, Attendance and Results pages: no horizontal page scroll, tables readable (they may scroll inside their own box), buttons tappable, the student switcher usable as `guardian_1`.
- [ ] No background worker errors: `bench start` output shows no failed jobs.

## Troubleshooting

- *"You do not have permission to access ..." in a report filter*: log in with the demo user of the role listed above;
  desk reports check read access on every link filter (the staff demo users hold Academics User for this reason).
- *A fiscal year or chart-of-accounts error on a bare site*: finish the ERPNext setup wizard first (or use a site
  that has been through it). The builder only adds fiscal years that do not overlap existing ones.
- *Admit refuses with "Seat not available"*: the Seat Matrix row of the quota and category is full; the demo
  matrix has 10 seats in every quota and category row.
