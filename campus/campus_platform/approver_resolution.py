"""M17-03 Resolve the users behind an approval level's approver (or escalation) spec for a document."""

import frappe
from frappe import _

from campus.campus_platform.positions import resolve_position


def document_company(doc):
	return doc.get("company") or doc.get("oc_company")


def resolve_approvers(approver_type, approver, doc, scope_field=None, limit_to_company=False):
	"""Enabled user ids for one approver spec, in a stable order, without duplicates."""
	resolver = RESOLVERS.get(approver_type)
	if not resolver:
		frappe.throw(_("Unknown approver type {0}.").format(frappe.bold(approver_type)))
	users = resolver(approver, doc, scope_field=scope_field, limit_to_company=limit_to_company)
	return _enabled(list(dict.fromkeys(u for u in users if u)))


def _by_role(role, doc, limit_to_company=False, **kwargs):
	users = frappe.get_all(
		"Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent", order_by="parent asc"
	)
	if limit_to_company and users:
		permitted = set(
			frappe.get_all(
				"User Permission",
				filters={"allow": "Company", "for_value": document_company(doc), "user": ["in", users]},
				pluck="user",
			)
		)
		users = [u for u in users if u in permitted]
	return users


def _by_position(code, doc, scope_field=None, **kwargs):
	scope = doc.get(scope_field) if scope_field else None
	if scope_field and not scope:
		frappe.throw(
			_("Field {0} is needed to find the {1} approver.").format(frappe.bold(scope_field), code)
		)
	return resolve_position(code, scope)


def _by_user(user, doc, **kwargs):
	return [user]


def _by_field(fieldname, doc, **kwargs):
	return [doc.get(fieldname)]


def _by_reporting_manager(fieldname, doc, **kwargs):
	employee = _employee_of(fieldname, doc)
	manager = employee and frappe.db.get_value("Employee", employee, "reports_to")
	return [frappe.db.get_value("Employee", manager, "user_id")] if manager else []


def _employee_of(fieldname, doc):
	"""Employee named by `fieldname` (an Employee link or a user field), else the owner's Employee."""
	value = doc.get(fieldname) if fieldname else doc.owner
	if fieldname and doc.meta.get_options(fieldname) == "Employee":
		return value
	return value and frappe.db.get_value("Employee", {"user_id": value, "status": "Active"}, "name")


def _enabled(users):
	if not users:
		return []
	enabled = set(frappe.get_all("User", filters={"name": ["in", users], "enabled": 1}, pluck="name"))
	return [u for u in users if u in enabled and u != "Guest"]


RESOLVERS = {
	"Role": _by_role,
	"Position": _by_position,
	"User": _by_user,
	"Field": _by_field,
	"Reporting Manager": _by_reporting_manager,
}
