"""M12-02 Who may enter marks and who may read results.

Marks: COE and System Manager, and the instructors of the offering (Student Group instructor ->
Instructor.employee -> Employee.user_id), only while the Exam Session is in Marks Entry (the status
rule is the controller's). Results: staff roles, else the student and guardians linked to the student,
and only once the session is Published and now >= publish_at.
"""

import frappe
from frappe.utils import now_datetime

COE_ROLE = "COE"
MARKS_ROLES = (COE_ROLE, "System Manager")
STAFF_ROLES = (COE_ROLE, "System Manager", "Dean Academics", "Academics User")
READ_TYPES = ("read", "print", "email", "export", "report", "select")


def has_any_role(user, roles):
	return user == "Administrator" or bool(set(roles) & set(frappe.get_roles(user)))


# ---- Mark Sheet Entry ---------------------------------------------------------------------


def instructor_users(offering):
	"""User ids of the instructors of a course offering."""
	instructors = frappe.get_all("Student Group Instructor", {"parent": offering}, pluck="instructor") or [""]
	employees = frappe.get_all("Instructor", {"name": ["in", instructors]}, pluck="employee") or [""]
	return set(frappe.get_all("Employee", {"name": ["in", employees], "user_id": ["is", "set"]}, pluck="user_id"))


def instructed_offerings(user):
	instructors = frappe.get_all("Instructor", {"employee": ["in", employees_of(user)]}, pluck="name") or [""]
	return frappe.get_all("Student Group Instructor", {"instructor": ["in", instructors]}, pluck="parent") or [""]


def employees_of(user):
	return frappe.get_all("Employee", {"user_id": user}, pluck="name") or [""]


def marks_permission_query(user=None):
	user = user or frappe.session.user
	if has_any_role(user, STAFF_ROLES):
		return ""
	offerings = ", ".join(frappe.db.escape(o) for o in instructed_offerings(user))
	return f"`tabMark Sheet Entry`.course_offering in ({offerings})"


def marks_has_permission(doc, ptype=None, user=None):
	user = user or frappe.session.user
	if has_any_role(user, MARKS_ROLES):
		return True
	if ptype in READ_TYPES and has_any_role(user, STAFF_ROLES):
		return True
	return user in instructor_users(doc.course_offering)


# ---- Student ------------------------------------------------------------------------------

PORTAL_ROLES = ("Student", "Guardian")


def sees_all_students(user):
	"""True when a role other than Student/Guardian gives the user read access to Student."""
	if user == "Administrator":
		return True
	roles = set(frappe.get_roles(user)) - set(PORTAL_ROLES)
	return any(p.role in roles and p.read for p in frappe.get_meta("Student").permissions)


def student_permission_query(user=None):
	"""Upstream lets the Student and Guardian roles read every Student; narrow them to their own."""
	user = user or frappe.session.user
	if sees_all_students(user):
		return ""
	names = ", ".join(frappe.db.escape(s) for s in students_of(user)) or "''"
	return f"`tabStudent`.name in ({names})"


def student_has_permission(doc, ptype=None, user=None):
	"""Deny-only hook: portal-only users get their own or guarded students, staff roles are untouched."""
	user = user or frappe.session.user
	return sees_all_students(user) or doc.name in students_of(user)


# ---- Student Result -----------------------------------------------------------------------


def students_of(user):
	"""Students the user is (Student.user) or guards (Guardian.user on the student's guardian rows)."""
	own = frappe.get_all("Student", {"user": user}, pluck="name")
	guardians = frappe.get_all("Guardian", {"user": user}, pluck="name")
	guarded = (
		frappe.get_all("Student Guardian", {"guardian": ["in", guardians], "parenttype": "Student"}, pluck="parent")
		if guardians
		else []
	)
	return set(own) | set(guarded)


def published_sessions():
	return frappe.get_all(
		"Exam Session", {"status": "Published", "publish_at": ["<=", now_datetime()]}, pluck="name"
	)


def result_permission_query(user=None):
	user = user or frappe.session.user
	if has_any_role(user, STAFF_ROLES):
		return ""
	students, sessions = students_of(user), published_sessions()
	if not (students and sessions):
		return "1=0"
	return "`tabStudent Result`.student in ({}) and `tabStudent Result`.exam_session in ({})".format(
		", ".join(frappe.db.escape(s) for s in students), ", ".join(frappe.db.escape(s) for s in sessions)
	)


def result_has_permission(doc, ptype=None, user=None):
	"""Staff keep their role permissions; everyone else reads own/guarded published results only.

	A controller hook can only deny (a falsy result denies), so allowed users get True."""
	user = user or frappe.session.user
	if has_any_role(user, STAFF_ROLES):
		return True
	if ptype and ptype not in READ_TYPES:
		return False
	return doc.student in students_of(user) and doc.exam_session in published_sessions()
