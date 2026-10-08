"""M12-02 Examinations service API. Other modules call these, never the controllers (D7)."""

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from campus.examinations import results
from campus.examinations.access import students_of  # noqa: F401  (public API)
from campus.examinations.arrears import arrear_courses  # noqa: F401  (public API)

# Exam registration and its fee are imported where used: they import campus_finance.api, which imports this module.


@frappe.whitelist(methods=["POST"])
def run_results(exam_session, program):
	"""Queue the Result Run for `program` in `exam_session` (COE only); returns the Bulk Run name.

	Idempotent: a re-run replaces the Student Results of the session. Refused once Published.
	"""
	return results.start_run(exam_session, program)


@frappe.whitelist(methods=["POST"])
def issue_grade_sheet(student_result):
	"""Issue a verifiable Grade Sheet (QR) for a published Student Result; returns the Verifiable Document."""
	from campus.campus_platform.verification import issue
	from campus.examinations.access import MARKS_ROLES

	frappe.only_for(MARKS_ROLES)
	doc = frappe.get_doc("Student Result", student_result)
	doc.check_permission("read")
	status, publish_at = frappe.db.get_value("Exam Session", doc.exam_session, ["status", "publish_at"])
	if status != "Published" or not publish_at or get_datetime(publish_at) > now_datetime():
		frappe.throw(_("A Grade Sheet is issued only for a published Exam Session whose publication time has passed."))
	return issue(doc, "Grade Sheet").name


@frappe.whitelist(methods=["POST"])
def start_registration(exam_session, program=None):
	"""Queue the bulk Exam Registration of the session (COE only); returns the Bulk Run name.

	Idempotent: a re-run adds only the missing courses of unconfirmed registrations.
	"""
	from campus.examinations import registration

	return registration.start(exam_session, program or None)


@frappe.whitelist(methods=["POST"])
def generate_hall_tickets(exam_session):
	"""Queue the bulk Hall Ticket generation of the session (COE only); returns the Bulk Run name.

	Idempotent: unchanged tickets keep their QR; changed ones are re-issued, newly withheld ones revoked.
	"""
	from campus.examinations import hall_tickets

	return hall_tickets.start(exam_session)


@frappe.whitelist(methods=["POST"])
def reraise_exam_fee_invoices(exam_session):
	"""Queue the missing exam fee invoices of the session's confirmed registrations (COE only); returns the Bulk Run
	name or None. Idempotent: a registration gets at most one invoice."""
	from campus.examinations import exam_fee

	return exam_fee.reraise_invoices(exam_session)


@frappe.whitelist(methods=["POST"])
def generate_seating(seating_plan):
	"""Seat the plan's students in its Exam Halls (COE only); returns the number seated. Refused once attendance
	is marked."""
	from campus.examinations import seating

	return seating.generate(seating_plan)


@frappe.whitelist(methods=["POST"])
def mark_exam_absent(seating_plan, students, value=1):
	"""Mark (1) or clear (0) students absent on a Seating Plan (COE only); the Result Run grades them AB."""
	from campus.examinations import seating

	return seating.mark_absent(seating_plan, students, value)


@frappe.whitelist(methods=["POST"])
def generate_invigilation(roster):
	"""Build the Invigilation Roster's duties from the session's Seating Plans (COE only); returns the count."""
	from campus.examinations import invigilation

	return invigilation.generate(roster)


def exam_dues_block(student, exam_session):
	"""{blocked, amount}: the hall ticket gate. Unpaid Exam-head dues in the session's company block a hall ticket
	(never the registration itself)."""
	from campus.examinations import exam_fee

	return exam_fee.exam_dues_block(student, exam_session)


def confirm_registration(registration_name):
	"""Confirm an Exam Registration (the caller checks who may): fixes the fee and queues the invoice; returns it."""
	from campus.examinations import registration

	return registration.confirm(registration_name)


def student_registrations(student):
	"""The student's Exam Registrations of unpublished sessions as plain dicts (the caller resolves the student)."""
	from campus.examinations import registration

	return registration.student_registrations(student)
