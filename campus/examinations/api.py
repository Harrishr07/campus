"""M12-02 Examinations service API. Other modules call these, never the controllers (D7)."""

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from campus.examinations import results


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
