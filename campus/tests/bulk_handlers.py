"""Handlers for the bulk runner tests (P1-T09). Side effects are ToDo rows described by the item key."""

import frappe

MARK = "bulk-test::"
state = {"crash_after": None, "calls": 0}


class SimulatedCrash(BaseException):
	"""Stands in for a killed worker: not an Exception, so the runner's per-item handler cannot swallow it."""


def record(item, run):
	frappe.get_doc({"doctype": "ToDo", "description": f"{MARK}{item}"}).insert(ignore_permissions=True)


def record_or_crash(item, run):
	state["calls"] += 1
	if state["crash_after"] is not None and state["calls"] > state["crash_after"]:
		raise SimulatedCrash
	record(item, run)


def record_unless_odd(item, run):
	"""Fails every odd item after having written its side effect, to prove the write is rolled back."""
	record(item, run)
	if item % 2:
		frappe.throw(f"odd item {item}")


def record_with_parameter(item, run):
	record(f"{run.get_parameters()['prefix']}-{item}", run)


def key_by_id(item):
	return f"id-{item['id']}"


def record_dict(item, run):
	record(item["id"], run)


def commit_in_handler(item, run):
	record(item, run)
	frappe.db.commit()


def commit_then_fail(item, run):
	frappe.db.commit()
	frappe.throw("after commit")


def record_session_user(item, run):
	record(f"{item}@{frappe.session.user}", run)


def todo_count(prefix=""):
	return frappe.db.count("ToDo", {"description": ["like", f"{MARK}{prefix}%"]})


def cleanup():
	frappe.db.delete("ToDo", {"description": ["like", f"{MARK}%"]})
	frappe.db.delete("Bulk Run", {"run_type": ["like", "test-%"]})
	frappe.db.commit()
