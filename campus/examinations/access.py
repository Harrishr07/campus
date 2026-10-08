"""M12-02 Who may enter marks and who may read results.

Marks (and the offering's CIA Schedule and CIA Unlock Requests): COE and System Manager, and the
instructors of the offering (Student Group instructor -> Instructor.employee -> Employee.user_id); other
staff roles read all, an HOD reads the offerings of the department's programmes. The session status and
CIA lock rules are the controllers'. Results: staff roles, else the student and guardians linked to the student,
and only once the session is Published and now >= publish_at.
"""

import frappe
from frappe.utils import get_datetime, getdate, now_datetime, today

COE_ROLE = "COE"
MARKS_ROLES = (COE_ROLE, "System Manager")
STAFF_ROLES = (COE_ROLE, "System Manager", "Dean Academics", "Academics User")
READ_TYPES = ("read", "print", "email", "export", "report", "select")
OFFERING_SCOPED = ("Mark Sheet Entry", "CIA Schedule", "CIA Unlock Request")


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


def hod_offerings(user):
	"""Course offerings of programmes whose department the user holds the HOD seat of."""
	departments = held_scopes(user, HOD_POSITION)
	if not departments:
		return []
	programs = frappe.get_all("Program", {"department": ["in", departments]}, pluck="name") or [""]
	return frappe.get_all("Student Group", {"group_based_on": "Course", "program": ["in", programs]}, pluck="name")


def offering_permission_query(user=None, doctype="Mark Sheet Entry"):
	"""Lists of OFFERING_SCOPED doctypes: staff see all; instructors their offerings, HODs their department's."""
	user = user or frappe.session.user
	if has_any_role(user, STAFF_ROLES):
		return ""
	offerings = ", ".join(frappe.db.escape(o) for o in {*instructed_offerings(user), *hod_offerings(user)})
	return f"`tab{doctype}`.course_offering in ({offerings})"


def offering_has_permission(doc, ptype=None, user=None):
	"""COE edits all; other staff read all; instructors edit their own offerings; an HOD reads the department's."""
	user = user or frappe.session.user
	if has_any_role(user, MARKS_ROLES):
		return True
	if ptype in READ_TYPES and has_any_role(user, STAFF_ROLES):
		return True
	offering = offering_of(doc)
	if offering and user in instructor_users(offering):
		return True
	return ptype in READ_TYPES and offering in hod_offerings(user)


def offering_of(doc):
	"""The doc's course offering; a new CIA Unlock Request has only its schedule until its links are fetched."""
	if doc.get("course_offering") or not doc.get("cia_schedule"):
		return doc.get("course_offering")
	return frappe.db.get_value("CIA Schedule", doc.cia_schedule, "course_offering")


# ---- Student-linked records ---------------------------------------------------------------

PORTAL_ROLES = ("Student", "Guardian")
MENTOR_ROLE = "Mentor"  # read right on Student only, narrowed to the user's mentees below
SCOPED_ROLES = (*PORTAL_ROLES, MENTOR_ROLE)


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


def mentees_of(user):
	"""Students whose Student.oc_mentor is an Employee of the user (the mentor allocation tool sets it)."""
	if not user:
		return set()
	employees = frappe.get_all("Employee", {"user_id": user}, pluck="name")
	return set(frappe.get_all("Student", {"oc_mentor": ["in", employees]}, pluck="name")) if employees else set()


def visible_students(user):
	"""What a Student-scoped user may read: their own / guarded students plus their mentees."""
	return students_of(user) | mentees_of(user)


def guardians_of(user):
	"""The user's own Guardian records plus the guardians of the students the user is or guards."""
	own = frappe.get_all("Guardian", {"user": user}, pluck="name")
	linked = frappe.get_all(
		"Student Guardian", {"parent": ["in", students_of(user) or [""]], "parenttype": "Student"}, pluck="guardian"
	)
	return set(own) | set(linked)


def groups_of(user):
	"""Student Groups that contain one of the user's students."""
	rows = frappe.get_all(
		"Student Group Student", {"student": ["in", students_of(user) or [""]], "parenttype": "Student Group"}, pluck="parent"
	)
	return set(rows)


# doctype -> (field holding the scoping key, function(user) -> keys the portal user may see).
# Upstream grants the Student/Guardian roles company-wide read on all of these.
PORTAL_SCOPES = {
	"Student": ("name", visible_students),
	"Guardian": ("name", guardians_of),
	"Program Enrollment": ("student", students_of),
	"Student Attendance": ("student", students_of),
	"Student Leave Application": ("student", students_of),
	"Condonation Request": ("student", students_of),
	"Certificate Request": ("student", students_of),
	"Student Grievance": ("student", students_of),
	"Assessment Result": ("student", students_of),
	"Sales Invoice": ("student", students_of),
	"Course Schedule": ("student_group", groups_of),
}


# Confidential rows (e.g. an ICC grievance) are for the committee roles alone, whatever else a role may read;
# the student who raised one still sees their own through the portal scope above, but a guardian does not.
COMMITTEE_ROLE = "Grievance Committee"
COMMITTEE_ROLES = (COMMITTEE_ROLE, "System Manager")
CONFIDENTIAL_FIELDS = {"Student Grievance": "is_confidential"}
# Handlers other than these see a Student Grievance only for their own department or one they handled.
COMPANY_WIDE_HANDLERS = ("Principal", "Dean Student Affairs")
HANDLER_POSITION = HOD_POSITION = "HOD"


def held_scopes(user, position):
	"""Scope values (e.g. departments) of the active holdings of `position` by `user`; a holding with a blank scope
	gives none (it must never match a row whose scope is blank too)."""
	today_ = getdate(today())
	values = frappe.get_all(
		"Position Holder",
		{"user": user, "position": position, "from_date": ["<=", today_]},
		or_filters=[["to_date", "is", "not set"], ["to_date", ">=", today_]],
		pluck="scope_value",
	)
	return [value for value in values if value]


def handled_grievances_sql(user):
	"""Sub-select of the Student Grievances `user` is or was an approver of."""
	return (
		"select r.reference_name from `tabApproval Request` r join `tabApproval Request Approver` a on a.parent = r.name"
		f" where r.reference_doctype = 'Student Grievance' and a.user = {frappe.db.escape(user)}"
	)


def confidential_clause(user, doctype):
	"""Extra list condition for a role that sees all rows of `doctype`: committee sees everything; others never see
	confidential rows, and (Student Grievance) only their department's or handled rows unless company-wide."""
	field = CONFIDENTIAL_FIELDS.get(doctype)
	if not field or has_any_role(user, COMMITTEE_ROLES):
		return ""
	clause = f"ifnull(`tab{doctype}`.`{field}`, 0) = 0"
	if has_any_role(user, COMPANY_WIDE_HANDLERS):
		return clause
	departments = ", ".join(frappe.db.escape(d) for d in held_scopes(user, HANDLER_POSITION))
	own = f" or `tab{doctype}`.department in ({departments})" if departments else ""  # no seat: never match a blank department
	return f"{clause} and (`tab{doctype}`.name in ({handled_grievances_sql(user)}){own})"


def may_see_confidential(doc, user):
	field = CONFIDENTIAL_FIELDS.get(doc.doctype)
	if not field or has_any_role(user, COMMITTEE_ROLES):
		return True
	if doc.get(field):
		return False
	if has_any_role(user, COMPANY_WIDE_HANDLERS):
		return True
	handled = frappe.db.sql(f"{handled_grievances_sql(user)} and r.reference_name = {frappe.db.escape(doc.name or '')}")
	department = doc.get("department")
	return bool(handled) or bool(department and department in held_scopes(user, HANDLER_POSITION))


def own_students(user):
	return set(frappe.get_all("Student", {"user": user}, pluck="name"))


def sees_all_students(user, doctype="Student"):
	"""True when a role other than Student/Guardian/Mentor gives the user level-0 read access to the doctype."""
	if user == "Administrator":
		return True
	roles = set(frappe.get_roles(user)) - set(SCOPED_ROLES)
	return any(p.role in roles and p.read and not p.permlevel for p in frappe.get_meta(doctype).permissions)


def portal_permission_query(user=None, doctype="Student"):
	"""Narrow the Student, Guardian and Mentor roles to rows of their own / linked / mentored students."""
	user = user or frappe.session.user
	if sees_all_students(user, doctype):
		return confidential_clause(user, doctype)
	field, keys_of = PORTAL_SCOPES[doctype]
	names = ", ".join(frappe.db.escape(k) for k in keys_of(user)) or "''"
	clause = f"`tab{doctype}`.`{field}` in ({names})"
	if doctype in CONFIDENTIAL_FIELDS:  # a guardian reads the ordinary rows of their ward, not the confidential ones
		own = ", ".join(frappe.db.escape(k) for k in own_students(user)) or "''"
		clause += f" and (ifnull(`tab{doctype}`.`{CONFIDENTIAL_FIELDS[doctype]}`, 0) = 0 or `tab{doctype}`.`{field}` in ({own}))"
	return clause


def portal_has_permission(doc, ptype=None, user=None):
	"""Deny-only hook: portal-only users get rows of their own or guarded students, staff roles are untouched."""
	user = user or frappe.session.user
	if sees_all_students(user, doc.doctype):
		return may_see_confidential(doc, user)
	field, keys_of = PORTAL_SCOPES[doc.doctype]
	if doc.doctype in CONFIDENTIAL_FIELDS and doc.get(CONFIDENTIAL_FIELDS[doc.doctype]):
		return doc.get(field) in own_students(user)
	return doc.get(field) in keys_of(user)


# ---- Student Result -----------------------------------------------------------------------


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


# ---- Hall Ticket --------------------------------------------------------------------------


def released_sessions():
	return frappe.get_all("Exam Session", {"hall_ticket_release_on": ["<=", now_datetime()]}, pluck="name")


def hall_ticket_permission_query(user=None):
	"""Staff see all tickets; a student or guardian only the issued, released tickets of their own students."""
	user = user or frappe.session.user
	if has_any_role(user, STAFF_ROLES):
		return ""
	students, sessions = students_of(user), released_sessions()
	if not (students and sessions):
		return "1=0"
	return "`tabHall Ticket`.status = 'Issued' and `tabHall Ticket`.student in ({}) and `tabHall Ticket`.exam_session in ({})".format(
		", ".join(frappe.db.escape(s) for s in students), ", ".join(frappe.db.escape(s) for s in sessions)
	)


def hall_ticket_has_permission(doc, ptype=None, user=None):
	"""Deny-only: portal users read / print an issued ticket of their own students once it is released."""
	user = user or frappe.session.user
	if has_any_role(user, STAFF_ROLES):
		return True
	if ptype and ptype not in READ_TYPES:
		return False
	release_on = frappe.db.get_value("Exam Session", doc.exam_session, "hall_ticket_release_on")
	released = bool(release_on) and get_datetime(release_on) <= now_datetime()
	return doc.status == "Issued" and doc.student in students_of(user) and released
