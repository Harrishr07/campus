"""M17-03 SLA escalation: an overdue level is escalated once; its original approvers can still act."""

import frappe
from frappe import _
from frappe.utils import now_datetime

from campus.campus_platform import approval_rules as rules
from campus.campus_platform.approval_engine import add_action, current_approvers
from campus.campus_platform.approver_resolution import resolve_approvers
from campus.campus_platform.notify import notify


def escalate_overdue():
	"""Hourly job: escalate every pending request whose current level is past due."""
	overdue = frappe.get_all(
		"Approval Request",
		filters={"status": rules.PENDING, "escalated": 0, "due_at": ["<", now_datetime()]},
		pluck="name",
	)
	for name in overdue:
		try:
			escalate(name)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"Approval escalation failed for {name}")


def escalate(request_name):
	"""Add the level's escalation approvers (or remind the current ones if none is set). Once per level."""
	request = frappe.get_doc("Approval Request", request_name, for_update=True)
	if not rules.needs_escalation(request.status, request.due_at, request.escalated, now_datetime()):
		return []
	doc = frappe.get_doc(request.reference_doctype, request.reference_name)
	level = frappe.get_doc("Approval Policy", request.policy).levels[request.current_level - 1]
	current = current_approvers(request)
	added = _escalation_users(level, doc, current)
	for user in added:
		request.append(
			"approvers",
			{"cycle": request.cycle, "level": request.current_level, "user": user, "source": "Escalation"},
		)
	request.escalated = 1
	add_action(
		request, rules.ESCALATE, request.current_level, comment=", ".join(added) or None, by="Administrator"
	)
	request.save(ignore_permissions=True)
	subject = _("Overdue approval: {0} {1}").format(_(doc.doctype), doc.name)
	notify(
		added or current,
		subject,
		_("Level {0} passed its due time {1}.").format(request.current_level, request.due_at),
		doc,
	)
	return added


def _escalation_users(level, doc, current):
	if not level.escalate_to_type:
		return []
	users = resolve_approvers(
		level.escalate_to_type, level.escalate_to, doc, level.escalate_scope_field, limit_to_company=True
	)
	return [u for u in users if u not in current]
