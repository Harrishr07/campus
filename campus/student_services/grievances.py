"""M05-06 Grievance rules: category check, student department, resolution and SLA escalation.

The escalation chain is the levels of the category's Approval Policy. Past a level's SLA the hourly job moves
the request to the next level (new approvers, new deadline) and notes it in the trail; the earlier level's
approvers can no longer act. The last level has nowhere to go: past its SLA its approvers are reminded once (the
request is marked escalated, nothing moves; the generic approval job leaves grievances alone).
A grievance is resolved by a current approver (or a committee member), which approves the request and submits
the document. Both paths lock the grievance first and the request second, and re-read under that lock.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, strip_html

from campus.campus_platform import approval_rules as rules
from campus.campus_platform.approval_engine import (
	acting_for,
	add_action,
	current_approvers,
	latest_request,
	start_level,
	start_request,
)
from campus.campus_platform.approver_resolution import resolve_approvers
from campus.campus_platform.notify import notify
from campus.examinations.access import COMMITTEE_ROLE, COMMITTEE_ROLES, has_any_role

SAVEPOINT = "grievance_escalation"
DESCRIPTION_LIMIT = 5000
PRINCIPAL_POSITION = "PRINCIPAL"


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


def validate_category(doc, method=None):
	"""Doc event (Grievance Type validate): a student category's policy must be a Student Grievance policy, and a
	confidential category's levels must all be the committee, or the handlers would be notified of what they cannot read."""
	if not doc.get("oc_escalation_policy"):
		return
	policy = frappe.get_doc("Approval Policy", doc.oc_escalation_policy)
	if policy.document_type != "Student Grievance":
		frappe.throw(_("{0} is not a Student Grievance policy.").format(frappe.bold(policy.name)))
	if doc.oc_confidential and not all(lv.approver_type == "Role" and lv.approver in COMMITTEE_ROLES for lv in policy.levels):
		frappe.throw(_("A confidential category needs a policy whose every level is the Grievance Committee role."))


def check_description(description):
	if len(description or "") > DESCRIPTION_LIMIT:
		frappe.throw(_("The description is too long (at most {0} characters).").format(DESCRIPTION_LIMIT))


def route(grievance):
	"""Start the grievance's approval request at the first level that can be resolved (a vacant HOD seat or a student
	with no department must not refuse a complaint). Each skipped level is logged for the administrators (a plain
	message, no context) and its message is dropped, so nothing about the policy reaches the student. With no
	resolvable level the grievance is left unrouted for the committee (see notify_unrouted)."""
	policy = frappe.get_doc("Approval Policy", grievance.escalation_policy)
	for level_no in range(1, len(policy.levels) + 1):
		shown = len(frappe.local.message_log)
		frappe.db.savepoint(SAVEPOINT)
		try:
			return start_request(grievance, policy, level_no)
		except frappe.ValidationError as error:
			frappe.db.rollback(save_point=SAVEPOINT)
			del frappe.local.message_log[shown:]
			frappe.log_error(
				title=f"Grievance {grievance.name}: level {level_no} skipped at intake",
				message=f"{type(error).__name__}: {strip_html(str(error))}",
				reference_doctype="Student Grievance",
				reference_name=grievance.name,
			)
	notify_unrouted(grievance)


def notify_unrouted(grievance):
	"""Tell who must take a grievance no level could route: the committee; with nobody in it the Principal (never
	for a confidential grievance), else the System Managers, so the grievance is never orphaned."""
	users = resolve_approvers("Role", COMMITTEE_ROLE, grievance)
	message = _("No approver could be found for the escalation levels; the grievance committee should handle it.")
	if not users:
		users = [] if grievance.is_confidential else resolve_approvers("Position", PRINCIPAL_POSITION, grievance, "company")
		users = users or resolve_approvers("Role", "System Manager", grievance, limit_to_company=True)
		message = _("No approver could be found for the escalation levels and nobody holds the Grievance Committee role. "
			"Give the role to the committee members (or fill the vacant positions) so the grievance can be handled.")  # fmt: skip
	notify(users, _("Unrouted grievance: {0}").format(grievance.name), message, grievance)


def student_department(student):
	"""Department of the programme of the student's latest submitted enrolment, or None."""
	program = frappe.db.get_value(
		"Program Enrollment", {"student": student, "docstatus": 1}, "program", order_by="creation desc"
	)
	return program and frappe.db.get_value("Program", program, "department")


def open_grievance(student, category, description, attachment=None):
	"""Raise a grievance for `student` (the caller has resolved who the student is); returns the document."""
	check_description(description)
	grievance = frappe.get_doc(
		{
			"doctype": "Student Grievance", "student": student, "category": category,
			"description": (description or "").strip(), "attachment": attachment,
		}
	)  # fmt: skip
	grievance.flags.ignore_permissions = True  # portal roles may only read; the student is server-resolved
	return grievance.insert()


@frappe.whitelist(methods=["POST"])
def resolve(name, resolution):
	"""Close grievance `name` with `resolution`: current approvers and committee members only."""
	grievance = frappe.get_doc("Student Grievance", name, for_update=True)
	grievance.check_permission("read")
	if grievance.docstatus != 0:
		frappe.throw(_("{0} is already closed.").format(name))
	committee = has_any_role(frappe.session.user, COMMITTEE_ROLES)
	latest = latest_request(grievance)
	if latest:
		close_request(latest.name, committee, resolution, name)
	elif committee:
		grievance.flags.unrouted = True
	else:  # unrouted: only the committee can take it
		frappe.throw(_("Only the grievance committee can resolve {0}.").format(name), frappe.PermissionError)
	grievance.resolution = resolution
	grievance.flags.ignore_approval_lock = True
	grievance.flags.ignore_permissions = True  # the approver or committee member was checked above
	grievance.submit()
	return grievance.status


def close_request(request_name, committee, resolution, grievance_name):
	request = frappe.get_doc("Approval Request", request_name, for_update=True)
	if request.status != rules.PENDING:
		frappe.throw(_("{0} is {1}; it cannot be resolved.").format(grievance_name, _(request.status)))
	on_behalf_of = None if committee else acting_for(request, frappe.session.user)
	add_action(request, rules.APPROVE, request.current_level, on_behalf_of=on_behalf_of, comment=resolution)
	request.status = rules.APPROVED
	request.save(ignore_permissions=True)


def escalate_overdue():
	"""Hourly job: move every open grievance whose level is past its SLA to the next level."""
	overdue = frappe.get_all(
		"Approval Request",
		{"reference_doctype": "Student Grievance", "status": rules.PENDING, "escalated": 0, "due_at": ["<", now_datetime()]},
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
	"""Move the request to its next level if it is still pending, overdue and has a next level; True if moved. An
	overdue last level reminds its approvers instead, once (the request is marked escalated).

	Idempotent: moving resets the deadline, so a second run finds nothing overdue. The grievance is locked
	before the request (as `resolve` does) and every fact is re-read under the locks."""
	reference = frappe.db.get_value("Approval Request", request_name, "reference_name")
	if frappe.db.get_value("Student Grievance", reference, "docstatus", for_update=True) != 0:
		return False
	request = frappe.get_doc("Approval Request", request_name, for_update=True)
	if not rules.needs_escalation(request.status, request.due_at, request.escalated, now_datetime()):
		return False
	policy = frappe.get_doc("Approval Policy", request.policy)
	level = request.current_level
	grievance = frappe.get_doc("Student Grievance", reference)
	if level >= len(policy.levels):
		remind_last_level(request, grievance)
		return False
	note = _("SLA of level {0} passed; escalated to level {1}.").format(level, level + 1)
	add_action(request, rules.ESCALATE, level, comment=note, by="Administrator")
	start_level(request, policy, grievance, level + 1)
	request.save(ignore_permissions=True)
	return True


def remind_last_level(request, grievance):
	"""The last level is past its SLA: remind its approvers once. Not an escalation in the trail (nothing moved)."""
	request.escalated = 1
	request.save(ignore_permissions=True)
	notify(
		current_approvers(request),
		_("Overdue grievance: {0}").format(grievance.name),
		_("Level {0} passed its due time {1}; it is the last level, so the grievance stays with you.").format(
			request.current_level, request.due_at
		),
		grievance,
	)
