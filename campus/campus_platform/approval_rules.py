"""M17-03 Pure approval rules: policy selection, level progression, SLA timing and delegation window.

No database access here; the engine in `approvals.py` feeds these functions plain values.
"""

import re
from datetime import timedelta

from frappe.utils import get_datetime, getdate

PENDING = "Pending"
APPROVED = "Approved"
REJECTED = "Rejected"
RETURNED = "Returned"

REQUEST = "Request"
APPROVE = "Approve"
REJECT = "Reject"
RETURN = "Return"
ESCALATE = "Escalate"


def select_policy(policies, company, condition_holds):
	"""The policy that governs a document of `company`, or None.

	Policies of another company are skipped. Higher `priority` is tried first; on equal priority a
	company-specific policy beats a generic one, then name order. The first policy whose condition
	is blank or holds (per `condition_holds(condition)`) wins.
	"""
	candidates = [p for p in policies if not p.get("company") or p.get("company") == company]
	candidates.sort(
		key=lambda p: (-(p.get("priority") or 0), 0 if p.get("company") else 1, p.get("name") or "")
	)
	for candidate in candidates:
		condition = (candidate.get("condition") or "").strip()
		if not condition or condition_holds(condition):
			return candidate
	return None


def next_state(action, level, level_count, approvals, min_approvals):
	"""(status, level) after `action` on 1-based `level`; `approvals` already counts this action."""
	if action == REJECT:
		return REJECTED, level
	if action == RETURN:
		return RETURNED, level
	if action != APPROVE:
		raise ValueError(f"Unknown approval action {action!r}")
	if approvals < max(min_approvals or 1, 1):
		return PENDING, level
	if level < level_count:
		return PENDING, level + 1
	return APPROVED, level


def requires_comment(action):
	return action in (REJECT, RETURN)


def approving_principals(actions, cycle, level):
	"""Users whose approval counts on `level` of `cycle`: the approver, or whom they acted for."""
	return {
		a.get("on_behalf_of") or a.get("approver")
		for a in actions
		if a.get("action") == APPROVE and a.get("cycle") == cycle and a.get("level") == level
	}


def due_at(started_at, sla_hours):
	"""Calendar-hour deadline of a level, or None when the level has no SLA."""
	if not sla_hours or sla_hours <= 0:
		return None
	return get_datetime(started_at) + timedelta(hours=float(sla_hours))


def needs_escalation(status, due, escalated, now):
	return status == PENDING and bool(due) and not escalated and get_datetime(now) > get_datetime(due)


def delegation_covers(from_date, to_date, document_types, doctype, on_date):
	"""True if a delegation (inclusive window, optional doctype list) applies to `doctype` on `on_date`."""
	in_window = getdate(from_date) <= getdate(on_date) <= getdate(to_date)
	return in_window and (not document_types or doctype in document_types)


def parse_fieldnames(text):
	return [f for f in re.split(r"[\s,]+", text or "") if f]


def disallowed_changes(changed, editable):
	return sorted(set(changed) - set(editable))
