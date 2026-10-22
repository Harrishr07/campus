# SXCCE demo data (PR-03)

A synthetic St. Xavier's Catholic College of Engineering (SXCCE) for the presentation and the intern UAT. Everything is
generated: names from a seeded generator, phone numbers that start with 0 (never dialable), e-mail addresses at
`sxcce.example.edu`, no Aadhaar numbers. The names are synthetic, not reserved: `example.edu` is not an IANA-reserved domain and
`0000...` is not a reserved number range, they are simply undeliverable and undialable in practice.

## Load it

```
bench --site <site> migrate
bench --site <site> execute campus.setup.pilot.setup_college --kwargs '{"profile": "sxcce"}'
bench --site <site> execute campus.setup.demo_data.load --kwargs '{"profile": "sxcce", "seed": 2026}'
```

- The site must be in developer mode or carry `campus_demo_site` in its site config; anything else is refused (the logins
  carry the published test password).
- The same seed gives the same people and marks. Loading again creates nothing. `steps` (a list from `staff`, `intake`,
  `fees`, `curriculum`, `batch`, `term`, `services`) loads part of it.
- The first load takes about 10 minutes on a fresh site (the 2025 batch's two terms and results are about 8 of them). The
  output lists what was created and the seconds per step. Loading again takes a few seconds.
- The kit prepares what a site made without the setup wizard lacks: ERPNext's own fixtures (warehouse types, UOMs, groups), the
  Standard Selling price list and a Holiday List (Sundays off) as the default of the trust and the college. The loader checks
  the kit's work first and names anything missing in one message before it writes a record.
- Dates follow the load date: the three weeks of attendance end the day before the load, the notes are from the last weeks and
  the placement drive lies ahead. Load shortly before a presentation; a second load keeps the first load's dates.

## What is loaded

| Area | Content |
|---|---|
| 2026 intake | 18 enquiries (12 converted to applicants), 60 applicants over the 6 programmes: 12 via enquiry conversion, 24 via one Applicant Upload file, 24 entered by hand. Per programme: 7 admitted and joined (Confirm Joining), 1 admitted and not yet joined (no-show so far), 1 Approved, 1 still Applied. Eligibility Rules and the Transfer Certificate document rule are set. |
| Fees | The 42 joiners have admission invoices from the Fee Structures: 60% paid in full, 10% half paid (Payment Entries), the rest outstanding. |
| 2025 batch | 120 active students (20 per programme) loaded like existing students (register numbers, guardians, class groups), enrolled in 2025-26 and promoted to 2026-27. First year complete: Course Registration, Mark Sheet Entries (CIA + end-semester), Result Run and published results for the Odd and Even terms (SGPA, CGPA, arrears). One Effective 8-semester R2022 curriculum per programme (165 credits; only CSE semester 3 and the common first year have real course names). |
| Current term (2026-27 Odd) | Semester 3 registrations and CIA marks for all programmes; for the CSE class a timetable (Course Schedules), three weeks of attendance, a medical leave and an on-duty leave. Attendance and leave go through the real documents (validation, holiday list, certificate file, Education's own leave hook). |
| Faculty | 18 Instructors, 3 per department; Head of Department in every department; the class advisor of the CSE 2025 class; two mentors with students allocated. |
| Services | A mentoring note (not confidential), a parent interaction, an institutional scholarship waiting for sanction, a placement drive with registrations, an Official Document and Degree Awarding Authority per programme, the AQAR cycle for 2025-26 computed. |

Not loaded: feedback responses (anonymous responses need a login per student), disbursed scholarships, Progression Run.

The one shortcut: the 2025-26 results are published without a Passing Board meeting (the Result Run is computed by the real
service, then the Exam Session is published with the board approval flag set and dated like a past term, no notice sent).
There is no Passing Board record to show for those two terms. The shortcut lives in `campus/setup/demo_data/shortcuts.py`.

## Logins

Password for every login: `Campus@Pilot2026` (the profile's test password; public, demo sites only).

| Role | Login |
|---|---|
| Office staff | `office@sxcce.example.edu` |
| Admission Officer | `admissions@sxcce.example.edu` |
| Faculty | `faculty@sxcce.example.edu` |
| HOD CSE (other departments: `hod-ece`, `hod-eee`, `hod-mech`, `hod-civil`, `hod-it`) | `hod@sxcce.example.edu` |
| Class Advisor / Mentor (also mentors the CSE 2025 class) | `class_advisor@sxcce.example.edu` |
| Controller of Examinations | `coe@sxcce.example.edu` |
| Accounts | `accounts@sxcce.example.edu` |
| Placement Officer | `placement@sxcce.example.edu` |
| Principal | `principal@sxcce.example.edu` |
| IQAC Coordinator | `iqac@sxcce.example.edu` |
| Student (CSE 2025 batch) | `student@sxcce.example.edu` |
| Guardian | `guardian@sxcce.example.edu` |
| Other faculty | `faculty-<programme>-1@sxcce.example.edu`, `-2` (e.g. `faculty-ece-1`) |

## Presentation walkthrough (10 steps)

1. **Enquiry to applicant** (Admission Officer): Lead list, convert an enquiry; Applicant Upload shows the validated file and row outcomes.
2. **Admit and Confirm Joining** (Admission Officer): open an Approved applicant, Admit; open an Admitted one, Confirm Joining; see the register number and fee invoice.
3. **Fees** (Accounts): Sales Invoice list, paid / part paid / outstanding; the Scholarship Application waiting for the Principal's sanction (the Principal sanctions it from the approval inbox).
4. **Class and timetable** (Class Advisor, Faculty): Student list of the CSE 2025 class, Course Schedule of the term.
5. **Attendance** (Faculty / HOD): open any CSE sem 3 course in the Student Group list and its Student Attendance. The third CSE student (SXCCE25CSE0003) is on medical leave and the fifth (SXCCE25CSE0005) on duty for a contest; both leaves are Student Leave Applications with a certificate.
6. **CIA marks** (Faculty): Mark Sheet Entry of any sem 3 course (the first CSE course is a good one); end-semester marks are blank, the term is in progress.
7. **Results** (COE): the published Odd and Even results, arrears, CGPA; a Grade Sheet. There is no Passing Board record for these terms (see the shortcut above).
8. **Student and guardian view** (Student, Guardian): the portal at `/campus-portal`.
9. **Mentoring and placement** (Mentor, Placement): the mentoring note and parent interaction; the drive and its registrations.
10. **Accreditation** (IQAC, Principal): the AQAR cycle data points and the AISHE export for 2025-26.
