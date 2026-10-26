"""M06-01 Exam registration: bulk creation of Exam Registrations and the confirmation that fixes the fee.

Courses of a student in a session (registrable_courses):
- the term's course offerings the student is an active member of. The kind is Dropped or Arrear when the
  student's submitted Course Registration of the term lists the course so, else Current. Offerings of
  Internal Only courses (no end-semester exam) are left out;
- arrears: courses whose latest published outcome is U, AB or WD (arrears.reappearance_courses) and that the
  student does not take this term. They carry no offering;
- an offered course that is a bridge course still owed after an approved Rejoin Application
  (student_services.api.pending_bridge_courses) has kind Bridge; an unoffered one is not registered (it stays
  pending on the student's record).
A student on a break of study is not registered (student_services.api.on_break), nor a student whose examination
mode (Autonomous / Affiliated, campus.examinations.affiliation) is not the session's (M06-10).
Attendance comes from the locked Attendance Eligibility Run (student_services.api.attendance_snapshot). A
student with courses of the term but no snapshot row fails (the bulk run records the error) instead of passing.

Only one registration run of a session is live at a time (start locks the session row and refuses a Queued or
Running one). The bulk handler is DB-only and does not commit. It is idempotent: a re-run adds only missing courses, keeps
the existing rows and refreshes the attendance status. A confirmed registration is left as it is (its fee is fixed).
"""

import frappe
from frappe import _
from frappe.utils import escape_html, getdate, now_datetime, today

from campus.campus_platform.api import latest_enrollment
from campus.campus_platform.bulk import live_run, run_bulk
from campus.examinations import exam_fee, hall_tickets
from campus.examinations.access import COE_ROLE
from campus.examinations.affiliation import AUTONOMOUS, examination_mode
from campus.examinations.arrears import REAPPEAR, reappearance_courses
from campus.examinations.courses import offering_course
from campus.examinations.doctype.exam_registration.exam_registration import registration_name
from campus.examinations.registration_rules import ARREAR, ATTENDED_KINDS, BRIDGE, CURRENT, DROPPED
from campus.student_services.api import (
	attendance_snapshot,
	on_break,
	pending_bridge_courses,
	student_offerings,
)

DOCTYPE, SESSION = "Exam Registration", "Exam Session"
RUN_TYPE = "Exam Registration"
HANDLER = "campus.examinations.registration.register_student"
REGISTRATION_KINDS = {"Dropped": DROPPED, "Arrear": ARREAR}  # Course Registration Item type -> kind


def start(exam_session, program=None):
	"""Queue the bulk registration of the session's students (of `program` when given); returns the Bulk Run name."""
	frappe.only_for((COE_ROLE, "System Manager"))
	session = frappe.get_doc(SESSION, exam_session)
	session.check_permission("write")
	if session.status == "Published":
		frappe.throw(_("A published Exam Session takes no registrations."))
	if not session.registration_closes:
		frappe.throw(_("Set the registration closing date of {0} first.").format(frappe.bold(exam_session)))
	if program and frappe.db.get_value("Program", program, "oc_company") != session.company:
		frappe.throw(
			_("Program {0} does not belong to {1}.").format(
				frappe.bold(program), frappe.bold(session.company)
			)
		)
	frappe.db.get_value(SESSION, exam_session, "name", for_update=True)  # one start of a session at a time
	running = live_run(RUN_TYPE, exam_session=exam_session)
	if running:
		frappe.throw(
			_("Exam registration run {0} of this session is still running.").format(frappe.bold(running))
		)
	students = candidate_students(session, program)
	return run_bulk(RUN_TYPE, students, HANDLER, parameters={"exam_session": exam_session})


def candidate_students(session, program=None):
	"""Active members of the term's course offerings of the company, plus the company's students with an arrear."""
	group, member = frappe.qb.DocType("Student Group"), frappe.qb.DocType("Student Group Student")
	members = (
		frappe.qb.from_(group)
		.join(member)
		.on(member.parent == group.name)
		.select(member.student)
		.distinct()
		.where((group.oc_company == session.company) & (group.academic_term == session.academic_term))
		.where((group.group_based_on == "Course") & (member.active == 1))
	)
	result, course_row, published = (
		frappe.qb.DocType(n) for n in ("Student Result", "Student Result Course", SESSION)
	)
	arrears = (
		frappe.qb.from_(result)
		.join(course_row)
		.on((course_row.parent == result.name) & (course_row.parenttype == "Student Result"))
		.join(published)
		.on(published.name == result.exam_session)
		.select(result.student)
		.distinct()
		.where((result.company == session.company) & course_row.result.isin(REAPPEAR))
		.where((published.status == "Published") & (published.publish_at <= now_datetime()))
	)
	if program:
		members, arrears = members.where(group.program == program), arrears.where(result.program == program)
	return sorted({row[0] for row in members.run()} | {row[0] for row in arrears.run()})


def register_student(student, run):
	"""Bulk handler: create or top up one student's Exam Registration. DB-only, no commit."""
	return register(student, run.get_parameters()["exam_session"])


def register(student, exam_session):
	"""Create the student's Exam Registration in the session, or add its missing courses; returns its name or None."""
	session = frappe.db.get_value(
		SESSION,
		exam_session,
		["company", "academic_term", "status", "examination_mode"],
		as_dict=True,
		for_update=True,
	)
	if session.status == "Published":
		frappe.throw(_("A published Exam Session takes no registrations."))
	if on_break(student):
		return None
	if examination_mode(student) != (
		session.examination_mode or AUTONOMOUS
	):  # M06-10: the other mode's session
		return None
	courses = registrable_courses(student, session.academic_term)
	if not courses:
		return None
	status = attendance_status(student, session, courses)
	name = registration_name(exam_session, student)
	# a locking read: a plain one after the session lock sees this transaction's older snapshot
	if not frappe.db.get_value(DOCTYPE, name, "name", for_update=True):
		return frappe.get_doc(
			{
				"doctype": DOCTYPE, "exam_session": exam_session, "student": student,
				"program": (latest_enrollment(student) or {}).get("program"), "attendance_status": status, "courses": courses,
			}
		).insert().name  # fmt: skip
	doc = frappe.get_doc(DOCTYPE, name, for_update=True)  # a locking read, children included
	if doc.confirmed:
		return name
	have = {row.course for row in doc.courses}
	missing = [row for row in courses if row["course"] not in have]
	if missing or doc.attendance_status != status:
		for row in missing:
			doc.append("courses", row)
		doc.attendance_status = status
		doc.save()
	return name


def registrable_courses(student, academic_term):
	"""[{course, course_offering, kind}] of the student in the term (see the module docstring)."""
	kinds, bridge = registered_kinds(student, academic_term), set(pending_bridge_courses(student))
	rows = []
	for offering in student_offerings(student, academic_term):
		course = offering_course(offering.name)
		if not course["configured"]:  # blank: refused, never registered as a guessed Theory (R-08)
			frappe.throw(
				_("Course {0} ({1}) has no exam type; set it on the curriculum before registering.").format(
					frappe.bold(escape_html(offering.course)), escape_html(offering.name)
				)
			)
		if not course["course_type"]:  # Internal Only: no end-semester exam
			continue
		kind = (
			BRIDGE
			if offering.course in bridge
			else REGISTRATION_KINDS.get(kinds.get(offering.course), CURRENT)
		)
		rows.append({"course": offering.course, "course_offering": offering.name, "kind": kind})
	taken = {row["course"] for row in rows}
	return rows + [{"course": c, "kind": ARREAR} for c in reappearance_courses(student) if c not in taken]


def registered_kinds(student, academic_term):
	"""{course: registration type} from the student's submitted Course Registrations of the term."""
	registration, item = (
		frappe.qb.DocType("Course Registration"),
		frappe.qb.DocType("Course Registration Item"),
	)
	return dict(
		frappe.qb.from_(registration)
		.join(item)
		.on((item.parent == registration.name) & (item.parenttype == "Course Registration"))
		.select(item.course, item.registration_type)
		.where((registration.student == student) & (registration.academic_term == academic_term))
		.where(registration.docstatus == 1)
		.run()
	)


def attendance_status(student, session, courses):
	"""The snapshot status when the student takes courses this term; None for arrears only."""
	if not any(row["kind"] in ATTENDED_KINDS for row in courses):
		return None
	status = attendance_snapshot(student, session.academic_term, session.company)
	if not status:
		frappe.throw(
			_(
				"No locked attendance eligibility run holds {0} for {1}; lock the run of the term first."
			).format(frappe.bold(student), frappe.bold(session.academic_term))
		)
	return status


def confirm(name):
	"""Confirm a registration: fix its fee (per eligible course plus today's late fee slab) and queue the invoice.

	Refused for a published session, before registration opens, once the exams start, past the last late fee slab
	and when the fee invoice could not be raised. The caller has checked who may confirm (the portal: the student themself). The registration row is locked
	and re-read first, so a double submit or a concurrent bulk top-up cannot confirm twice or change the courses.
	"""
	doc = frappe.get_doc(DOCTYPE, name, for_update=True)
	if doc.confirmed:
		frappe.throw(_("This exam registration is already confirmed."))
	session = frappe.db.get_value(
		SESSION,
		doc.exam_session,
		["status", "registration_opens", "registration_closes", "exam_start"],
		as_dict=True,
	)
	if session.status == "Published":
		frappe.throw(_("A published Exam Session takes no registrations."))
	if session.registration_opens and getdate(today()) < getdate(session.registration_opens):
		frappe.throw(
			_("Registration opens on {0}.").format(frappe.format(session.registration_opens, "Date"))
		)
	if session.exam_start and getdate(today()) >= getdate(session.exam_start):
		frappe.throw(_("The examinations of this session have started; registration is closed."))
	eligible = doc.eligible_courses()
	if not eligible:
		frappe.throw(_("No course of this registration is eligible for the examination."))
	fee = exam_fee.registration_fee(doc.company, doc.program, len(eligible), session.registration_closes)
	if fee["fee_total"] > 0:
		exam_fee.check_invoiceable(
			doc.student, doc.company
		)  # refuse now rather than confirm a fee never invoiced
	doc.update(fee)
	doc.confirmed, doc.confirmed_on = 1, now_datetime()
	doc.flags.ignore_permissions = True  # the student confirms; every value is server-side
	doc.flags.server_fields = True  # confirmed and the fee are set here only
	doc.save()
	exam_fee.queue_fee(doc)
	return doc


def student_registrations(student):
	"""The student's Exam Registrations in sessions not yet published, newest first, as plain dicts.

	No permission check: the caller (the portal) has resolved the student from the session user.
	"""
	rows = []
	for name in frappe.get_all(DOCTYPE, {"student": student}, pluck="name", order_by="creation desc"):
		doc = frappe.get_doc(DOCTYPE, name)
		if frappe.db.get_value(SESSION, doc.exam_session, "status") == "Published":
			continue
		rows.append(
			{
				**{f: doc.get(f) for f in ("name", "exam_session", "academic_term", "confirmed", "late_fee", "fee_total", "fee_invoice")},
				"has_eligible": bool(doc.eligible_courses()),
				"hall_ticket": hall_tickets.portal_row(doc.name),
				"courses": [{f: c.get(f) for f in ("course", "kind", "eligibility")} for c in doc.courses],
			}
		)  # fmt: skip
	return rows
