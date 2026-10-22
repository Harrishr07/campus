"""M14-01 Placement eligibility from LIVE results: CGPA, standing arrears and history of arrears are read from the
published results at the moment of asking (campus.examinations.api), never stored as a flag, so a student who clears
an arrear is eligible the next time it is asked without any manual change. The Drive Registration keeps a snapshot of
the standing at registration as evidence only."""

import frappe
from frappe import _

from campus.examinations import api as exams
from campus.placement import rules
from campus.student_services.api import ON_ROLL

CRITERIA_FIELDS = ("min_cgpa", "any_standing_arrears", "max_standing_arrears", "allow_arrear_history", "gender")


def criteria_of(doc):
	"""The eligibility criteria of a Placement Drive or Placement Eligibility Template as the rules' dict."""
	criteria = {field: doc.get(field) for field in CRITERIA_FIELDS}
	criteria["programs"] = [row.program for row in doc.programs]
	criteria["batches"] = [row.batch for row in doc.batches]
	return criteria


def current_program(student):
	"""The program of the student's latest submitted Program Enrollment."""
	return frappe.db.get_value(
		"Program Enrollment", {"student": student, "docstatus": 1}, "program", order_by="enrollment_date desc, creation desc"
	)


def student_standing(student):
	"""The student's live standing: CGPA, standing arrears and history of arrears from published results, plus the
	gender, program and batch the criteria look at."""
	info = frappe.db.get_value("Student", student, ["gender", "oc_batch", "oc_company", "oc_academic_status"], as_dict=True)
	return {
		"cgpa": exams.cgpa(student), "standing_arrears": len(exams.arrear_courses(student)),
		"had_arrears": bool(exams.had_arrears(student)), "gender": info.gender, "program": current_program(student),
		"batch": info.oc_batch, "company": info.oc_company, "status": info.oc_academic_status,
	}  # fmt: skip


def evaluate(drive, student, standing=None):
	"""{eligible, reasons, cgpa, standing_arrears, had_arrears} of `student` for the Placement Drive `drive` now.

	A student who is not on the roll of the drive's college is never eligible."""
	doc = frappe.get_doc("Placement Drive", drive) if isinstance(drive, str) else drive
	standing = standing or student_standing(student)
	found = rules.reasons(criteria_of(doc), standing)
	if standing["company"] != doc.company:
		found.insert(0, _("{0} does not belong to {1}").format(student, doc.company))
	if standing["status"] not in ON_ROLL:
		found.insert(0, _("Only students on the roll can register; {0} is {1}").format(student, _(standing["status"] or "not set")))
	return {
		"eligible": not found, "reasons": found, "cgpa": standing["cgpa"],
		"standing_arrears": standing["standing_arrears"], "had_arrears": standing["had_arrears"],
	}  # fmt: skip


@frappe.whitelist()
def template_criteria(template):
	"""Criteria of a Placement Eligibility Template for the drive form to copy when the template is chosen."""
	frappe.has_permission("Placement Eligibility Template", "read", template, throw=True)
	return template_values(template)


def template_values(template):
	"""Criteria fields and rows of a Placement Eligibility Template, ready to set on a drive."""
	doc = frappe.get_doc("Placement Eligibility Template", template)
	values = {field: doc.get(field) for field in CRITERIA_FIELDS}
	values["programs"] = [{"program": row.program} for row in doc.programs]
	values["batches"] = [{"batch": row.batch} for row in doc.batches]
	return values
