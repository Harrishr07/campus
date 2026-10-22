"""M06-06, M16-04 A student's own photocopy, revaluation and review applications, for the campus portal (P2-T25).

The caller (campus.student_services portal) has resolved the student from the session user and checked that the
user is the student; nothing here trusts a student id from a request. The rules stay campus.examinations.revaluation's
(the window from release, eligibility, the photocopy and justification steps, the fee): an application is made with
ignore_permissions, since portal roles hold no right on Revaluation Application, and validated as any other.

- options: the student's released results (examinations.api.released_sessions: Published, publish_at passed; the
  latest, ratified version) whose application window is open today, with the courses they may apply for.
- apply: makes the application and submits it at once (the fee invoice follows), unless a teacher's justification
  is still due (R2022 revaluation after photocopy): then it stays a draft the student submits once justified.
- applications: every application of the student with a portal status; the marks of an outcome are never shown,
  they reach the student through the ratified result.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, getdate, today

from campus.campus_platform.api import get_rule
from campus.examinations import revaluation, revaluation_rules

APPLICATION, OUTCOME, RESULT, SESSION = revaluation.APPLICATION, revaluation.OUTCOME, revaluation.RESULT, revaluation.SESSION
AWAITING_JUSTIFICATION, DRAFT, CANCELLED = "Awaiting justification", "Draft", "Cancelled"
INVOICE_PENDING, FEE_DUE, PHOTOCOPY_PENDING, PHOTOCOPY_ISSUED = "Fee invoice pending", "Fee due", "Photocopy being prepared", "Photocopy issued"
IN_PROGRESS = {revaluation.REVALUATION: "Under revaluation", revaluation.REVIEW: "Under review"}
COMPLETED, COURSE_IN_PROGRESS = "Completed", "In progress"


def options(student):
	"""[{exam_session, academic_term, closes_on, courses: [{course, grade}]}] of the open windows, newest first."""
	from campus.examinations.api import released_sessions

	rows = frappe.get_all(RESULT, {"student": student, "is_latest": 1}, ["name", "exam_session", "company"], order_by="creation desc")
	if not rows:
		return []
	rule_set = get_rule(student, "Exam Rule Set")
	released = {company: set(released_sessions(company)) for company in {r.company for r in rows}}
	found = []
	for row in rows:
		if row.exam_session not in released[row.company]:
			continue
		published_on = getdate(frappe.db.get_value(SESSION, row.exam_session, "publish_at"))
		if not revaluation_rules.window_open(published_on, today(), rule_set.revaluation_window_days):
			continue
		result = frappe.get_doc(RESULT, row.name)
		courses = [{"course": c.course, "grade": c.grade} for c in revaluation.eligible_courses(result, rule_set)]
		if courses:
			found.append(
				{
					"exam_session": row.exam_session, "academic_term": result.academic_term, "courses": courses,
					"closes_on": add_days(published_on, cint(rule_set.revaluation_window_days)),
				}
			)  # fmt: skip
	return found


def apply(student, exam_session, application_type, courses):
	"""Make (and, when nothing is due from a teacher, submit) the student's application; returns its row."""
	if application_type not in (revaluation.PHOTOCOPY, revaluation.REVALUATION, revaluation.REVIEW):
		frappe.throw(_("Choose Photocopy, Revaluation or Review."))
	doc = frappe.get_doc(
		{
			"doctype": APPLICATION, "student": student, "exam_session": exam_session, "application_type": application_type,
			"courses": [{"course": course} for course in courses],
		}
	)  # fmt: skip
	doc.flags.ignore_permissions = True  # portal roles hold no right on the doctype; the caller resolved the student
	doc.insert()
	if not awaiting_justification(doc):
		doc.submit()
	return application_row(doc.reload())  # the fee job has set the invoice


def submit(student, application):
	"""Submit the student's own draft once its justifications are recorded; returns its row."""
	name = frappe.db.get_value(APPLICATION, {"name": application, "student": student}, "name", for_update=True)
	if not name:
		frappe.throw(_("You cannot submit this application."), frappe.PermissionError)
	doc = frappe.get_doc(APPLICATION, name)
	if doc.docstatus != 0:
		frappe.throw(_("{0} is already submitted.").format(frappe.bold(doc.name)))
	if awaiting_justification(doc):
		frappe.throw(_("A teacher of the course has not recorded the justification for revaluing it yet."))
	doc.flags.ignore_permissions = True
	doc.submit()
	return application_row(doc.reload())


def applications(student):
	"""Rows of the student's applications, newest first."""
	names = frappe.get_all(APPLICATION, {"student": student}, pluck="name", order_by="creation desc")
	return [application_row(frappe.get_doc(APPLICATION, name)) for name in names]


def awaiting_justification(doc):
	"""A revaluation that the regulation puts after a photocopy needs a teacher's justification of every course."""
	if doc.application_type != revaluation.REVALUATION:
		return False
	if not cint(get_rule(doc.student, "Exam Rule Set").revaluation_after_photocopy):
		return False
	return any(not row.justified_by for row in doc.courses)


def application_row(doc):
	completed = completed_courses(doc)
	waiting = doc.docstatus == 0 and awaiting_justification(doc)
	return {
		"name": doc.name, "application_type": doc.application_type, "exam_session": doc.exam_session,
		"application_date": doc.application_date, "fee_amount": doc.fee_amount, "fee_invoice": doc.fee_invoice,
		"status": status(doc, completed, waiting), "can_submit": doc.docstatus == 0 and not waiting,
		"courses": [
			{"course": row.course, "grade": row.grade, "status": course_status(doc, row.course, completed)} for row in doc.courses
		],
	}  # fmt: skip


def status(doc, completed, waiting):
	if doc.docstatus == 2:
		return CANCELLED
	if doc.docstatus == 0:
		return AWAITING_JUSTIFICATION if waiting else DRAFT
	if not revaluation.fee_paid(doc):
		return FEE_DUE if doc.fee_invoice else INVOICE_PENDING
	if doc.application_type == revaluation.PHOTOCOPY:
		return PHOTOCOPY_ISSUED if doc.photocopy_issued_on else PHOTOCOPY_PENDING
	return COMPLETED if completed >= {row.course for row in doc.courses} else IN_PROGRESS[doc.application_type]


def course_status(doc, course, completed):
	if doc.application_type == revaluation.PHOTOCOPY or doc.docstatus != 1:
		return None
	return COMPLETED if course in completed else COURSE_IN_PROGRESS


def completed_courses(doc):
	if doc.docstatus != 1 or doc.application_type == revaluation.PHOTOCOPY:
		return set()
	return set(frappe.get_all(OUTCOME, {"application": doc.name, "docstatus": 1}, pluck="course"))
