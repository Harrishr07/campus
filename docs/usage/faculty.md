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
