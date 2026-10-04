"""M17-02 Positions: resolution by date, overlap rule, role sync and seed data.

Role sync rule: a Position Holder that grants its position's role to a user who did not already
have it is marked `role_granted`. Only marked holdings ever remove a role, so roles assigned by
hand are never touched. When a marked holding ends, the role is removed unless the user has another
active holding whose position grants the same role; then the mark moves to that holding.
"""

import frappe
from frappe.utils import getdate, today

SCOPE_DOCTYPES = {
	"Institution": "Company",
	"Department": "Department",
	"Student Group": "Student Group",
	"Hostel": None,  # no Hostel doctype yet
	"Body": None,
	"Lab": None,
}

# code, title, scope type, role, single holder
SEED_POSITIONS = [
	("PRINCIPAL", "Principal", "Institution", "Principal", 1),
	("DEAN-ACADEMICS", "Dean Academics", "Institution", "Dean Academics", 1),
	("DEAN-STUDENT-AFFAIRS", "Dean Student Affairs", "Institution", "Dean Student Affairs", 1),
	("HOD", "HOD", "Department", "HOD", 1),
	("CLASS-ADVISOR", "Class Advisor", "Student Group", "Class Advisor", 1),
	("MENTOR", "Mentor", "Student Group", "Mentor", 0),
	("COE", "COE", "Institution", "COE", 1),
	("IQAC-COORDINATOR", "IQAC Coordinator", "Institution", "IQAC Coordinator", 1),
	("WARDEN", "Warden", "Hostel", "Warden", 1),
]


def resolve_position(code, scope=None, on_date=None):
	"""User ids holding position `code` on `on_date` (default today), oldest holding first.

	`scope` is the scope value (company, department, student group...); None means any scope.
	"""
	on_date = getdate(on_date or today())
	filters = {"position": code, "from_date": ["<=", on_date], "user": ["is", "set"]}
	if scope is not None:
		filters["scope_value"] = scope
	rows = frappe.get_all(
		"Position Holder",
		filters=filters,
		or_filters=[["to_date", "is", "not set"], ["to_date", ">=", on_date]],
		fields=["user"],
		order_by="from_date asc, creation asc",
	)
	return list(dict.fromkeys(row.user for row in rows))


def date_ranges_overlap(from_a, to_a, from_b, to_b):
	"""Inclusive date ranges; a missing end date is open-ended."""
	starts_before_b_ends = not to_b or getdate(from_a) <= getdate(to_b)
	ends_after_b_starts = not to_a or getdate(to_a) >= getdate(from_b)
	return starts_before_b_ends and ends_after_b_starts


def find_overlapping_holding(holder):
	"""Name of another holding of the same position and scope overlapping `holder`, or None."""
	others = frappe.get_all(
		"Position Holder",
		filters={
			"position": holder.position,
			"scope_value": holder.scope_value or ["is", "not set"],
			"name": ["!=", holder.name or ""],
		},
		fields=["name", "from_date", "to_date"],
	)
	for other in others:
		if date_ranges_overlap(holder.from_date, holder.to_date, other.from_date, other.to_date):
			return other.name


def active_holdings(user, on_date=None):
	"""Holdings of `user` active on `on_date`, with the role their position grants."""
	on_date = getdate(on_date or today())
	rows = frappe.get_all(
		"Position Holder",
		filters={"user": user, "from_date": ["<=", on_date]},
		or_filters=[["to_date", "is", "not set"], ["to_date", ">=", on_date]],
		fields=["name", "position", "role_granted"],
	)
	for row in rows:
		row.role = frappe.db.get_value("Position", row.position, "role")
	return [row for row in rows if row.role]


def sync_user_roles(user, ignore_holding=None):
	"""Make `user`'s position roles match their holdings today (see module docstring)."""
	active = [h for h in active_holdings(user) if h.name != ignore_holding]
	active_names = {h.name for h in active}
	for holding in _marked_holdings(user):
		if holding.name not in active_names:
			_release(user, holding, active)
	for holding in active:
		if not holding.role_granted and not _has_role(user, holding.role):
			_set_role_granted(holding.name, 1)
			_change_roles(user, add=holding.role)


def release_reassigned_holding(old_user, holding):
	"""`holding` moved to another user: take back the role it had granted to `old_user`."""
	if holding.role_granted:
		role = frappe.db.get_value("Position", holding.position, "role")
		_release(old_user, frappe._dict(name=holding.name, role=role), active_holdings(old_user))
		holding.role_granted = 0


def _marked_holdings(user):
	holdings = frappe.get_all("Position Holder", filters={"user": user, "role_granted": 1}, fields=["name", "position"])
	for holding in holdings:
		holding.role = frappe.db.get_value("Position", holding.position, "role")
	return holdings


def _release(user, ended, active):
	_set_role_granted(ended.name, 0)
	successor = next((h for h in active if h.role == ended.role and not h.role_granted), None)
	if successor:
		_set_role_granted(successor.name, 1)
		successor.role_granted = 1
	elif ended.role and not any(h.role == ended.role for h in active):
		_change_roles(user, remove=ended.role)


def _set_role_granted(holding, value):
	frappe.db.set_value("Position Holder", holding, "role_granted", value, update_modified=False)


def _has_role(user, role):
	return bool(frappe.db.exists("Has Role", {"parent": user, "parenttype": "User", "role": role}))


def _change_roles(user, add=None, remove=None):
	doc = frappe.get_doc("User", user)
	doc.flags.ignore_permissions = True
	if add:
		doc.add_roles(add)
	if remove:
		doc.remove_roles(remove)


def sync_all_roles():
	"""Daily job: grant roles for holdings that started and revoke those whose holding ended."""
	users = frappe.get_all("Position Holder", filters={"user": ["is", "set"]}, pluck="user", distinct=True)
	for user in users:
		sync_user_roles(user)


def ensure_seed_positions():
	"""Create the standard positions and their roles if missing. Idempotent; never edits existing ones."""
	for code, title, scope_type, role, single_holder in SEED_POSITIONS:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)
		if not frappe.db.exists("Position", code):
			frappe.get_doc(
				{
					"doctype": "Position",
					"code": code,
					"title": title,
					"scope_type": scope_type,
					"role": role,
					"single_holder": single_holder,
				}
			).insert(ignore_permissions=True)
