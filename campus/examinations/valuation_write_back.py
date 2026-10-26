"""M06-04 Final ESE marks from the Dummy Number Map to the Mark Sheet Entry, by Exam Confidential.

`write_back_pending` queues a bulk run (campus_platform bulk runner) for one session and course once every
valuation allocation of the course is Completed and every live script of the course has its final mark: a
partial write-back would let anyone watching the sheets tie the few changed rows to the few valued scripts. The job runs as the Exam Confidential user who started it,
so no examiner ever authors a mark-sheet change. A script is skipped, with the reason kept on its map row,
when the student is absent on the mark sheet or in the exam hall (an absent mark is never cleared), when the
result has been run, or when the sheet refuses the mark (e.g. the session is not in Marks Entry). The job
can be run again; written scripts are not touched twice.
"""

import frappe
from frappe import _
from frappe.utils import cstr

from campus.campus_platform.bulk import live_run, run_bulk
from campus.examinations import dummy_numbers, seating
from campus.examinations.valuation import offering_of, result_locked
from campus.examinations.valuation_access import DUMMY_NUMBER_MAP, require_confidential

RUN_TYPE = "Valuation Write-back"
HANDLER = "campus.examinations.valuation_write_back.write_back_item"
SHEET = "Mark Sheet Entry"


@frappe.whitelist(methods=["POST"])
def write_back_pending(exam_session, course):
	"""Exam Confidential: queue the write-back of the course's final marks; returns how many scripts were queued."""
	require_confidential()
	frappe.db.get_value("Exam Session", exam_session, "name", for_update=True)  # one start at a time
	statuses = frappe.get_all(
		"Valuation Allocation", {"exam_session": exam_session, "course": course}, pluck="status"
	)
	if not statuses or any(status != "Completed" for status in statuses):
		frappe.throw(
			_("Every valuation allocation of {0} must be Completed before its marks are written.").format(
				course
			)
		)
	if frappe.db.exists(
		DUMMY_NUMBER_MAP, {"exam_session": exam_session, "course": course, "void": 0, "finalised": 0}
	):
		frappe.throw(
			_("Every script of {0} must be bundled and finalised before its marks are written.").format(
				course
			)
		)
	if live_run(RUN_TYPE, exam_session=exam_session, course=course):
		frappe.throw(_("A write-back of {0} is still running.").format(course))
	names = frappe.get_all(
		DUMMY_NUMBER_MAP,
		{"exam_session": exam_session, "course": course, "finalised": 1, "ese_written": 0, "void": 0},
		pluck="name",
		order_by="dummy_number",
	)
	if names:
		run_bulk(RUN_TYPE, names, HANDLER, parameters={"exam_session": exam_session, "course": course})
	return len(names)


def write_back_item(name, run):
	"""Bulk handler (DB only, no commit): write one script's final mark; True when written."""
	row = frappe.db.get_value(
		DUMMY_NUMBER_MAP,
		name,
		[*dummy_numbers.SCRIPT_FIELDS, "finalised", "ese_written"],
		as_dict=True,
		for_update=True,
	)
	if not row or not row.finalised or row.ese_written or row.void:
		return False
	issue = write_back(row)
	frappe.db.set_value(
		DUMMY_NUMBER_MAP, name, {"ese_written": int(not issue), "write_back_issue": issue or None}
	)
	return not issue


def write_back(row):
	"""Put the final mark on the student's sheet row; returns the reason it was not written, or None."""
	if result_locked(row):
		return _("The result has been run: the mark sheet is locked.")
	if seating.absent(row.student, row.exam_session, row.course):
		return _("Marked absent in the exam hall: the absent mark is kept.")
	sheet_name = frappe.db.get_value(
		SHEET, {"exam_session": row.exam_session, "course_offering": offering_of(row)}
	)
	sheet = sheet_name and frappe.get_doc(SHEET, sheet_name)
	mark_row = sheet and next((r for r in sheet.marks if r.student == row.student), None)
	if not mark_row:
		return _("The student has no row on a Mark Sheet Entry of the course.")
	if mark_row.absent:
		return _("Marked absent on the mark sheet: the absent mark is kept.")
	mark_row.update({"ese": row.final_ese, "ese_from_valuation": 1})
	sheet.flags.valuation_write_back = True
	frappe.db.savepoint("valuation_write_back")
	try:
		sheet.save(ignore_permissions=True)
	except (frappe.ValidationError, frappe.PermissionError) as e:
		frappe.db.rollback(save_point="valuation_write_back")
		frappe.clear_messages()
		return cstr(e) or _("The mark sheet refused the mark.")
	return None
