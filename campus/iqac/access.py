"""M01-02 Who may touch a cycle's Metric Values.

IQAC Coordinators and System Managers work on every value of the companies they are permitted for (Company User
Permissions do that part). A criterion owner (a row of the cycle's owners) answers only the values under their
criterion; the Principal reads. Frappe lets this module only narrow what the role permissions grant.
"""

import frappe

ROLES = ("IQAC Coordinator", "System Manager")
OWNER_ROLE = "IQAC Criterion Owner"
READERS = (*ROLES, "Principal")
OWNER_ROW = "Accreditation Cycle Owner"


def has_role(user, roles):
	return bool(set(frappe.get_roles(user)) & set(roles))


def root_criterion(node):
	"""The root (Criterion or Extended Profile) of the node's branch."""
	parent = frappe.db.get_value("Framework Node", node, "parent_node")
	while parent:
		node, parent = parent, frappe.db.get_value("Framework Node", parent, "parent_node")
	return node


def owns(user, cycle, node):
	return bool(
		frappe.db.exists(
			OWNER_ROW,
			{
				"parent": cycle,
				"parenttype": "Accreditation Cycle",
				"user": user,
				"criterion": root_criterion(node),
			},
		)
	)


def may_edit(user, cycle, node):
	"""True for IQAC staff, and for the owner of the criterion `node` sits under."""
	return has_role(user, ROLES) or owns(user, cycle, node)


def has_permission(doc, ptype=None, user=None):
	"""Metric Value hook: a criterion owner is refused the values of other criteria."""
	user = user or frappe.session.user
	if has_role(user, READERS) or not (doc.cycle and doc.node):
		return True
	return owns(user, doc.cycle, doc.node)


def permission_query(user=None):
	"""Metric Value list condition: a criterion owner sees only the values under their criteria."""
	user = user or frappe.session.user
	if has_role(user, READERS):
		return ""
	rows = frappe.get_all(
		OWNER_ROW, {"parenttype": "Accreditation Cycle", "user": user}, ["parent", "criterion"]
	)
	conditions = []
	for row in rows:
		framework, code = frappe.db.get_value("Framework Node", row.criterion, ["framework", "code"])
		nodes = frappe.get_all(
			"Framework Node", {"framework": framework, "code": ["like", f"{code}.%"]}, pluck="name"
		)
		if nodes:
			conditions.append(
				f"(`tabMetric Value`.cycle = {frappe.db.escape(row.parent)} and `tabMetric Value`.node in ({', '.join(frappe.db.escape(n) for n in nodes)}))"
			)
	return f"({' or '.join(conditions)})" if conditions else "1=0"


def override_has_permission(doc, ptype=None, user=None):
	"""Metric Override hook: IQAC staff and the Principal see all; a criterion owner only the overrides under their criteria."""
	user = user or frappe.session.user
	if has_role(user, READERS):
		return True
	values = (
		frappe.db.get_value("Metric Value", doc.metric_value, ["cycle", "node"], as_dict=True)
		if doc.metric_value
		else None
	)
	return bool(values and owns(user, values.cycle, values.node))


def override_permission_query(user=None):
	"""Metric Override list condition: the overrides of the Metric Values the user may see."""
	user = user or frappe.session.user
	if has_role(user, READERS):
		return ""
	return f"`tabMetric Override`.metric_value in (select name from `tabMetric Value` where {permission_query(user)})"
