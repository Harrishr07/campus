# SXCCE demo data (PR-03)

A synthetic St. Xavier's Catholic College of Engineering (SXCCE) for the presentation and the intern UAT. Everything is
generated: names from a seeded generator, phone numbers that start with 0 (never dialable), e-mail addresses at
`sxcce.example.edu`, no Aadhaar numbers.

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
- The first load takes several minutes (about 10 on a busy shared bench: the 2025 batch's two terms and results are most
  of it). The output lists what was created and the seconds per step.
- A few ERPNext defaults a fresh site lacks are set (the Standard Selling price list, needed to invoice fees).

## What is loaded

| Area | Content |
|---|---|
| 2026 intake | 18 enquiries (12 converted to applicants), 60 applicants over the 6 programmes: 12 via enquiry conversion, 24 via one Applicant Upload file, 24 entered by hand. Per programme: 7 admitted and joined (Confirm Joining), 1 admitted and not yet joined (no-show so far), 1 Approved, 1 still Applied. Eligibility Rules and the Transfer Certificate document rule are set. |
| Fees | The 42 joiners have admission invoices from the Fee Structures: 60% paid in full, 10% half paid (Payment Entries), the rest outstanding. |
| 2025 batch | 120 active students (20 per programme) loaded like existing students (register numbers, guardians, class groups), enrolled in 2025-26 and promoted to 2026-27. First year complete: Course Registration, Mark Sheet Entries (CIA + end-semester), Result Run and published results for the Odd and Even terms (SGPA, CGPA, arrears). One Effective 8-semester R2022 curriculum per programme (165 credits; only CSE semester 3 and the common first year have real course names). |
| Current term (2026-27 Odd) | Semester 3 registrations and CIA marks for all programmes; for the CSE class a timetable (Course Schedules), three weeks of attendance, a medical leave and an on-duty leave. |
| Faculty | 18 Instructors, 3 per department; Head of Department in every department; the class advisor of the CSE 2025 class; two mentors with students allocated. |
| Services | A mentoring note (not confidential), a parent interaction, an institutional scholarship waiting for sanction, a placement drive with registrations, an Official Document and Degree Awarding Authority per programme, the AQAR cycle for 2025-26 computed. |

Not loaded: feedback responses (anonymous responses need a login per student), disbursed scholarships, Passing Board
meetings (results are published as the thin-slice demo does), Progression Run.

## Logins

Password for every login: `Campus@Pilot2026` (the profile's test password; public, demo sites only).

| Role | Login |
|---|---|
| Office staff | `office@sxcce.example.edu` |
| Admission Officer | `admissions@sxcce.example.edu` |
| Faculty | `faculty@sxcce.example.edu` |
| HOD CSE (other departments: `hod-ece`, `hod-eee`, `hod-mech`, `hod-civil`, `hod-it`) | `hod@sxcce.example.edu` |
| Class Advisor / Mentor | `class_advisor@sxcce.example.edu` |
| Controller of Examinations | `coe@sxcce.example.edu` |
| Accounts | `accounts@sxcce.example.edu` |
| Principal | `principal@sxcce.example.edu` |
| IQAC Coordinator | `iqac@sxcce.example.edu` |
| Student (CSE 2025 batch) | `student@sxcce.example.edu` |
| Guardian | `guardian@sxcce.example.edu` |
| Other faculty | `faculty-<programme>-1@sxcce.example.edu`, `-2` (e.g. `faculty-ece-1`) |

## Presentation walkthrough (10 steps)

1. **Enquiry to applicant** (Admission Officer): Lead list, convert an enquiry; Applicant Upload shows the validated file and row outcomes.
2. **Admit and Confirm Joining** (Admission Officer): open an Approved applicant, Admit; open an Admitted one, Confirm Joining; see the register number and fee invoice.
3. **Fees** (Accounts): Sales Invoice list, paid / part paid / outstanding; the Scholarship Application waiting for sanction.
4. **Class and timetable** (Class Advisor, Faculty): Student list of the CSE 2025 class, Course Schedule of the term.
5. **Attendance** (Faculty / HOD): attendance of the CSE sem 3 courses; the medical leave and on-duty student.
6. **CIA marks** (Faculty): Mark Sheet Entry of a sem 3 course.
7. **Results** (COE): the published Odd and Even results, arrears, CGPA; a Grade Sheet.
8. **Student and guardian view** (Student, Guardian): the portal at `/campus-portal`.
9. **Mentoring and placement** (Mentor, Placement): the mentoring note and parent interaction; the drive and its registrations.
10. **Accreditation** (IQAC, Principal): the AQAR cycle data points and the AISHE export for 2025-26.
