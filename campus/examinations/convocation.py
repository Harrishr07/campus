"""M06-07, M05-09 Convocation List: the eligible graduates of a company (and programme) and their export for the
university.

Eligible: a published final-year result, the programme completed with no arrear (campus.examinations.graduation),
and not already on another Convocation List. Listing moves an Active graduate to Study Completed and then Award
Eligible (lifecycle, effective the convocation date once it has passed, else the day listed); a refill that drops a
student undoes those steps. Mark Graduated, on or after the convocation date, moves the Award Eligible graduates
to Graduated from that date (COE) and reports the ones the lifecycle refuses. The export follows the list's column table (heading -> source). The
university's format is not known yet, so DEFAULT_COLUMNS is a placeholder the COE edits to match it. Cells that a
spreadsheet would run as a formula are neutralised.
"""

import frappe
from frappe import _
from frappe.utils import getdate, strip_html, today
from frappe.utils.csvutils import build_csv_response

from campus.examinations import graduation_rules
from campus.examinations.access import COE_ROLE
from campus.examinations.graduation import final_year_students, graduate_record
from campus.student_services.api import (
	ACTIVE,
	AWARD_ELIGIBLE,
	GRADUATED,
	STUDY_COMPLETED,
	last_change_date,
	lifecycle_status,
	revert_transition,
	transition,
)

DOCTYPE = "Convocation List"
ROW = "Convocation List Graduate"
# Placeholder export format (heading, source); see the module docstring.
DEFAULT_COLUMNS = [
	("Register Number", "Register Number"), ("Student Name", "Student Name"), ("Date of Birth", "Date of Birth"),
	("Programme", "Program"), ("Regulation", "Regulation"), ("CGPA", "CGPA"), ("Percentage", "Percentage"),
	("Classification", "Classification"), ("Completion Term", "Completion Term"),
]  # fmt: skip
SOURCES = {
	"Register Number": "register_no", "Student": "student", "Student Name": "student_name", "Date of Birth": "date_of_birth",
	"Program": "program", "Regulation": "regulation", "CGPA": "cgpa", "Percentage": "percentage",
	"Classification": "classification", "Variant": "variant", "Completion Term": "completion_term",
}  # fmt: skip


def fill_graduates(convocation_list):
	"""Replace the list's graduates with the eligible ones; returns their number. A student no longer listed goes
	back from Award Eligible / Study Completed, while that is still their latest change."""
	doc = frappe.get_doc(DOCTYPE, convocation_list)
	doc.check_permission("write")
	listed = set(frappe.get_all(ROW, {"parenttype": DOCTYPE, "parent": ["!=", doc.name]}, pluck="student"))
	before = {row.student for row in doc.graduates}
	doc.graduates = []
	for student in final_year_students(doc.company, doc.program):
		if student in listed:
			continue
		record = graduate_record(student)
		if record.completed:
			doc.append("graduates", graduate_row(record))
	doc.save()
	for row in doc.graduates:
		record_award_eligible(row, doc)
	for student in sorted(before - {row.student for row in doc.graduates}):
		undo_award_eligible(student, doc)
	return len(doc.graduates)


def record_award_eligible(row, doc):
	"""Active -> Study Completed -> Award Eligible, dated by listing_date; a graduate already past either step is
	left as they are."""
	if lifecycle_status(row.student) == ACTIVE:
		reason = _("Programme completed in {0}").format(row.completion_term) if row.completion_term else _("Programme completed")
		transition(row.student, STUDY_COMPLETED, listing_date(doc, row.student), reason, doc)
	if lifecycle_status(row.student) == STUDY_COMPLETED:
		transition(row.student, AWARD_ELIGIBLE, listing_date(doc, row.student), _("Listed for convocation on {0}").format(doc.name), doc)


def listing_date(doc, student):
	"""The list's convocation date when it has passed, else today; never before the student's last change."""
	day = min(getdate(doc.convocation_date or today()), getdate(today()))
	last = last_change_date(student)
	return max(day, getdate(last)) if last else day


def undo_award_eligible(student, doc):
	reason = _("No longer on Convocation List {0}").format(doc.name)
	while revert_transition(doc, reason, student=student, statuses=(AWARD_ELIGIBLE, STUDY_COMPLETED)):
		pass


def graduate(convocation_list):
	"""Record the list's Award Eligible graduates as Graduated from the convocation date. Returns {graduated,
	refused: [{student, reason}]}: a graduate the lifecycle refuses (e.g. a later change) does not stop the rest."""
	frappe.only_for((COE_ROLE, "System Manager"))
	doc = frappe.get_doc(DOCTYPE, convocation_list)
	doc.check_permission("write")
	if not doc.convocation_date or getdate(doc.convocation_date) > getdate(today()):
		frappe.throw(_("Set the convocation date; graduates are recorded on or after it."))
	graduated, refused = 0, []
	for row in doc.graduates:
		if lifecycle_status(row.student) != AWARD_ELIGIBLE:
			continue
		messages = len(frappe.local.message_log)
		try:
			transition(row.student, GRADUATED, doc.convocation_date, _("Degree conferred at convocation {0}").format(doc.name), doc)
			graduated += 1
		except frappe.ValidationError as error:  # refused before anything is written
			del frappe.local.message_log[messages:]
			refused.append({"student": row.student, "reason": strip_html(str(error))})
	return {"graduated": graduated, "refused": refused}


def graduate_row(record):
	return {
		"student": record.student, "student_name": record.student_name, "register_no": record.register_no,
		"date_of_birth": record.date_of_birth, "program": record.program, "regulation": record.regulation,
		"cgpa": record.cgpa, "percentage": record.percentage, "classification": record.classification,
		"variant": record.class_variant or record.variant, "completion_term": record.completion_term,
	}  # fmt: skip


def export_rows(convocation_list):
	"""[headings, *graduate rows] of the list in its column format."""
	doc = frappe.get_doc(DOCTYPE, convocation_list)
	doc.check_permission("read")
	columns = [(c.heading, SOURCES[c.source]) for c in doc.columns]
	if not columns:
		frappe.throw(_("Set the export columns of {0} first.").format(doc.name))
	rows = [[graduation_rules.csv_cell(heading) for heading, _field in columns]]
	for graduate in doc.graduates:
		rows.append([graduation_rules.csv_cell(graduate.get(field)) for _heading, field in columns])
	return rows


def download(convocation_list):
	build_csv_response(export_rows(convocation_list), convocation_list)
