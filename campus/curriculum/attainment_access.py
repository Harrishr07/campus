"""M03-03 Who reads and manages attainment runs (permission hooks of CO and PO Attainment Run).

- System Manager and Dean Academics read and manage every run.
- COE and IQAC Coordinator read every run (the college's attainment figures).
- An HOD reads and manages (compute, submit, cancel, amend) the runs of their department's programmes: a CO run of an
  offering of such a programme, a PO run of such a programme. Department = Program.department, the HOD seat from
  Position Holder (examinations.api.held_scopes), as for mark sheets.
- An instructor reads the CO runs of the offerings they teach.
Per-student marks sit in the CO run's input snapshot at permlevel 1 (System Manager, COE, Dean Academics only), so the
readers above see the per-CO figures and the questions used, never a student's marks.
"""

import frappe

READ_TYPES = ("read", "print", "email", "export", "report", "select")
MANAGE_ALL_ROLES = ("System Manager", "Dean Academics")
READ_ALL_ROLES = (*MANAGE_ALL_ROLES, "COE", "IQAC Coordinator")
HOD_POSITION = "HOD"


def has_any_role(user, roles):
	return user == "Administrator" or bool(set(roles) & set(frappe.get_roles(user)))


def managed_programs(user):
	"""The programmes whose runs `user` manages: None for all (System Manager, Dean Academics), else those of the
	departments the user holds the HOD seat of."""
	from campus.examinations.api import held_scopes

	if has_any_role(user, MANAGE_ALL_ROLES):
		return None
	departments = held_scopes(user, HOD_POSITION)
	return frappe.get_all("Program", {"department": ["in", departments]}, pluck="name") if departments else []


def taught_offerings(user):
	from campus.examinations.api import instructed_offerings

	return [o for o in instructed_offerings(user) if o]


def in_list(values):
	return ", ".join(frappe.db.escape(v) for v in values) or "''"


def co_run_query(user=None):
	user = user or frappe.session.user
	if has_any_role(user, READ_ALL_ROLES):
		return ""
	return "(`tabCO Attainment Run`.program in ({0}) or `tabCO Attainment Run`.course_offering in ({1}))".format(
		in_list(managed_programs(user)), in_list(taught_offerings(user))
	)


def co_run_has_permission(doc, ptype=None, user=None):
	user = user or frappe.session.user
	if has_any_role(user, MANAGE_ALL_ROLES) or (ptype in READ_TYPES and has_any_role(user, READ_ALL_ROLES)):
		return True
	program = doc.get("program") or frappe.db.get_value("Student Group", doc.get("course_offering"), "program")
	if program and program in managed_programs(user):
		return True
	return ptype in READ_TYPES and doc.get("course_offering") in taught_offerings(user)


def po_run_query(user=None):
	user = user or frappe.session.user
	if has_any_role(user, READ_ALL_ROLES):
		return ""
	return "`tabPO Attainment Run`.program in ({0})".format(in_list(managed_programs(user)))


def po_run_has_permission(doc, ptype=None, user=None):
	user = user or frappe.session.user
	if has_any_role(user, MANAGE_ALL_ROLES) or (ptype in READ_TYPES and has_any_role(user, READ_ALL_ROLES)):
		return True
	return bool(doc.get("program")) and doc.program in managed_programs(user)
