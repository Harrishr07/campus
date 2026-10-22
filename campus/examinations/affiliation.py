"""M06-10 Affiliated mode: whose end-semester examinations a student writes - the college's (Autonomous, the default)
or the affiliating university's (Affiliated).

A student's mode is the Examination Mode of their regulation's Exam Rule Set, else their college's (Institution
Profile), else Autonomous. An Exam Session carries its own mode (set once): an Affiliated session is the university's
examination of the term. Exam registration puts a student only in a session of their own mode; the Result Run and
Publish Results refuse an Affiliated session and leave Affiliated students out of an Autonomous one. CIA stays the
college's in both modes; in Affiliated mode it is exported to the university (campus.examinations.university_export)
and the university's results come back through campus.examinations.university_import.

Setup: the Student field oc_university_register_no (the university's register number, unique) and one placeholder
University Exam Format per direction, to be replaced with the university's agreed format.
"""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from campus.campus_platform.api import get_regulation

AUTONOMOUS, AFFILIATED = "Autonomous", "Affiliated"
UNIVERSITY_REGISTER_FIELD = "oc_university_register_no"
PLACEHOLDER_UNIVERSITY = "Affiliating University"
PLACEHOLDER_FORMATS = {
	"Export": (
		"Placeholder registration export - replace with the university's agreed format",
		["University Register No", "Student Name", "Program", "Course Code", "Registration Type", "CIA", "CIA Max"],
	),
	"Import": (
		"Placeholder result import - replace with the university's agreed format",
		["University Register No", "Course Code", "Grade", "Result", "ESE", "Total"],
	),
}


def examination_mode(student):
	"""Autonomous or Affiliated: whose end-semester examinations `student` writes (see the module docstring)."""
	return examination_modes({student: get_regulation(student)})[student]


def examination_modes(regulations):
	"""{student: mode} for `regulations` ({student: regulation or None}), read in bulk."""
	students = list(regulations)
	rule_modes = dict(
		frappe.get_all(
			"Exam Rule Set", {"regulation": ["in", [r for r in regulations.values() if r] or [""]]},
			["regulation", "examination_mode"], as_list=True,
		)
	)  # fmt: skip
	companies = dict(frappe.get_all("Student", {"name": ["in", students or [""]]}, ["name", "oc_company"], as_list=True))
	college_modes = dict(
		frappe.get_all("Institution Profile", {"name": ["in", list(set(companies.values())) or [""]]}, ["name", "examination_mode"], as_list=True)
	)
	return {
		student: rule_modes.get(regulation) or college_modes.get(companies.get(student)) or AUTONOMOUS
		for student, regulation in regulations.items()
	}


def session_mode(exam_session):
	return frappe.db.get_value("Exam Session", exam_session, "examination_mode") or AUTONOMOUS


def refuse_affiliated_session(exam_session, action):
	"""Refuse `action` (the Result Run, publication) on an Affiliated session: the university grades and publishes it."""
	if session_mode(exam_session) == AFFILIATED:
		frappe.throw(
			_("{0} is an Affiliated session: the university conducts its examinations, so {1} is not used. Import the university's results instead.").format(
				frappe.bold(exam_session), action
			),
			title=_("Affiliated mode"),
		)


# ---- setup ------------------------------------------------------------------------------------


def setup_affiliation():
	create_custom_fields({"Student": student_fields()}, update=True)
	seed_placeholder_formats()


def student_fields():
	return [
		{
			"fieldname": UNIVERSITY_REGISTER_FIELD, "label": "University Register No", "fieldtype": "Data", "insert_after": "oc_register_no",
			"unique": 1, "no_copy": 1, "search_index": 1, "module": "Examinations",
			"description": "The register number the affiliating university gave the student (Affiliated mode exports and result imports).",
		}
	]  # fmt: skip


def seed_placeholder_formats():
	"""One placeholder format per direction, columns mapped to themselves; an existing (possibly edited) one stays."""
	for direction, (name, sources) in PLACEHOLDER_FORMATS.items():
		if frappe.db.exists("University Exam Format", name):
			continue
		frappe.get_doc(
			{
				"doctype": "University Exam Format", "format_name": name, "university": PLACEHOLDER_UNIVERSITY, "direction": direction,
				"file_type": "CSV", "header_row": 1, "date_format": "dd-mm-yyyy",
				"columns": [{"heading": source, "source": source} for source in sources],
				"notes": "Placeholder only: the official format is the university's. Replace the columns and code mappings with the agreed ones.",
			}
		).insert(ignore_permissions=True)  # fmt: skip
