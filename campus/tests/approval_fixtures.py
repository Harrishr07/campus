"""Shared fixtures for the M17-03 approval engine tests (test doctype: Approval Test Document)."""

import frappe
from frappe.utils import add_days, today

from campus.campus_platform.positions import ensure_seed_positions
from campus.tests.factories import make_company, make_user

DOCTYPE = "Approval Test Document"
COLLEGE = "Approval Test College"
OTHER_COLLEGE = "Approval Other College"
HOD = "apr-hod@example.com"
DEAN = "apr-dean@example.com"
PRINCIPAL = "apr-principal@example.com"
DELEGATE = "apr-delegate@example.com"
OUTSIDER = "apr-outsider@example.com"
ESCALATOR = "apr-escalator@example.com"
CLERK = "apr-clerk@example.com"
USERS = (HOD, DEAN, PRINCIPAL, DELEGATE, OUTSIDER, ESCALATOR, CLERK)
BIG = "APR Test Three Level"
SMALL = "APR Test Single Level"


def setup_world():
	"""Companies, users, department and position holders. Idempotent; safe to commit."""
	ensure_seed_positions()
	make_company(COLLEGE, "APTC")
	make_company(OTHER_COLLEGE, "APOC")
	for user in USERS:
		make_user(user, [COLLEGE])
	department = make_department("Approval Test CSE", COLLEGE)
	for code, user, scope in (
		("HOD", HOD, department),
		("DEAN-ACADEMICS", DEAN, COLLEGE),
		("PRINCIPAL", PRINCIPAL, COLLEGE),
	):
		if not frappe.db.exists("Position Holder", {"position": code, "scope_value": scope}):
			frappe.get_doc(
				{
					"doctype": "Position Holder",
					"position": code,
					"scope_value": scope,
					"user": user,
					"from_date": add_days(today(), -30),
				}
			).insert()
	return department


def make_department(name, company):
	existing = frappe.db.get_value("Department", {"department_name": name, "company": company})
	if existing:
		return existing
	return (
		frappe.get_doc({"doctype": "Department", "department_name": name, "company": company}).insert().name
	)


def clear_approval_data():
	"""Remove the documents, requests, policies and delegations a previous test left behind."""
	frappe.db.delete("Approval Request Approver", {"parent": ["in", _requests()]})
	frappe.db.delete("Approval Action", {"parent": ["in", _requests()]})
	frappe.db.delete("Approval Request", {"reference_doctype": DOCTYPE})
	frappe.db.delete(DOCTYPE)
	frappe.db.delete("Approval Level", {"parenttype": "Approval Policy", "parent": ["like", "APR Test%"]})
	frappe.db.delete("Approval Policy", {"name": ["like", "APR Test%"]})
	frappe.db.delete("Approval Delegation Document Type", {"parent": ["in", _delegations()]})
	frappe.db.delete("Approval Delegation", {"name": ["in", _delegations()]})
	frappe.db.delete("Notification Log", {"document_type": DOCTYPE})


def _requests():
	return frappe.get_all("Approval Request", filters={"reference_doctype": DOCTYPE}, pluck="name") or [""]


def _delegations():
	return frappe.get_all("Approval Delegation", filters={"user": ["in", USERS]}, pluck="name") or [""]


def level(approver_type, approver=None, **extra):
	return {"approver_type": approver_type, "approver": approver, **extra}


def make_policy(name, levels, condition=None, priority=0, company=None, **extra):
	return frappe.get_doc(
		{
			"doctype": "Approval Policy",
			"policy_name": name,
			"document_type": DOCTYPE,
			"company": company,
			"condition": condition,
			"priority": priority,
			"levels": levels,
			**extra,
		}
	).insert()


def make_standard_policies():
	"""HOD -> Dean -> Principal above 50000; a single Clerk level above 1000; nothing below."""
	make_policy(
		BIG,
		[
			level(
				"Position",
				"HOD",
				title="HOD",
				scope_field="department",
				sla_hours=24,
				escalate_to_type="User",
				escalate_to=ESCALATOR,
				can_edit_fields="notes",
			),
			level("Position", "DEAN-ACADEMICS", title="Dean", scope_field="company"),
			level("Position", "PRINCIPAL", title="Principal", scope_field="company"),
		],
		condition="doc.amount > 50000",
		priority=10,
	)
	make_policy(SMALL, [level("User", CLERK)], condition="doc.amount > 1000", priority=5)


def make_document(amount, department, company=COLLEGE, **extra):
	return frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"title": f"Spend {amount}",
			"amount": amount,
			"company": company,
			"department": department,
			**extra,
		}
	).insert()


def actions_of(request):
	return [(a.action, a.level, a.approver, a.on_behalf_of) for a in request.actions]


def notified(user):
	return frappe.get_all(
		"Notification Log", filters={"for_user": user, "document_type": DOCTYPE}, pluck="subject"
	)
