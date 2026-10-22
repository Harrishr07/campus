"""M05-13 Who reads mentoring records (L-09).

Counselling Note: the author and the designated counsellor always; when not confidential also the student's current
mentor (Student.oc_mentor), Student Counsellors, the Principal and the HOD of the note's department. Only the author
edits. Only the student's current mentor or a Student Counsellor writes a note.
Parent Interaction: who recorded it, the student's current mentor and class advisor, the HOD of its department and
the office roles. The current mentor, the class advisor and the office roles edit; a follow-up owner must already be
one of its readers. No guardian or student role has any right on either. Both are never shared (a share would grant
what these rules refuse). Their Comments, Files and Connections counts: campus.campus_platform.restricted_records.
Company scope comes from the User Permissions on the `company` field.
"""

import frappe
from frappe import _

from campus.student_services.mentoring import (
	COUNSELLOR_ROLE,
	HOD_ROLE,
	INTERACTION,
	NOTE,
	OFFICE_ROLES,
	PRINCIPAL_ROLE,
)

READ_TYPES = ("read", "print", "email", "report", "select")
NOTE_OPEN_ROLES = {COUNSELLOR_ROLE, PRINCIPAL_ROLE}  # read every non-confidential note


# ---- Counselling Note -----------------------------------------------------------------------


def note_permission_query(user=None):
	user = user or frappe.session.user
	if user == "Administrator":
		return ""
	table, escaped = f"`tab{NOTE}`", frappe.db.escape(user)
	rule = f"{table}.author = {escaped} or {table}.counsellor = {escaped}"
	open_rule = "1 = 1" if NOTE_OPEN_ROLES & set(frappe.get_roles(user)) else scoped_student_rule(user, table)
	return f"({rule} or (ifnull({table}.is_confidential, 0) = 0 and ({open_rule})))"


def note_has_permission(doc, ptype=None, user=None):
	"""Deny-only hook. A new note passes here; its controller checks who may write about the student."""
	user = user or frappe.session.user
	if user == "Administrator" or ptype == "create" or doc.is_new():
		return True
	if ptype in READ_TYPES:
		return reads_note(doc, user)
	return ptype == "write" and doc.author == user


def reads_note(doc, user):
	if user in (doc.author, doc.counsellor):
		return True
	if doc.is_confidential:
		return False
	roles = set(frappe.get_roles(user))
	return bool(NOTE_OPEN_ROLES & roles) or in_student_scope(doc, user, roles)


def check_may_write_note(user, student):
	if user == "Administrator" or COUNSELLOR_ROLE in frappe.get_roles(user) or is_mentor_of(user, student):
		return
	frappe.throw(_("Only the student's mentor or a student counsellor may write a counselling note."), frappe.PermissionError)


# ---- Parent Interaction ---------------------------------------------------------------------


def interaction_permission_query(user=None):
	user = user or frappe.session.user
	if user == "Administrator" or set(OFFICE_ROLES) & set(frappe.get_roles(user)):
		return ""
	table, escaped = f"`tab{INTERACTION}`", frappe.db.escape(user)
	advised = f"select name from `tabStudent` where oc_class_advisor = {escaped}"
	return f"({table}.recorded_by = {escaped} or {table}.student in ({advised}) or {scoped_student_rule(user, table)})"


def interaction_has_permission(doc, ptype=None, user=None):
	user = user or frappe.session.user
	if user == "Administrator" or ptype == "create" or doc.is_new():
		return True
	roles = set(frappe.get_roles(user))
	if set(OFFICE_ROLES) & roles:
		return True
	if ptype in READ_TYPES:
		return reads_interaction(doc, user, roles)
	return ptype == "write" and (is_mentor_of(user, doc.student) or is_class_advisor_of(user, doc.student))


def reads_interaction(doc, user, roles=None):
	roles = roles if roles is not None else set(frappe.get_roles(user))
	if user == doc.recorded_by or set(OFFICE_ROLES) & roles or is_class_advisor_of(user, doc.student):
		return True
	return in_student_scope(doc, user, roles)


def check_may_record_interaction(user, student):
	roles = set(frappe.get_roles(user))
	if user == "Administrator" or set(OFFICE_ROLES) & roles or is_mentor_of(user, student) or is_class_advisor_of(user, student):
		return
	frappe.throw(_("Only the student's mentor, class advisor or the office may record a parent interaction."), frappe.PermissionError)


# ---- shared ---------------------------------------------------------------------------------


def block_share(doc, method=None):
	"""DocShare validate: mentoring records are never shared (an assignment shares too, so it is refused as well)."""
	if doc.share_doctype in (NOTE, INTERACTION):
		frappe.throw(_("{0} records cannot be shared.").format(_(doc.share_doctype)), frappe.PermissionError)


def scoped_student_rule(user, table):
	"""SQL: the row's student is the user's current mentee, or its department is one the user is HOD of."""
	escaped = frappe.db.escape(user)
	mentees = (
		"select s.name from `tabStudent` s join `tabEmployee` e on e.name = s.oc_mentor"
		f" where e.user_id = {escaped}"
	)
	rule = f"{table}.student in ({mentees})"
	departments = hod_departments(user) if HOD_ROLE in frappe.get_roles(user) else []
	if departments:
		rule += f" or {table}.department in ({', '.join(frappe.db.escape(d) for d in departments)})"
	return rule


def in_student_scope(doc, user, roles):
	if is_mentor_of(user, doc.student):
		return True
	return HOD_ROLE in roles and bool(doc.department) and doc.department in hod_departments(user)


def is_mentor_of(user, student):
	mentor = student and frappe.db.get_value("Student", student, "oc_mentor")
	return bool(mentor) and frappe.db.get_value("Employee", mentor, "user_id") == user


def is_class_advisor_of(user, student):
	return bool(student) and frappe.db.get_value("Student", student, "oc_class_advisor") == user


def hod_departments(user):
	"""Departments of the user's active HOD Position Holder seats (a blank scope gives none)."""
	from campus.examinations.api import held_scopes  # imported here: examinations imports student_services

	return held_scopes(user, "HOD")
