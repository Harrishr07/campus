"""M05-07 Mentor allocation: spread a cohort of students evenly over mentors (Student.oc_mentor).

Mentors are the users holding the MENTOR position (Position Holder); the position grants them the Mentor
role, and the portal permission hooks (campus.examinations.access) narrow that role to their mentees.
"""

import frappe
from frappe import _

from campus.campus_platform.api import resolve_position
from campus.campus_platform.company_scope import permitted_companies
from campus.student_services.onboarding import mark_item_done

ALLOCATOR_ROLES = ("HOD", "Dean Academics", "Dean Student Affairs")
MENTOR_POSITION = "MENTOR"
# A program-wide cohort is one long request holding a lock on every student row: above this size the HOD
# allocates per Student Group instead.
MAX_PROGRAM_COHORT = 150


def allocate(student_group=None, program=None, batch=None, mentors=None, per_mentor=None):
	"""See `campus.student_services.api.allocate_mentors`."""
	frappe.only_for(ALLOCATOR_ROLES)
	students = cohort(student_group, program, batch)
	check_company_access(students)
	mentors = resolve_mentors(mentors, cohort_company(students))
	check_capacity(len(students), len(mentors), per_mentor)
	assignment = {}
	for index, student in enumerate(students):
		mentor = mentors[index % len(mentors)]
		frappe.db.set_value("Student", student.name, "oc_mentor", mentor)
		mark_item_done(student.name, "MENTOR")
		assignment.setdefault(mentor, []).append(student.name)
	return assignment


def position_employees(company):
	"""{employee: user} for active employees of `company` whose user holds the MENTOR position today."""
	users = resolve_position(MENTOR_POSITION)
	if not users:
		return {}
	rows = frappe.get_all(
		"Employee",
		filters={"user_id": ["in", users], "status": "Active", "company": company},
		fields=["name", "user_id"],
		order_by="name",
	)
	return {row.name: row.user_id for row in rows}


def cohort_company(students):
	companies = {s.oc_company for s in students}
	if len(companies) > 1:
		frappe.throw(_("The students belong to more than one company; allocate one company at a time."))
	return companies.pop()


def resolve_mentors(mentors, company):
	"""The Employees of `company` to allocate to: the given ones, or every active MENTOR position holder there."""
	holders = position_employees(company)
	chosen = list(dict.fromkeys(frappe.parse_json(mentors) or [])) or list(holders)
	if not chosen:
		frappe.throw(_("No mentors: no active employee of {0} holds the Mentor position.").format(company))
	for employee in chosen:
		if employee not in holders:
			frappe.throw(
				_("Employee {0} does not hold the Mentor position in {1}.").format(employee, company)
			)
	return chosen


def cohort(student_group, program, batch):
	"""Students to allocate, locked for update, in a fixed order (register no, then id)."""
	if student_group:
		names = frappe.get_all(
			"Student Group Student", filters={"parent": student_group, "active": 1}, pluck="student"
		)
	elif program and batch:
		names = frappe.get_all(
			"Program Enrollment", filters={"program": program, "docstatus": 1}, pluck="student", distinct=True
		)
	else:
		frappe.throw(_("Give a student group, or a program and a batch."))
	student = frappe.qb.DocType("Student")
	query = frappe.qb.from_(student).select(
		student.name, student.oc_register_no, student.oc_company, student.oc_batch
	)
	students = (
		query.where(student.name.isin(names or [""])).for_update().run(as_dict=True)
	)  # locked: facts below are current
	if not student_group:
		students = [s for s in students if s.oc_batch == batch]
		if len(students) > MAX_PROGRAM_COHORT:
			frappe.throw(
				_(
					"{0} students is too many to allocate at once (limit {1}); allocate per Student Group."
				).format(len(students), MAX_PROGRAM_COHORT)
			)
	if not students:
		frappe.throw(_("No students found to allocate."))
	return sorted(students, key=lambda s: (s.oc_register_no or "", s.name))


def check_company_access(students):
	permitted = permitted_companies(frappe.session.user)
	if permitted is not None and any(s.oc_company not in permitted for s in students):
		frappe.throw(
			_("You are not permitted to allocate mentors for these students."), frappe.PermissionError
		)


def check_capacity(student_count, mentor_count, per_mentor):
	busiest = -(-student_count // mentor_count)
	if per_mentor and busiest > int(per_mentor):
		frappe.throw(
			_("{0} students over {1} mentors needs up to {2} per mentor, above the limit of {3}.").format(
				student_count, mentor_count, busiest, per_mentor
			)
		)


def set_class_advisor(doc, method=None):
	"""Student validate: the CLASS-ADVISOR of the first of the student's groups that has one (Position Holder)."""
	groups = (
		frappe.get_all(
			"Student Group Student",
			filters={"student": doc.name, "parenttype": "Student Group", "active": 1},
			pluck="parent",
		)
		if doc.name
		else []
	)
	doc.oc_class_advisor = next((u for g in groups for u in resolve_position("CLASS-ADVISOR", scope=g)), None)
