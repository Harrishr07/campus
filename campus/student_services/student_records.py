"""M06-01, M05-03 Student records services: the regulation values the withdrawal, break and rejoin documents read,
the withdrawal code of a course result and the bridge courses still owed after a rejoin.

The examinations module calls `withdrawal_code` (Result Run) and `pending_bridge_courses` (exam registration)
through campus.student_services.api; this module reaches examinations only lazily (its api imports ours).
"""

import frappe
from frappe import _

from campus.campus_platform.api import get_rule, resolve_position
from campus.student_services import withdrawal_rules

RULE_SET = "Exam Rule Set"


def rule_values(student):
	"""{withdrawal_days, break_max_years, break_exceptional_years} of the student's Exam Rule Set."""
	rule = get_rule(student, RULE_SET)
	return frappe._dict(
		withdrawal_days=rule.get("oc_withdrawal_days") or 0,
		break_max_years=rule.get("oc_break_max_years") or 0,
		break_exceptional_years=rule.get("oc_break_exceptional_years") or 0,
	)


def regulation_withdrawal_code(student):
	"""The withdrawal result code (WD, WC, W) of the student's Grading Scheme; throws when it has none."""
	from campus.examinations.api import WITHDRAWAL_CODES

	codes = [row.code for row in get_rule(student, "Grading Scheme").codes]
	code = withdrawal_rules.withdrawal_code(codes, WITHDRAWAL_CODES)
	if not code:
		frappe.throw(_("The Grading Scheme of the regulation of {0} has no withdrawal code.").format(frappe.bold(student)))
	return code


def withdrawal_code(student, exam_session, course):
	"""The code of the student's approved (submitted) withdrawal from `course` in the session, or None.

	None on a site whose DocTypes are not migrated yet: the Result Run of a shared tree must not break."""
	if not frappe.db.table_exists("Exam Withdrawal Application"):
		return None
	application, row = frappe.qb.DocType("Exam Withdrawal Application"), frappe.qb.DocType("Exam Withdrawal Course")
	found = (
		frappe.qb.from_(application)
		.join(row)
		.on((row.parent == application.name) & (row.parenttype == "Exam Withdrawal Application"))
		.select(application.withdrawal_code)
		.where((application.student == student) & (application.exam_session == exam_session))
		.where((application.docstatus == 1) & (row.course == course))
		.limit(1)
		.run()
	)
	return found[0][0] if found else None


def pending_bridge_courses(student):
	"""Bridge courses (sorted) of the student's approved rejoins with no Student Result row yet. Once sat, a
	bridge course is an ordinary pass or arrear. Empty on a site whose DocTypes are not migrated yet."""
	if not frappe.db.table_exists("Rejoin Application"):
		return []
	rejoin, row = frappe.qb.DocType("Rejoin Application"), frappe.qb.DocType("Rejoin Bridge Course")
	bridge = (
		frappe.qb.from_(rejoin)
		.join(row)
		.on((row.parent == rejoin.name) & (row.parenttype == "Rejoin Application"))
		.select(row.course)
		.distinct()
		.where((rejoin.student == student) & (rejoin.docstatus == 1))
		.run(pluck=True)
	)
	if not bridge:
		return []
	result, course = frappe.qb.DocType("Student Result"), frappe.qb.DocType("Student Result Course")
	sat = (
		frappe.qb.from_(result)
		.join(course)
		.on((course.parent == result.name) & (course.parenttype == "Student Result"))
		.select(course.course)
		.where((result.student == student) & course.course.isin(bridge))
		.run(pluck=True)
	)
	return sorted(set(bridge) - set(sat))


def refresh_result(student, exam_session):
	"""Recompute the student's Student Result of the session, if the Result Run has made one."""
	from campus.examinations.api import refresh_student_result

	refresh_student_result(student, exam_session)


def is_principal(company, user=None):
	return (user or frappe.session.user) in resolve_position("PRINCIPAL", company)


def student_department(program):
	return program and frappe.db.get_value("Program", program, "department")
