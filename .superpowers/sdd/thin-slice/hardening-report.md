# Portal privacy hardening report

Scope: Student/Guardian role read access narrowed to rows linked to the user's own / guarded students, on top of the Student hook from e233748.

## Permission audit (education.localhost, DocPerm + Custom DocPerm, read-only)
Roles Student/Guardian have read (level 0) on:

| Doctype | Student | Guardian | Decision |
|---|---|---|---|
| Student | yes | yes | scoped (existing, now generic) |
| Guardian | no | yes | scoped: own record + guardians of linked students |
| Program Enrollment | yes | yes | scoped by `student` |
| Student Attendance | yes | yes | scoped by `student` |
| Student Leave Application | yes | yes | scoped by `student` |
| Assessment Result | yes | yes | scoped by `student` |
| Sales Invoice | yes | no | scoped by `student` (Student role only; Guardian has none) |
| Course Schedule | yes | yes | scoped by `student_group` in groups containing a linked student |
| Student Result, Mark Sheet Entry | - | - | already scoped (earlier work) |
| Program | yes | yes | left public (catalogue) |
| Circular | yes | yes | left; already has its own audience hook |

Not granted to either role, so not hooked: Student Group, Course Enrollment, Fees, Course, Academic Year/Term, Room. Student Group and
Course Enrollment/Fees were not scoped: with no read grant the roles cannot reach them, and unused hooks would be speculative. If an admin
later grants read via Custom DocPerm, add the doctype to `PORTAL_SCOPES` (one line; hooks follow automatically).

## Change
- `campus/examinations/access.py`: `students_of` moved up; new `guardians_of`, `groups_of`; `PORTAL_SCOPES` table (doctype -> key field, key function);
  `sees_all_students(user, doctype="Student")` generalised and now ignores permlevel > 0 grants (Sales Invoice gives role `All` read at level 1);
  `student_permission_query/has_permission` replaced by generic `portal_permission_query/portal_has_permission`.
- `campus/hooks.py`: hooks for every `PORTAL_SCOPES` doctype built by dict-unpacking, merged beside the existing Circular/Approval/Lead/Mark/Result hooks.
- `campus/tests/test_portal_privacy.py`: 6 tests.

## Verification
- Tests: student A vs B (get_list + get_doc) for all 8 doctypes, symmetric check, guardian scope (own + second guardian of linked student, other student's guardian hidden),
  Course Schedule follows groups, staff (Administrator, Academics User, Instructor) still see all rows of every doctype they can read.
  A first run caught the real bug of the permlevel-1 `All` grant defeating Sales Invoice scoping.
- Live HTTP on education.localhost (demo password): student_1 and guardian_1 get 200 on /campus-portal (index, fees, attendance, results, circulars) and /edu-portal.
  REST counts: student_1 sees 1 Student, 1 Program Enrollment, 96 own attendance of 480, 1 Sales Invoice of 5, 0 of 1 leave application (another student's);
  guardian_1 sees the same student plus its Guardian record. Administrator, coe (Academics User) and faculty_1 (Instructor) counts unchanged
  (480 attendance, 96 schedules, 35 Program Enrollments; Student 36 admin vs 35 company-scoped staff, as before).
- Both sites migrated. Full suite (scripts/test.sh): `Ran 674 tests in 1143.708s` then `OK`.

## Notes / concerns
- Course Schedule for student_1 is 96 because all demo schedules belong to the four groups student_1 is in.
- `portal.linked_students` (student_services/portal.py) still duplicates the `students_of` logic; left alone (out of scope), could call `students_of`.
- Server-side code using `frappe.get_all` (portal pages) bypasses these hooks by design; the hooks protect desk/REST/get_list/get_doc.
