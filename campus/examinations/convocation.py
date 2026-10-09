"""M06-07 Convocation List: the eligible graduates of a company (and programme) and their export for the university.

Eligible: a published final-year result, the programme completed with no arrear (campus.examinations.graduation),
and not already on another Convocation List. The export follows the list's column table (heading -> source). The
university's format is not known yet, so DEFAULT_COLUMNS is a placeholder the COE edits to match it. Cells that a
spreadsheet would run as a formula are neutralised.
"""

import frappe
from frappe import _
from frappe.utils.csvutils import build_csv_response

from campus.examinations import graduation_rules
from campus.examinations.graduation import final_year_students, graduate_record

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
	"""Replace the list's graduates with the eligible ones; returns their number."""
	doc = frappe.get_doc(DOCTYPE, convocation_list)
	doc.check_permission("write")
	listed = set(frappe.get_all(ROW, {"parenttype": DOCTYPE, "parent": ["!=", doc.name]}, pluck="student"))
	doc.graduates = []
	for student in final_year_students(doc.company, doc.program):
		if student in listed:
			continue
		record = graduate_record(student)
		if record.completed:
			doc.append("graduates", graduate_row(record))
	doc.save()
	return len(doc.graduates)


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
