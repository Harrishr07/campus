# Faculty profile, norms and sanctioned posts (M07-01, M07-06 fields)

The faculty profile is the HRMS **Employee** record. The "Faculty" tab adds: staff type (Teaching / Non-teaching /
Project), cadre, funding mode (Aided / Self-financing), pay scale, AICTE faculty ID, highest qualification, PhD
status and award date, NET / SET / SLET, teaching experience before joining, specialisation, research guide,
ORCID, Scopus and Vidwan / IRINS IDs. An awarded PhD sets the highest qualification to Doctorate.

## Faculty Norm (Faculty > Masters)
One record per college and Effective From date. The version in force on a date is the latest one on or before it,
so a new AICTE/UGC norm is a new record, not an edit. It holds the students-per-faculty figure and, per cadre, the
cadre ratio share (1, 2, 6 for 1:2:6), minimum qualification, PhD required, NET/SET/SLET or PhD required, and
minimum teaching experience.

## Qualification check
- **Employee:** when a teacher is created, or their cadre, qualification, PhD, NET/SET, experience, joining date or
  company changes, the norm in force on the joining date is checked. A shortfall blocks the save unless the
  **Principal** of the college (Position Holder of PRINCIPAL) enters an override reason; the shortfall text and
  the Principal are recorded on the Employee. Other edits keep the earlier override. A stricter norm added later
  only updates the shortfall text on the next save.
- **Job Applicant:** cadre and qualification fields; the shortfall is shown, nothing is blocked.

## Sanctioned Post (Faculty > Masters)
Department, cadre, academic year and the sanctioned count; one record per department, cadre and year.

## Reports (filters: company, academic year, department)
A teacher of the year is a Teaching employee who joined by the year end and was not relieved before the year start.
- Faculty vs Sanctioned Posts (NAAC 2.4.1): sanctioned, filled, vacant per department and cadre.
- PhD Faculty (2.4.2): teachers and those with a PhD awarded by the year end.
- Teaching Experience (2.4.3): years in this institution at the year end; average in the summary.
- Cadre Ratio: ceil(students / SFR) split by the ratio shares (half-up), against teachers on roll.
- Student-Teacher Ratio (2.2.2): students with a submitted Program Enrollment of the year per teacher, by
  the program's department.

IQAC data points (for Phase 3 formulas): `full_time_teachers`, `sanctioned_posts`, `phd_teachers`,
`teacher_experience_years` (sum; divide by `full_time_teachers` for 2.4.3), `student_teacher_ratio`.

Demo (`make_demo`): norm "AICTE APH (demo)" (SFR 20, 1:2:6), 2026-27 sanctioned posts CSE 1/2/6 and ECE 1/1/3,
and the four demo instructors as CSE Professor, Associate Professor and two Assistant Professors.

## Course allocation and workload (M07-02)
- **Workload norm** is part of the Faculty Norm: each cadre row has Min and Max Teaching Hours / Week, and the norm
  has an Overload Block Margin (default 2 hours).
- **Course Allocation** (Faculty > Transactions): one per department and term, covering the course offerings
  (course-based Student Groups) of the department's programs. Rows give the offering, the faculty and the weekly
  Lecture / Tutorial / Practical hours. The faculty must be an active Employee with an Instructor record.
- A teacher's weekly total counts this allocation plus every other submitted allocation of the term. Above the cadre
  maximum the form warns. Above maximum + margin the save is blocked unless the **Dean Academics** (Position Holder
  of DEAN-ACADEMICS) enters a Dean Override Reason; the Dean is recorded, and the override lapses if the rows or the
  reason change afterwards.
- Every offering of the term needs at least one faculty before the allocation can be submitted; the form warns
  while offerings are missing. Approval goes through the approval engine (demo policy "Course Allocation - HOD":
  the HOD of the department). With no policy it submits directly.
- On submit the faculty are added as instructors of the offerings (existing instructors stay); cancel removes the
  ones the allocation added.
- **Workload Balance** report (company and term required, department optional): per teacher the Lecture, Tutorial
  and Practical hours of submitted allocations against the norm's min / max with a status (Under, Within, Over,
  Beyond Limit), a total row per department and a summary.

## Timetable (M07-03)

1. Give each Room a Room Type (Classroom, Lab, Skill Lab, Seminar Hall; Exam Hall is not timetabled) and Seating Capacity. Create a Timetable Slot Template (days, numbered periods with times, breaks, practical block length, soft daily maximum per teacher).
2. Submit the term's Course Allocations (the solver reads their weekly Lecture / Tutorial / Practical hours).
3. Create a Timetable (company, term, template, optional department), list any Faculty Unavailability, then Actions > Generate. The Timetable Generation Run records what was placed and every constraint it could not satisfy.
4. Edit the grid by hand if needed (every save is checked for faculty, room and section clashes, lab rules and unavailability). Actions > Check Clashes opens the Timetable Clash Checker.
5. Actions > Publish creates Course Schedules for each matching weekday to term end. Publishing again replaces only this timetable's Course Schedules from today on; past schedules and any schedule with Student Attendance are kept.

Not yet: electives of a group in parallel, cross-timetable clash checks (education's own Course Schedule overlap check is the safety net at publish), holidays, class/faculty/room print formats, OR-Tools CP-SAT backend (the pure-Python solver sits behind `solver.solve`).

## Leave and substitution (M07-03)

1. When a Leave Application is approved (submitted as Approved), a Substitution is proposed for every published Course Schedule of that teacher in the leave dates. The proposed substitute is a free teacher of the same department (no class or other substitution at that time, not on approved leave), the one covering least so far. If nobody is free the substitute is left blank.
2. Open the Substitution (Faculty > Substitution): Suggest Substitutes lists the free teachers; set the Substitute and change Status to Confirmed. Confirming sends the substitute the `substitution.assigned` message. A manual choice is checked for clashes and leave. A Cancelled substitution stays cancelled; cancelling the leave cancels its substitutions.
3. Print format Substitution Order gives the order for the period.
4. The confirmed substitute opens the Substitution and uses Mark Attendance. The Confirmed Substitution is the permission: it covers that Course Schedule only, for students of its Student Group, and the user's roles do not change. The Instructor role alone sees only their own substitutions, read-only.

Not yet: feeding approved leave into Timetable faculty unavailability (that table is per Timetable, by weekday), half-day leave (the whole day's periods are proposed), holidays.

## Payroll (M07-07)
Aided and self-financing payroll on HRMS: see [payroll.md](payroll.md).
