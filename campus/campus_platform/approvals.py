"""M17-03 Generic approval engine: policies, levels, delegation and the `ApprovableDocument` mixin.

A submittable DocType opts in with `class MyDoc(ApprovableDocument, Document)`. Its owner calls
`request_approval`; the matching Approval Policy's levels are worked through by `approve`; the final
approval runs the policy's on-final action (submit by default). Submitting directly is blocked while
a policy matches and no approval exists. With no matching policy the document submits directly.

The engine itself lives in `approval_engine.py`; this module holds the mixin, the whitelisted API,
the submit/edit guards and the form summary.
"""

import frappe
from frappe import _

from campus.campus_platform import approval_rules as rules
from campus.campus_platform.approval_changes import changed_fields
from campus.campus_platform.approval_engine import (
	act,
	acting_capacity,
	current_approvers,
	delegator_for,
	find_policy,
	latest_request,
	start_request,
)


class ApprovableDocument:
	"""Mixin for submittable controllers; list it before `Document`. Overrides must call super()."""

	def validate(self):
		_call_next(self, ApprovableDocument, "validate")
		guard_edits(self)

	def before_submit(self):
		_call_next(self, ApprovableDocument, "before_submit")
		guard_submit(self)

	def on_trash(self):
		_call_next(self, ApprovableDocument, "on_trash")
		delete_requests(self)

	def onload(self):
		_call_next(self, ApprovableDocument, "onload")
		self.set_onload("approval", approval_summary(self))


def _call_next(doc, cls, method):
	parent = getattr(super(cls, doc), method, None)
	if parent:
		parent()


@frappe.whitelist()
def request_approval(doctype, name):
	"""Start (or restart after Return) approval of a draft; submits directly when no policy matches."""
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("submit")
	if not isinstance(doc, ApprovableDocument):
		frappe.throw(_("{0} does not use approvals.").format(_(doctype)))
	request = start_request(doc)
	return request.name if request else None


@frappe.whitelist()
def approve(request, comment=None):
	return act(request, rules.APPROVE, comment)


@frappe.whitelist()
def reject(request, comment=None):
	return act(request, rules.REJECT, comment)


@frappe.whitelist()
def return_for_changes(request, comment=None):
	return act(request, rules.RETURN, comment)


def guard_submit(doc):
	latest = latest_request(doc)
	if latest and latest.status == rules.APPROVED:
		return
	if latest and latest.status == rules.PENDING:
		frappe.throw(_("{0} is awaiting approval in {1}.").format(doc.name, latest.name))
	if find_policy(doc):
		frappe.throw(
			_("{0} needs approval before it can be submitted. Use Request Approval.").format(doc.name)
		)


def guard_edits(doc):
	"""While pending only current approvers may change their level's editable fields; approved is frozen."""
	if doc.is_new() or doc.docstatus != 0 or doc.flags.ignore_approval_lock:
		return
	latest = latest_request(doc)
	if not latest or latest.status not in (rules.PENDING, rules.APPROVED):
		return
	changed = changed_fields(doc, doc.get_doc_before_save())
	if not changed:
		return
	if latest.status == rules.APPROVED:
		frappe.throw(_("{0} is approved and can no longer be changed.").format(doc.name))
	blocked = rules.disallowed_changes(changed, _editable_fields(latest.name))
	if blocked:
		frappe.throw(
			_("{0} is awaiting approval; you cannot change: {1}").format(doc.name, ", ".join(blocked))
		)


def _editable_fields(request_name):
	request = frappe.get_doc("Approval Request", request_name)
	user = frappe.session.user
	current = current_approvers(request)
	if user not in current and not delegator_for(user, current, request.reference_doctype):
		return []
	level = frappe.get_doc("Approval Policy", request.policy).levels[request.current_level - 1]
	return rules.parse_fieldnames(level.can_edit_fields)


def delete_requests(doc):
	for name in frappe.get_all(
		"Approval Request",
		filters={"reference_doctype": doc.doctype, "reference_name": doc.name},
		pluck="name",
	):
		request = frappe.get_doc("Approval Request", name)
		request.flags.reference_deleted = True
		request.delete(ignore_permissions=True)


def approval_summary(doc):
	"""Data for the form's approval panel: trail, status and what the session user may do."""
	latest = latest_request(doc)
	if not latest and (doc.docstatus != 0 or not find_policy(doc)):
		return None
	summary = {"can_request": doc.docstatus == 0 and doc.has_permission("submit")}
	if not latest:
		return summary
	request = frappe.get_doc("Approval Request", latest.name)
	summary.update(
		request=request.name,
		status=request.status,
		current_level=request.current_level,
		due_at=request.due_at,
		trail=[row.as_dict() for row in request.actions],
		can_act=request.status == rules.PENDING and acting_capacity(request, frappe.session.user)[0],
	)
	summary["can_request"] = summary["can_request"] and request.status in (rules.RETURNED, rules.REJECTED)
	return summary
