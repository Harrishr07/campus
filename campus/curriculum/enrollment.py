"""M03-04 Enrollment effects of a Course Registration: offering membership and Course Enrollment rows.

Membership of the offering Student Group is the single record of who holds a seat, so seat counts,
duplicate checks and the HOD report all read it. Every operation is idempotent.
"""

import frappe


def count_members(curriculum, course, academic_term):
	"""Active students across the offering groups of `course` in the term."""
	group = frappe.qb.DocType("Student Group")
	member = frappe.qb.DocType("Student Group Student")
	rows = (
		frappe.qb.from_(group)
		.join(member)
		.on(member.parent == group.name)
		.select(frappe.qb.functions("COUNT", member.student))
		.where((group.oc_curriculum == curriculum) & (group.course == course))
		.where((group.academic_term == academic_term) & (member.active == 1))
		.run()
	)
	return rows[0][0]


def current_offering(student, course, academic_term):
	"""The offering group of `course` in the term that already holds `student`, or None."""
	group = frappe.qb.DocType("Student Group")
	member = frappe.qb.DocType("Student Group Student")
	rows = (
		frappe.qb.from_(group)
		.join(member)
		.on(member.parent == group.name)
		.select(group.name)
		.where((member.student == student) & (group.course == course))
		.where((group.academic_term == academic_term) & (group.oc_curriculum.isnotnull()))
		.limit(1)
		.run()
	)
	return rows[0][0] if rows else None


def find_offering(curriculum, course, academic_term, section=None):
	"""The offering to join: the student's own section when it exists, else the first one by name."""
	offerings = frappe.get_all(
		"Student Group",
		filters={"oc_curriculum": curriculum, "course": course, "academic_term": academic_term, "disabled": 0},
		fields=["name", "oc_section"],
		order_by="name",
	)
	for offering in offerings:
		if section and offering.oc_section == section:
			return offering.name
	return offerings[0].name if offerings else None


def enroll(student, item, program_enrollment, enrollment_date):
	"""Add the student to the row's offering and create the Course Enrollment, each only once."""
	group = frappe.get_doc("Student Group", item.offering, for_update=True)
	if not any(row.student == student for row in group.students):
		group.append("students", {"student": student, "active": 1})
		group.save(ignore_permissions=True)
	if not frappe.db.exists(
		"Course Enrollment", {"student": student, "course": item.course, "program_enrollment": program_enrollment}
	):
		frappe.get_doc(
			{
				"doctype": "Course Enrollment",
				"student": student,
				"course": item.course,
				"program_enrollment": program_enrollment,
				"enrollment_date": enrollment_date,
			}
		).insert(ignore_permissions=True)


def unenroll(student, item, program_enrollment):
	"""Remove the student from the row's offering and delete the Course Enrollment, if present."""
	group = frappe.get_doc("Student Group", item.offering, for_update=True)
	rows = [row for row in group.students if row.student == student]
	if rows:
		for row in rows:
			group.remove(row)
		group.save(ignore_permissions=True)
	for name in frappe.get_all(
		"Course Enrollment", {"student": student, "course": item.course, "program_enrollment": program_enrollment}, pluck="name"
	):
		frappe.delete_doc("Course Enrollment", name, ignore_permissions=True)
