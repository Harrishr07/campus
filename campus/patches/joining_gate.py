"""M04-09 Joining gate on an existing site: students admitted before it count as joined on their enrollment date.

- The joining fields exist (patches run before after_migrate creates custom fields).
- The first submitted enrollment of a student made from an applicant becomes that applicant's joining enrollment
  (oc_joining_key), so a joining confirmation of the applicant returns it instead of enrolling them again.
- A student still Admitted who has a submitted enrollment moves to Joined, then Active, from its enrollment date
  (never before their last lifecycle change). Admitted students without one join through the joining confirmation.
Idempotent: keyed enrollments and joined students are left alone. Attendance start dates are not filled: only
the joining confirmation writes them (clear_legacy_attendance_start_dates undoes an earlier fill).
"""

import frappe
from frappe.utils import getdate

from campus.admissions.setup import setup_admission_fields
from campus.student_services.api import ACTIVE, ADMITTED, JOINED, last_change_date, transition

ENROLLMENT = "Program Enrollment"


def execute():
	setup_admission_fields()
	key_joining_enrollments()
	mark_admitted_students_joined()


def key_joining_enrollments():
	keyed = set(frappe.get_all(ENROLLMENT, {"oc_joining_key": ("is", "set")}, pluck="oc_joining_key"))
	for student in frappe.get_all(
		"Student", {"student_applicant": ("is", "set")}, ["name", "student_applicant"]
	):
		if student.student_applicant in keyed:
			continue
		first = frappe.db.get_value(
			ENROLLMENT, {"student": student.name, "docstatus": 1}, ["name", "oc_joining_key"], as_dict=True,
			order_by="enrollment_date asc, creation asc",
		)  # fmt: skip
		if first and not first.oc_joining_key:
			frappe.db.set_value(
				ENROLLMENT, first.name, "oc_joining_key", student.student_applicant, update_modified=False
			)
			keyed.add(student.student_applicant)


def mark_admitted_students_joined():
	for student in frappe.get_all("Student", {"oc_academic_status": ADMITTED}, pluck="name"):
		enrollment = frappe.db.get_value(
			ENROLLMENT, {"student": student, "docstatus": 1}, ["name", "enrollment_date"], as_dict=True,
			order_by="enrollment_date asc, creation asc",
		)  # fmt: skip
		if not enrollment:
			continue
		last = last_change_date(student)
		effective = (
			max(getdate(enrollment.enrollment_date), getdate(last)) if last else enrollment.enrollment_date
		)
		for status in (JOINED, ACTIVE):
			transition(
				student, status, effective, "Enrolled before the joining confirmation existed", (ENROLLMENT, enrollment.name),
				approved_by="Administrator", program_enrollment=enrollment.name,
			)  # fmt: skip
