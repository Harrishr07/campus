"""M12-02 Examinations service API. Other modules call these, never the controllers (D7)."""

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from campus.examinations import results
from campus.examinations.access import instructed_offerings, instructor_users, mentees_of, students_of  # noqa: F401  (public API)
from campus.examinations.arrears import arrear_courses  # noqa: F401  (public API)
from campus.examinations.registration_rules import TERM_KINDS  # noqa: F401  (public API)
from campus.examinations.rules import WITHDRAWAL_CODES  # noqa: F401  (public API)

# Exam registration and its fee are imported where used: they import campus_finance.api, which imports this module.


@frappe.whitelist(methods=["POST"])
def run_results(exam_session, program):
	"""Queue the Result Run for `program` in `exam_session` (COE only); returns the Bulk Run name.

	Idempotent: before publication a re-run replaces the Student Results of the session; after it, a re-run makes a
	new version of each changed result (P2-T19).
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
def fill_convocation_list(convocation_list):
	"""Fill a Convocation List with the eligible graduates (write access to it); returns their number (P2-T22)."""
	from campus.examinations import convocation

	return convocation.fill_graduates(convocation_list)


@frappe.whitelist()
def download_convocation_list(convocation_list):
	"""The Convocation List as CSV in its column format (read access to it)."""
	from campus.examinations import convocation

	convocation.download(convocation_list)


@frappe.whitelist(methods=["POST"])
def rerun_progression(progression_run):
	"""Queue a submitted Progression Run again (COE only, idempotent); returns the Bulk Run name."""
	from campus.examinations import progression

	return progression.rerun(progression_run)


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


def refresh_student_result(student, exam_session):
	"""Recompute the student's Student Result of the session when the Result Run has made one (an approved or
	cancelled exam withdrawal changes a course's code). After publication this makes a new result version."""
	if frappe.db.exists(results.RESULT, {"student": student, "exam_session": exam_session}):
		results.compute_student_result(student, exam_session)


def cia_lock_state(cia_schedule):
	"""Open before the CIA entry deadline, Unlocked inside an approved unlock window, else Locked."""
	from campus.examinations import cia

	return cia.lock_state(cia_schedule)
