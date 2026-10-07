"""M05-06 Grievance rules: category check, student department, resolution and SLA escalation.

The escalation chain is the levels of the category's Approval Policy. Past a level's SLA the hourly job moves
the request to the next level (new approvers, new deadline) and notes it in the trail; the earlier level's
approvers can no longer act. The last level has nowhere to go (the generic approval reminder covers it).
A grievance is resolved by a current approver (or a committee member), which approves the request and submits
the document. Both paths lock the grievance first and the request second, and re-read under that lock.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime

from campus.campus_platform import approval_rules as rules
from campus.campus_platform.approval_engine import acting_capacity, acting_for, add_action, latest_request, start_level
from campus.examinations.access import COMMITTEE_ROLES, has_any_role

SAVEPOINT = "grievance_escalation"


def category_settings(category):
	"""The oc_ settings of a Grievance Type; throws unless students may raise it and it has an escalation policy."""
	settings = frappe.db.get_value(
		"Grievance Type", category, ["oc_applies_to_students", "oc_confidential", "oc_escalation_policy"], as_dict=True
	)
	if not settings or not settings.oc_applies_to_students:
		frappe.throw(_("{0} is not a student grievance category.").format(frappe.bold(category)))
	if not settings.oc_escalation_policy:
		frappe.throw(_("Grievance category {0} has no escalation policy.").format(frappe.bold(category)))
	return settings


def student_department(student):
	"""Department of the programme of the student's latest submitted enrolment, or None."""
	program = frappe.db.get_value(
		"Program Enrollment", {"student": student, "docstatus": 1}, "program", order_by="creation desc"
	)
	return program and frappe.db.get_value("Program", program, "department")


def open_grievance(student, category, description, attachment=None):
	"""Raise a grievance for `student` (the caller has resolved who the student is); returns the document."""
	grievance = frappe.get_doc(
		{
			"doctype": "Student Grievance", "student": student, "category": category,
			"description": (description or "").strip(), "attachment": attachment,
		}
	)  # fmt: skip
	grievance.flags.ignore_permissions = True  # portal roles may only read; the student is server-resolved
	return grievance.insert()


@frappe.whitelist()
def resolve(name, resolution):
	"""Close grievance `name` with `resolution`: current approvers and committee members only."""
	grievance = frappe.get_doc("Student Grievance", name, for_update=True)
	grievance.check_permission("read")
	if grievance.docstatus != 0:
		frappe.throw(_("{0} is already closed.").format(name))
	request_name = latest_request(grievance).name
	request = frappe.get_doc("Approval Request", request_name, for_update=True)
	if request.status != rules.PENDING:
		frappe.throw(_("{0} is {1}; it cannot be resolved.").format(name, _(request.status)))
	on_behalf_of = None if has_any_role(frappe.session.user, COMMITTEE_ROLES) else acting_for(request, frappe.session.user)
	add_action(request, rules.APPROVE, request.current_level, on_behalf_of=on_behalf_of, comment=resolution)
	request.status = rules.APPROVED
	request.save(ignore_permissions=True)
	grievance.resolution = resolution
	grievance.flags.ignore_approval_lock = True
	grievance.flags.ignore_permissions = True  # the approver or committee member was checked above
	grievance.submit()
	return grievance.status


def escalate_overdue():
	"""Hourly job: move every open grievance whose level is past its SLA to the next level."""
	overdue = frappe.get_all(
		"Approval Request",
		{"reference_doctype": "Student Grievance", "status": rules.PENDING, "due_at": ["<", now_datetime()]},
		pluck="name",
	)
	for name in overdue:
		frappe.db.savepoint(SAVEPOINT)
		try:
			escalate(name)
		except Exception as error:
			frappe.db.rollback(save_point=SAVEPOINT)
			frappe.log_error(
				title=f"Grievance escalation failed for {name}",
				message=f"{type(error).__name__}: {error}",
				reference_doctype="Approval Request",
				reference_name=name,
			)
		frappe.db.commit()


def escalate(request_name):
	"""Move the request to its next level if it is still pending, overdue and has a next level; True if moved.

	Idempotent: moving resets the deadline, so a second run finds nothing overdue. The grievance is locked
	before the request (as `resolve` does) and every fact is re-read under the locks."""
	reference = frappe.db.get_value("Approval Request", request_name, "reference_name")
	if frappe.db.get_value("Student Grievance", reference, "docstatus", for_update=True) != 0:
		return False
	request = frappe.get_doc("Approval Request", request_name, for_update=True)
	if not rules.needs_escalation(request.status, request.due_at, 0, now_datetime()):
		return False
	policy = frappe.get_doc("Approval Policy", request.policy)
	level = request.current_level
	if level >= len(policy.levels):
		return False
	grievance = frappe.get_doc("Student Grievance", reference)
	note = _("SLA of level {0} passed; escalated to level {1}.").format(level, level + 1)
	add_action(request, rules.ESCALATE, level, comment=note, by="Administrator")
	start_level(request, policy, grievance, level + 1)
	request.save(ignore_permissions=True)
	return True
