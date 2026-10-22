"""M05-12 Attendance corrections: once the cut-off after a period was first marked has passed (Campus Settings
`attendance_correction_hours`, 48 by default), a marked student's status changes only through an Attendance Correction
Request approved by the HOD of the course's department (approval engine, seeded policy). Within the cut-off the
period's teacher re-marks it as before (campus.faculty.portal / substitute_attendance).

The approved request is submitted by the engine; on submit the marked record is cancelled and replaced (the same writer
as marking) and a Version of the change is kept on the new record. A student never marked in the period is, after the
cut-off, also marked only through a request (an unmarked student counts as not attended).

The cut-off holds for every writer of Student Attendance (doc_events, `guard_record` / `guard_cancel`): desk cancel and
amend, Education's attendance tool and `mark_period` alike. Only `apply()` passes, by flagging the records it writes and
cancels, and a record carrying the student's approved leave for its date (Education's leave approval); no role is exempt.
"""

import frappe
from frappe import _
from frappe.query_builder.functions import Min
from frappe.utils import add_to_date, cint, get_datetime, getdate, now_datetime

from campus.campus_platform.api import find_policy, start_request

DOCTYPE = "Attendance Correction Request"
POLICY = "Attendance Correction - HOD"
SETTINGS = "Campus Settings"
ACADEMIC_OFFICE_ROLES = ("HOD", "Dean Academics", "Principal", "System Manager")


# ---- the cut-off ----------------------------------------------------------------------------


def cutoff_hours():
	"""The Campus Settings value; the field's default while the settings were never saved with it."""
	fieldname = "attendance_correction_hours"
	stored = frappe.db.sql("select value from `tabSingles` where doctype = %s and field = %s", (SETTINGS, fieldname))
	if stored and stored[0][0] not in (None, ""):
		return cint(stored[0][0])
	return cint(frappe.get_meta(SETTINGS).get_field(fieldname).default)


def past_cutoff(course_schedule):
	"""True when the cut-off after the period's first marking (any record, also a cancelled one) has passed."""
	attendance = frappe.qb.DocType("Student Attendance")
	first = frappe.qb.from_(attendance).select(Min(attendance.creation)).where(attendance.course_schedule == course_schedule).run()[0][0]
	return bool(first) and now_datetime() > add_to_date(get_datetime(first), hours=cutoff_hours())


def refuse_late_changes(course_schedule, wanted):
	"""Marking (`wanted` = {student: status}) after the cut-off may repeat a marked status, nothing else: neither a
	change nor a first mark. The caller holds the period lock; the marks are re-read with a locking read."""
	if not wanted or not past_cutoff(course_schedule):
		return
	marked = dict(
		frappe.db.sql(
			"select student, status from `tabStudent Attendance` where course_schedule = %s and docstatus = 1 for update",
			course_schedule,
		)
	)
	changed = sorted(student for student, status in wanted.items() if marked.get(student) != status)
	if changed:
		frappe.throw(
			_("The attendance of {0} was marked more than {1} hours ago. Raise an Attendance Correction Request for: {2}").format(
				course_schedule, cutoff_hours(), ", ".join(changed)
			)
		)


def guard_record(doc, method=None):
	"""Student Attendance validate: after the cut-off no record of the period is written (a new mark, an amendment,
	Education's tool) except by an approved correction, or by the student's approved leave covering its date (Education
	writes and, on the leave's cancel, cancels those records)."""
	if not doc.course_schedule or doc.flags.attendance_correction or backed_by_leave(doc):
		return
	if past_cutoff(doc.course_schedule):
		frappe.throw(late_change_message(doc))


def backed_by_leave(doc):
	if not doc.leave_application:
		return False
	leave = frappe.db.get_value("Student Leave Application", doc.leave_application, ["student", "from_date", "to_date"], as_dict=True)
	return bool(leave) and leave.student == doc.student and getdate(leave.from_date) <= getdate(doc.date) <= getdate(leave.to_date)


def guard_cancel(doc, method=None):
	"""Student Attendance before_cancel: after the cut-off a mark is cancelled only by an approved correction."""
	guard_record(doc)


def late_change_message(doc):
	return _("The attendance of {0} was first marked more than {1} hours ago; {2} changes only through an approved Attendance Correction Request.").format(
		doc.course_schedule, cutoff_hours(), frappe.bold(doc.student)
	)


# ---- the request ----------------------------------------------------------------------------


def prepare(doc):
	"""Fill what the server decides: the session, its company and department, and the marked record being corrected."""
	session = frappe.db.get_value("Course Schedule", doc.course_schedule, ["student_group", "schedule_date", "course"], as_dict=True)
	if not session:
		frappe.throw(_("Session {0} does not exist.").format(frappe.bold(doc.course_schedule)))
	group = frappe.db.get_value("Student Group", session.student_group, ["oc_company", "program", "course"], as_dict=True)
	doc.student_group, doc.schedule_date, doc.company = session.student_group, session.schedule_date, group.oc_company
	doc.department = department_of(session.course or group.course, group.program)
	doc.student_name = frappe.db.get_value("Student", doc.student, "student_name")
	if not frappe.db.exists("Student Group Student", {"parent": session.student_group, "student": doc.student, "active": 1}):
		frappe.throw(_("{0} is not an active student of {1}.").format(frappe.bold(doc.student), session.student_group))
	marked = marked_record(doc)
	doc.attendance, doc.current_status = (marked.name, marked.status) if marked else (None, None)
	if doc.new_status == doc.current_status:
		frappe.throw(_("{0} is already marked {1}; there is nothing to correct.").format(frappe.bold(doc.student), _(doc.new_status)))


def check_requester(doc):
	"""A request raised on the desk comes from the period's teacher (own or substituted period), unless the user is an
	HOD or in the academic office."""
	if set(ACADEMIC_OFFICE_ROLES) & set(frappe.get_roles()):
		return
	from campus.faculty import portal

	portal.period_grant(doc.course_schedule, portal.require_faculty())


def department_of(course, program):
	return (course and frappe.db.get_value("Course", course, "department")) or (
		program and frappe.db.get_value("Program", program, "department")
	) or None


def marked_record(doc, for_update=False):
	return frappe.db.get_value(
		"Student Attendance", {"student": doc.student, "course_schedule": doc.course_schedule, "docstatus": 1},
		["name", "status"], as_dict=True, for_update=for_update,
	)  # fmt: skip


def before_request(doc):
	"""A correction is never applied without approval: refuse the request when no policy matches."""
	if not find_policy(doc):
		frappe.throw(_("No Approval Policy is set for {0}; it cannot be applied without approval.").format(_(DOCTYPE)))


def apply(doc):
	"""On submit (the final approval): replace the marked record (or mark the unmarked student) with the corrected
	status and keep a Version of a replaced record. The session must still be held."""
	from campus.faculty import session_states
	from campus.faculty.substitute_attendance import record

	session = frappe.db.get_value(
		"Course Schedule", doc.course_schedule, ["student_group", "schedule_date", "oc_session_state"], as_dict=True, for_update=True
	)
	session_states.check_held(doc.course_schedule, session.oc_session_state)
	marked = marked_record(doc, for_update=True)
	if (marked.name if marked else None) != (doc.attendance or None):
		frappe.throw(_("The attendance of {0} in {1} changed after this request was raised; raise a new one.").format(doc.student, doc.course_schedule))
	before = frappe.get_doc("Student Attendance", marked.name) if marked else None
	after = frappe.get_doc(
		"Student Attendance", record(doc.student, doc.student_name, doc.new_status, doc.course_schedule, session, correction=True)
	)
	version = None
	if before:
		version = frappe.new_doc("Version")
		version.update_version_info(before, after)
		version.insert(ignore_permissions=True)
	after.add_comment("Info", _("Corrected from {0} by {1}").format(_(before.status) if before else _("not marked"), doc.name))
	doc.db_set({"corrected_attendance": after.name, "version": version and version.name}, update_modified=False)


@frappe.whitelist(methods=["POST"])
def request_correction(course_schedule, student, status, reason):
	"""Faculty portal: the period's teacher (own or substituted period) asks to correct a mark after the cut-off.
	Returns the request name; it waits on the HOD's approval."""
	from campus.faculty import portal

	portal.period_grant(course_schedule, portal.require_faculty())
	doc = frappe.get_doc(
		{"doctype": DOCTYPE, "course_schedule": course_schedule, "student": student, "new_status": status, "reason": (reason or "").strip()}
	)
	doc.flags.ignore_permissions = True  # the period grant above is the permission; the request still needs approval
	doc.insert()
	start_request(doc)
	return doc.name


# ---- seed -----------------------------------------------------------------------------------


def seed_policy():
	"""Corrections are approved by the HOD of the course's department, unless the college has its own policy."""
	if frappe.db.exists("Approval Policy", {"document_type": DOCTYPE}) or not frappe.db.exists("Position", "HOD"):
		return
	frappe.get_doc(
		{
			"doctype": "Approval Policy", "policy_name": POLICY, "document_type": DOCTYPE,
			"levels": [{"approver_type": "Position", "approver": "HOD", "scope_field": "department", "title": "HOD", "limit_to_company": 1}],
		}
	).insert(ignore_permissions=True)  # fmt: skip
