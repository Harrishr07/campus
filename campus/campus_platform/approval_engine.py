"""M17-03 Approval engine core: start a request, act on a level, resolve who may act.

A Returned request is reused: requesting approval again starts a new cycle on the same request (the
policy is re-selected, so changed values pick the right policy). A Rejected request is closed; a new
request is created if the owner asks again.

Separation of duties: the requester and the document owner (and any users the document excludes through
`approval_excluded_users()`) are never approvers, and may not act on their own request, even as a delegate.

Approvers of a level are resolved when the level becomes current. If a later level resolves too few
approvers, the approval that would move the request there fails with that error and the request stays
on the earlier level until the policy, position holders or roles are fixed (no level is skipped).
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, today

from campus.campus_platform import approval_rules as rules
from campus.campus_platform.approver_resolution import document_company, resolve_approvers
from campus.campus_platform.notify import notify


def start_request(doc, policy=None, level=1):
	"""Start approval of a draft under `policy` (an Approval Policy doc), else under the policy matching its values,
	at 1-based `level` (first by default)."""
	if doc.docstatus != 0:
		frappe.throw(_("Only a draft can be sent for approval."))
	frappe.db.get_value(doc.doctype, doc.name, "name", for_update=True)  # one request at a time per doc
	latest = latest_request(doc)
	if latest and latest.status in (rules.PENDING, rules.APPROVED):
		frappe.throw(_("{0} is already {1} in {2}.").format(doc.name, _(latest.status).lower(), latest.name))
	before_request = getattr(doc, "before_approval_request", None)
	if before_request:
		before_request()  # optional hook: a document may refuse a request that could never be approved
	policy = policy or find_policy(doc)
	if not policy:
		doc.flags.ignore_permissions = True
		doc.submit()
		return None
	request = _reusable_request(latest, doc)
	request.update(
		{"policy": policy.name, "company": document_company(doc), "requested_by": frappe.session.user}
	)
	request.status = rules.PENDING
	request.cycle = (request.cycle or 0) + 1
	add_action(request, rules.REQUEST, 0)
	start_level(request, policy, doc, level)
	request.save(ignore_permissions=True)
	return request


def _reusable_request(latest, doc):
	if latest and latest.status == rules.RETURNED:
		return frappe.get_doc("Approval Request", latest.name, for_update=True)
	return frappe.new_doc("Approval Request", reference_doctype=doc.doctype, reference_name=doc.name)


def act(request_name, action, comment=None):
	"""Record `action` by the session user on the current level and move the request on."""
	request = frappe.get_doc("Approval Request", request_name, for_update=True)
	if request.status != rules.PENDING:
		frappe.throw(_("{0} is {1}; it cannot be acted on.").format(request.name, _(request.status)))
	if rules.requires_comment(action) and not (comment or "").strip():
		frappe.throw(_("A comment is required to {0}.").format(_(action).lower()))
	doc = frappe.get_doc(request.reference_doctype, request.reference_name)
	frappe.has_permission(doc.doctype, "read", doc=doc, user=frappe.session.user, throw=True)
	on_behalf_of = acting_for(request, frappe.session.user)
	add_action(request, action, request.current_level, on_behalf_of=on_behalf_of, comment=comment)

	policy = frappe.get_doc("Approval Policy", request.policy)
	level = policy.levels[request.current_level - 1]
	principals = rules.approving_principals(_actions(request), request.cycle, request.current_level)
	status, next_level = rules.next_state(
		action, request.current_level, len(policy.levels), len(principals), level.min_approvals
	)
	request.status = status
	if status == rules.PENDING and next_level != request.current_level:
		start_level(request, policy, doc, next_level)
	request.save(ignore_permissions=True)
	if status == rules.APPROVED:
		run_final_action(policy, doc, request)
	if status != rules.PENDING:
		notify(
			[request.requested_by],
			_("{0} {1}: {2}").format(_(doc.doctype), doc.name, _(status)),
			comment,
			doc,
		)
	return request.status


def start_level(request, policy, doc, level_no):
	"""Make `level_no` current: resolve and store its approvers, set its deadline, notify them."""
	level = policy.levels[level_no - 1]
	excluded = requesters(request, doc)
	users = resolve_approvers(
		level.approver_type, level.approver, doc, level.scope_field, level.limit_to_company
	)
	users = [u for u in users if u not in excluded]
	needed = max(level.min_approvals or 1, 1)
	if len(users) < needed:
		frappe.throw(
			_(
				"Level {0} of approval policy {1} needs {2} approver(s) but {3} were found"
				" (the requester and document owner cannot approve)."
			).format(level_no, policy.name, needed, len(users))
		)
	request.current_level = level_no
	request.level_started_at = now_datetime()
	request.due_at = rules.due_at(request.level_started_at, level.sla_hours)
	request.escalated = 0
	for user in users:
		request.append(
			"approvers", {"cycle": request.cycle, "level": level_no, "user": user, "source": "Approver"}
		)
	subject = _("Approval needed: {0} {1}").format(_(doc.doctype), doc.name)
	notify(users, subject, _("Level {0}: {1}").format(level_no, level.title or level.approver_type), doc)


def run_final_action(policy, doc, request):
	if policy.on_final_action == "Set Field":
		doc.db_set(policy.final_field, policy.final_value)
	elif policy.on_final_action == "Call Service":
		frappe.get_attr(registered_final_action(policy.final_method))(doc, request)
	else:
		doc.flags.ignore_permissions = True
		doc.submit()


def registered_final_action(method):
	"""`method` if an app lists it in the `approval_final_actions` hook; throws otherwise."""
	if method not in frappe.get_hooks("approval_final_actions"):
		frappe.throw(
			_("{0} is not a registered approval final action (hook approval_final_actions).").format(
				frappe.bold(method)
			)
		)
	return method


def requesters(request, doc=None):
	"""Users who may not approve their own request: the requester, the document owner and any users the document
	names in an `approval_excluded_users()` method (e.g. a question paper's setters and editors)."""
	if not doc:
		try:
			doc = frappe.get_doc(request.reference_doctype, request.reference_name)
		except frappe.DoesNotExistError:
			frappe.clear_last_message()
			return {u for u in (request.requested_by,) if u}
	excluded = {request.requested_by, doc.owner}
	if hasattr(doc, "approval_excluded_users"):
		excluded |= set(doc.approval_excluded_users())
	return {u for u in excluded if u}


def add_action(request, action, level, on_behalf_of=None, comment=None, by=None):
	request.append(
		"actions",
		{
			"cycle": request.cycle,
			"level": level,
			"action": action,
			"approver": by or frappe.session.user,
			"on_behalf_of": on_behalf_of,
			"comment": comment,
			"timestamp": now_datetime(),
		},
	)


def acting_for(request, user):
	"""None when `user` acts as a current approver; the approver they stand in for as a delegate.

	Throws PermissionError for anyone else."""
	if user in requesters(request):
		frappe.throw(_("You cannot act on your own approval request."), frappe.PermissionError)
	allowed, principal = acting_capacity(request, user)
	if allowed:
		return principal
	if user in current_approvers(request):
		frappe.throw(_("You have already approved this level."))
	frappe.throw(
		_("You are not an approver of {0} at this level.").format(request.name), frappe.PermissionError
	)


def acting_capacity(request, user):
	"""(may act, on behalf of) for `user` on the current level; never throws."""
	excluded = requesters(request)
	if user in excluded:
		return False, None
	current = [u for u in current_approvers(request) if u not in excluded]
	done = rules.approving_principals(_actions(request), request.cycle, request.current_level)
	if user in current and user not in done:
		return True, None
	principal = delegator_for(user, [u for u in current if u not in done], request.reference_doctype)
	return bool(principal), principal


def delegator_for(delegate, users, doctype, on_date=None):
	"""The first of `users` whose delegation to `delegate` covers `doctype` on `on_date`."""
	on_date = on_date or today()
	if not users:
		return None
	delegations = frappe.get_all(
		"Approval Delegation",
		filters={
			"delegate": delegate,
			"user": ["in", users],
			"from_date": ["<=", on_date],
			"to_date": [">=", on_date],
		},
		fields=["name", "user", "from_date", "to_date"],
		order_by="from_date asc",
	)
	for row in delegations:
		types = frappe.get_all(
			"Approval Delegation Document Type", filters={"parent": row.name}, pluck="document_type"
		)
		if rules.delegation_covers(row.from_date, row.to_date, types, doctype, on_date):
			return row.user
	return None


def current_approvers(request):
	return [
		row.user
		for row in request.approvers
		if row.cycle == request.cycle and row.level == request.current_level
	]


def _actions(request):
	return [row.as_dict() for row in request.actions]


def find_policy(doc):
	policies = frappe.get_all(
		"Approval Policy",
		filters={"document_type": doc.doctype, "enabled": 1},
		fields=["name", "priority", "company", "condition"],
	)
	context = frappe._dict(doc.as_dict())  # a plain dict: conditions cannot call document methods
	found = rules.select_policy(
		policies, document_company(doc), lambda c: bool(frappe.safe_eval(c, None, {"doc": context}))
	)
	return frappe.get_doc("Approval Policy", found.name) if found else None


def latest_request(doc):
	return frappe.db.get_value(
		"Approval Request",
		{"reference_doctype": doc.doctype, "reference_name": doc.name},
		["name", "status"],
		order_by="creation desc",
		as_dict=True,
	)
