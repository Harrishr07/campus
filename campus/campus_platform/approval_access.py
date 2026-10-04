"""M17-03 Who may read Approval Requests, and the requests waiting on a user."""

import frappe
from frappe.core.doctype.user_permission.user_permission import get_user_permissions
from frappe.utils import get_datetime, now_datetime, today

from campus.campus_platform import approval_rules as rules
from campus.campus_platform.approval_engine import acting_capacity


def pending_approvals(user, company=None):
	"""Pending requests the user can act on now (as approver or delegate), oldest due first."""
	candidates = _candidate_requests(user, company)
	rows = []
	for name in candidates:
		request = frappe.get_doc("Approval Request", name)
		allowed, on_behalf_of = acting_capacity(request, user)
		if allowed:
			rows.append(_row(request, on_behalf_of))
	return sorted(rows, key=lambda r: (r["due_at"] is None, r["due_at"] or 0))


def _candidate_requests(user, company):
	people = [user, *_delegating_users(user)]
	request = frappe.qb.DocType("Approval Request")
	approver = frappe.qb.DocType("Approval Request Approver")
	query = (
		frappe.qb.from_(request)
		.join(approver)
		.on(
			(approver.parent == request.name)
			& (approver.cycle == request.cycle)
			& (approver.level == request.current_level)
		)
		.select(request.name)
		.distinct()
		.where(request.status == rules.PENDING)
		.where(approver.user.isin(people))
	)
	companies = _permitted_companies(user)
	if company:
		query = query.where(request.company == company)
	if companies is not None:
		query = query.where(request.company.isin(companies or [""]))
	return [row[0] for row in query.run()]


def _delegating_users(user):
	return frappe.get_all(
		"Approval Delegation",
		filters={"delegate": user, "from_date": ["<=", today()], "to_date": [">=", today()]},
		pluck="user",
		distinct=True,
	)


def _permitted_companies(user):
	"""Companies the user is restricted to by User Permission, or None when unrestricted."""
	restricted = get_user_permissions(user).get("Company")
	return [p["doc"] for p in restricted] if restricted else None


def _row(request, on_behalf_of):
	return {
		"request": request.name,
		"reference_doctype": request.reference_doctype,
		"reference_name": request.reference_name,
		"company": request.company,
		"current_level": request.current_level,
		"due_at": request.due_at and get_datetime(request.due_at),
		"overdue": bool(request.due_at and get_datetime(request.due_at) < now_datetime()),
		"on_behalf_of": on_behalf_of,
	}


def _unrestricted(user):
	return user == "Administrator" or "System Manager" in frappe.get_roles(user)


def get_permission_query_conditions(user=None):
	"""List filter: requests the user raised, is or was an approver of, or holds a live delegation for."""
	user = user or frappe.session.user
	if _unrestricted(user):
		return ""
	user_sql, today_sql = frappe.db.escape(user), frappe.db.escape(today())
	return f"""(`tabApproval Request`.requested_by = {user_sql}
		or `tabApproval Request`.name in (
			select a.parent from `tabApproval Request Approver` a
			left join `tabApproval Delegation` d
				on d.user = a.user and d.delegate = {user_sql}
				and d.from_date <= {today_sql} and d.to_date >= {today_sql}
			where a.user = {user_sql} or d.name is not null))"""


def has_permission(doc, ptype=None, user=None):
	user = user or frappe.session.user
	if _unrestricted(user) or user == doc.requested_by:
		return True
	approvers = {row.user for row in doc.approvers}
	return user in approvers or bool(set(_delegating_users(user)) & approvers)
