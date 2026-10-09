"""M06-01, M06-06, M16-04 Student exam pages of /campus-portal (P2-T25): exam registrations with their fee invoice and
hall ticket, exam withdrawal, and photocopy / revaluation / review applications with their fee.

The student comes from portal.resolve_student (the session user's own student, or a guardian's ward), never from the
request alone. A guardian reads; only the student applies (as only the student confirms an exam registration).
Release dates are the rules' own and are enforced server-side: hall tickets after hall_ticket_release_on
(hall_tickets.portal_row and access.py), revaluation from the release of the results within the Exam Rule Set's
window (examinations.revaluation), withdrawal while the session is unpublished and within its window (Exam
Withdrawal Application). A fee is paid with portal.pay_invoice through the college's gateway (campus_finance).
"""

import json

import frappe
from frappe import _
from frappe.utils import flt

from campus.campus_finance.api import can_pay_online
from campus.campus_platform.api import latest_request, start_request
from campus.examinations import api as exams
from campus.student_services.portal import is_the_student, my_exam_registrations, resolve_student

WITHDRAWAL = "Exam Withdrawal Application"


def require_the_student(student):
	if not is_the_student(student):
		frappe.throw(_("Only the student can apply."), frappe.PermissionError)


def parse_courses(courses):
	"""Course names from a JSON list (the portal form), a comma-separated string or a list."""
	if isinstance(courses, str):
		try:
			courses = json.loads(courses)
		except ValueError:
			courses = courses.split(",")
	if not isinstance(courses, list | tuple):
		frappe.throw(_("Choose the courses."))
	names = [str(course).strip() for course in courses if str(course).strip()]
	if not names:
		frappe.throw(_("Choose the courses."))
	return names


def invoice_state(invoice):
	"""{name, outstanding_amount, currency, can_pay} of a fee invoice, or None."""
	row = invoice and frappe.db.get_value(
		"Sales Invoice", invoice, ["name", "company", "docstatus", "is_return", "outstanding_amount", "currency"], as_dict=True
	)
	if not row:
		return None
	due = row.docstatus == 1 and not row.is_return and flt(row.outstanding_amount) > 0
	return {
		"name": row.name, "outstanding_amount": row.outstanding_amount, "currency": row.currency,
		"can_pay": bool(due and can_pay_online(row.company)),
	}  # fmt: skip


# ---- exams: registrations, hall tickets, withdrawal ------------------------------------------------


@frappe.whitelist()
def my_exams(student=None):
	"""The student's registrations of unpublished sessions (fee invoice, hall ticket), withdrawable courses and
	withdrawal applications."""
	student = resolve_student(student)
	registrations = my_exam_registrations(student)["registrations"]
	for row in registrations:
		row["invoice"] = invoice_state(row["fee_invoice"])
	withdrawals = withdrawal_rows(student)
	return {
		"student": student, "can_act": is_the_student(student), "registrations": registrations,
		"withdrawable": withdrawable(registrations, withdrawals), "withdrawals": withdrawals,
	}  # fmt: skip


def withdrawable(registrations, withdrawals):
	"""[{exam_session, courses}]: eligible courses of the term (not arrears or bridges) with no live application."""
	taken = {(w["exam_session"], c) for w in withdrawals if w["docstatus"] < 2 for c in w["courses"]}
	found = []
	for row in registrations:
		courses = [
			c["course"] for c in row["courses"]
			if c["kind"] in exams.TERM_KINDS and c["eligibility"] == "Eligible" and (row["exam_session"], c["course"]) not in taken
		]  # fmt: skip
		if courses:
			found.append({"exam_session": row["exam_session"], "courses": courses})
	return found


def withdrawal_rows(student):
	names = frappe.get_all(WITHDRAWAL, {"student": student}, pluck="name", order_by="creation desc")
	return [withdrawal_row(frappe.get_doc(WITHDRAWAL, name)) for name in names]


def withdrawal_row(doc):
	status = {1: "Approved", 2: "Cancelled"}.get(doc.docstatus)  # translated by the page
	if not status:
		request = latest_request(doc)
		status = request.status if request else "Draft"
	return {
		"name": doc.name, "exam_session": doc.exam_session, "application_date": doc.application_date, "reason": doc.reason,
		"courses": [row.course for row in doc.courses], "status": status, "docstatus": doc.docstatus,
	}  # fmt: skip


@frappe.whitelist(methods=["POST"])
def apply_withdrawal(exam_session, courses, reason, student=None):
	"""The student withdraws from the examination of registered courses; the application goes to its approval
	(HOD, then Principal). The controller checks the registration, the window and once-per-programme."""
	student = resolve_student(student)
	require_the_student(student)
	doc = frappe.get_doc(
		{
			"doctype": WITHDRAWAL, "student": student, "exam_session": exam_session, "reason": (reason or "").strip(),
			"courses": [{"course": course} for course in parse_courses(courses)],
		}
	)  # fmt: skip
	doc.flags.ignore_permissions = True  # portal roles hold no right on the doctype; every value is checked server-side
	doc.insert()
	start_request(doc)
	return withdrawal_row(doc.reload())


# ---- photocopy, revaluation, review --------------------------------------------------------------


def with_invoice(row):
	row["invoice"] = invoice_state(row.pop("fee_invoice"))
	return row


@frappe.whitelist()
def my_revaluations(student=None):
	"""Open application windows of the student's released results and their applications with status and fee."""
	student = resolve_student(student)
	return {
		"student": student, "can_apply": is_the_student(student), "options": exams.revaluation_options(student),
		"applications": [with_invoice(row) for row in exams.student_revaluations(student)],
	}  # fmt: skip


@frappe.whitelist(methods=["POST"])
def apply_revaluation(exam_session, application_type, courses, student=None):
	"""The student applies for a Photocopy, Revaluation or Review of courses of a released result."""
	student = resolve_student(student)
	require_the_student(student)
	return with_invoice(exams.apply_revaluation(student, exam_session, application_type, parse_courses(courses)))


@frappe.whitelist(methods=["POST"])
def submit_revaluation(application, student=None):
	"""The student submits their own draft revaluation once a teacher has justified it."""
	student = resolve_student(student)
	require_the_student(student)
	return with_invoice(exams.submit_revaluation(student, application))
