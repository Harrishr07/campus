"""M01-02 / M01-03 Accreditation Cycle lifecycle: Collecting -> Validating -> IQAC Review -> Approved -> Submitted.

Collecting, Validating and IQAC Review are moved by `advance` / `reopen` (IQAC Coordinator, System Manager). Approved is
reached only by the final approval of the Accreditation Cycle, which submits it and locks every Metric Value
(`lock_values`); Submitted (to the regulator) follows. Criterion owners get a task each (`assign_tasks`).
"""

import frappe
from frappe import _

from campus.iqac.access import OWNER_ROLE, ROLES

CLOSED_CYCLE = ("Approved", "Submitted")
FORWARD = {"Collecting": "Validating", "Validating": "IQAC Review", "Approved": "Submitted"}
REOPENABLE = ("Validating", "IQAC Review")
ANSWER_NODES = ("Metric", "Sub-Metric", "Extended Profile")


def assert_open(cycle):
	"""Throw when the cycle's values are locked; `cycle` is an Accreditation Cycle doc."""
	if cycle.status in CLOSED_CYCLE:
		frappe.throw(_("{0} is {1}; its values are locked.").format(frappe.bold(cycle.name), _(cycle.status)))


def authorised(name):
	"""The cycle, row-locked, for an IQAC role holder permitted for its company."""
	frappe.only_for(ROLES)
	cycle = frappe.get_doc("Accreditation Cycle", name, for_update=True)
	cycle.check_permission("read")
	return cycle


def advance(name, comment=None):
	"""Collecting -> Validating -> IQAC Review, and Approved -> Submitted. Leaving Validating passes the validation gate:
	blocking failures stop it, warnings need a `comment`."""
	cycle = authorised(name)
	if cycle.status == "IQAC Review":
		frappe.throw(
			_("{0} is approved only through its approval; use Request Approval.").format(frappe.bold(name))
		)
	if cycle.status not in FORWARD:
		frappe.throw(_("{0} is {1}; there is no next step.").format(frappe.bold(name), _(cycle.status)))
	if cycle.status == "Validating":
		from campus.iqac.validation import gate

		gate(cycle, comment)
	move(cycle, FORWARD[cycle.status])


def reopen(name):
	"""Back to Collecting from Validating or IQAC Review (not once approved)."""
	cycle = authorised(name)
	if cycle.status not in REOPENABLE:
		frappe.throw(_("{0} is {1} and cannot be reopened.").format(frappe.bold(name), _(cycle.status)))
	move(cycle, "Collecting")


def move(cycle, status):
	cycle.flags.cycle_transition = True
	cycle.status = status
	cycle.save(ignore_permissions=True)


def lock_values(name):
	"""Lock every Metric Value of the cycle (on approval)."""
	frappe.db.set_value("Metric Value", {"cycle": name}, "status", "Locked")


def prepare_values(name):
	"""Draft Metric Values for the nodes answered by hand that have none yet; returns the new names."""
	cycle = authorised(name)
	assert_open(cycle)
	nodes = frappe.get_all(
		"Framework Node",
		{
			"framework": cycle.framework,
			"node_type": ["in", ANSWER_NODES],
			"formula": ["is", "not set"],
			"answer_type": ["is", "set"],
		},
		["name", "code"],
		order_by="code",
	)
	made = []
	for node in nodes:
		if frappe.db.exists("Metric Value", f"{name}-{node.code}"):
			continue
		made.append(
			frappe.get_doc({"doctype": "Metric Value", "cycle": name, "node": node.name})
			.insert(ignore_permissions=True)
			.name
		)
	return made


def assign_tasks(cycle):
	"""One ToDo per owner row (kept when the owner closes it); the owner gets the criterion owner role."""
	for row in cycle.owners:
		if row.todo and frappe.db.exists("ToDo", row.todo):
			continue
		grant_owner_role(row.user)
		title = frappe.db.get_value("Framework Node", row.criterion, "title")
		todo = frappe.get_doc(
			{
				"doctype": "ToDo", "allocated_to": row.user, "reference_type": cycle.doctype, "reference_name": cycle.name,
				"description": _("Provide the metric values of criterion {0} ({1}) for {2}.").format(row.criterion.rsplit("-", 1)[-1], title, cycle.name),
			}
		).insert(ignore_permissions=True)  # fmt: skip
		row.db_set("todo", todo.name)


def grant_owner_role(user):
	doc = frappe.get_doc("User", user)
	doc.flags.ignore_permissions = True
	doc.add_roles(OWNER_ROLE)
