"""M16-02 Audience resolution: the people an Audience Rule addresses, as `api.send` recipients.

Rule types
  Role                  enabled users holding the role (and permitted for the rule's company)
  Student Group         active students of the group
  Program and Semester  students with a submitted Program Enrollment in the program for the current
                        academic year; the semester filter uses Student `oc_current_semester` when that
                        field exists and is ignored otherwise (the field arrives with the semester model)
  Department            active employees of the department
  Guardians of          guardians of the students selected by one of the student-based types above
  Hostel, Route         declared but not available until Phase 4 (the records do not exist yet)

Students are always limited to the rule's company. Resolution returns "Doctype:name" strings
(JSON-safe, so they can be bulk-run items), in a stable order, without duplicates.
"""

import frappe
from frappe import _

ROLE = "Role"
STUDENT_GROUP = "Student Group"
PROGRAM_SEMESTER = "Program and Semester"
DEPARTMENT = "Department"
GUARDIANS_OF = "Guardians of"
HOSTEL = "Hostel"
ROUTE = "Route"

STUDENT_BASED = (STUDENT_GROUP, PROGRAM_SEMESTER)
UNAVAILABLE = (HOSTEL, ROUTE)
SEMESTER_FIELD = "oc_current_semester"
NON_PEOPLE_USERS = ("Administrator", "Guest")


def resolve(rule):
	"""Recipients ("Doctype:name") of an Audience Rule document or name."""
	rule = _rule(rule)
	ensure_available(rule)
	if rule.rule_type == ROLE:
		return _users_with_role(rule)
	if rule.rule_type == DEPARTMENT:
		return _prefixed("Employee", _employees(rule))
	if rule.rule_type == GUARDIANS_OF:
		return _prefixed("Guardian", _guardians_of(_students(rule, rule.guardians_of)))
	return _prefixed("Student", _students(rule, rule.rule_type))


def ensure_available(rule):
	"""Throw for Hostel/Route rules (also as the basis of "Guardians of"): not available until Phase 4."""
	basis = rule.guardians_of if rule.rule_type == GUARDIANS_OF else rule.rule_type
	if basis in UNAVAILABLE:
		_unavailable(basis)


def count(rule):
	return len(resolve(rule))


def _rule(rule):
	return rule if isinstance(rule, frappe.model.document.Document) else frappe.get_doc("Audience Rule", rule)


def _unavailable(rule_type):
	frappe.throw(
		_(
			"Audience rules based on {0} are not available until Phase 4, when hostel and transport data arrive."
		).format(_(rule_type)),
		title=_("Not Available Yet"),
	)


def _prefixed(doctype, names):
	return [f"{doctype}:{name}" for name in names]


def _students(rule, basis):
	if basis == STUDENT_GROUP:
		names = frappe.get_all(
			"Student Group Student",
			filters={"parent": rule.student_group, "parenttype": "Student Group", "active": 1},
			pluck="student",
			order_by="idx",
		)
	elif basis == PROGRAM_SEMESTER:
		names = _enrolled_students(rule)
	else:
		frappe.throw(_("{0} cannot be used to select students.").format(_(basis or "")))
	return _active_students_of_company(names, rule, semester=basis == PROGRAM_SEMESTER)


def _enrolled_students(rule):
	filters = {"program": rule.program, "docstatus": 1}
	academic_year = frappe.db.get_single_value("Education Settings", "current_academic_year")
	if academic_year:
		filters["academic_year"] = academic_year
	return frappe.get_all("Program Enrollment", filters=filters, pluck="student", distinct=True)


def _active_students_of_company(names, rule, semester=False):
	if not names:
		return []
	filters = {"name": ["in", list(dict.fromkeys(names))], "enabled": 1, "oc_company": rule.company}
	if semester and rule.semester and frappe.get_meta("Student").has_field(SEMESTER_FIELD):
		filters[SEMESTER_FIELD] = rule.semester
	return sorted(frappe.get_all("Student", filters=filters, pluck="name"))


def _guardians_of(students):
	if not students:
		return []
	names = frappe.get_all(
		"Student Guardian",
		filters={"parent": ["in", students], "parenttype": "Student"},
		pluck="guardian",
		distinct=True,
	)
	return sorted(name for name in names if name)


def _employees(rule):
	return sorted(
		frappe.get_all(
			"Employee",
			filters={"department": rule.department, "company": rule.company, "status": "Active"},
			pluck="name",
		)
	)


def _users_with_role(rule):
	holders = frappe.get_all(
		"Has Role", filters={"role": rule.role, "parenttype": "User"}, pluck="parent", distinct=True
	)
	enabled = frappe.get_all("User", filters={"name": ["in", holders or [""]], "enabled": 1}, pluck="name")
	permitted = _users_permitted_for(rule.company, enabled)
	return _prefixed("User", sorted(u for u in permitted if u not in NON_PEOPLE_USERS))


def _users_permitted_for(company, users):
	"""Users with no Company restriction, or restricted to include `company`."""
	rows = frappe.get_all(
		"User Permission",
		filters={"allow": "Company", "user": ["in", users or [""]]},
		fields=["user", "for_value"],
	)
	restricted = {r.user for r in rows}
	allowed = {r.user for r in rows if r.for_value == company}
	return [u for u in users if u not in restricted or u in allowed]


def keys_for_user(user):
	"""Every recipient key a user answers to: themself and the Student/Guardian/Employee records linked to them."""
	keys = {f"User:{user}"}
	for doctype, field in (("Student", "user"), ("Guardian", "user"), ("Employee", "user_id")):
		keys.update(
			f"{doctype}:{name}" for name in frappe.get_all(doctype, filters={field: user}, pluck="name")
		)
	return keys


def includes_user(rule, user):
	"""Whether `user` is in the rule's audience (through any record linked to them)."""
	return bool(keys_for_user(user) & set(resolve(rule)))


def users_of(keys):
	"""{key: (user, display name)} for recipient keys, one query per doctype; users may be None."""
	from campus.campus_messaging.recipients import SOURCES

	by_doctype = {}
	for key in keys:
		doctype, _sep, name = key.partition(":")
		by_doctype.setdefault(doctype, []).append(name)
	result = {}
	for doctype, names in by_doctype.items():
		_emails, _mobiles, user_field, _language, name_field = SOURCES[doctype]
		for row in frappe.get_all(
			doctype, filters={"name": ["in", names]}, fields=["name", user_field, name_field]
		):
			result[f"{doctype}:{row.name}"] = (row[user_field], row[name_field] or row.name)
	return result
