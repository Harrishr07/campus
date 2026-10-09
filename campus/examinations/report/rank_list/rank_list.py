"""M17-06 Rank List: per program, the students of a released exam session whose latest, ratified result is a Pass (no course
failed or outstanding in the session), ranked by SGPA (or CGPA) highest first; equal scores share a rank.

Limited to the companies the user is permitted for and to the results the user may read."""

import frappe
from frappe import _

from campus.examinations import coe_report_rules as rules
from campus.examinations import coe_reports

BASES = {"SGPA": "sgpa", "CGPA": "cgpa"}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	ok = coe_reports.in_scope(filters.company) and filters.exam_session
	return columns(), data(filters) if ok else []


def columns():
	return [
		{"fieldname": "program", "label": _("Program"), "fieldtype": "Link", "options": "Program", "width": 180},
		{"fieldname": "rank", "label": _("Rank"), "fieldtype": "Int", "width": 70},
		{"fieldname": "student", "label": _("Student"), "fieldtype": "Link", "options": "Student", "width": 150},
		{"fieldname": "student_name", "label": _("Student Name"), "fieldtype": "Data", "width": 180},
		{"fieldname": "sgpa", "label": _("SGPA"), "fieldtype": "Float", "precision": 2, "width": 90},
		{"fieldname": "cgpa", "label": _("CGPA"), "fieldtype": "Float", "precision": 2, "width": 90},
	]  # fmt: skip


def data(filters):
	if filters.exam_session not in {s.name for s in coe_reports.released_sessions(filters.company)}:
		return []  # another college's, unpublished or still embargoed
	basis = BASES.get(filters.basis, "sgpa")
	programs = [filters.program] if filters.program else None
	results = [
		r for r in coe_reports.published_results([filters.exam_session], programs, lister=frappe.get_list) if r.result == "Pass"
	]  # fmt: skip
	by_program = {}
	for result in results:
		by_program.setdefault(result.program, []).append(result)
	out = []
	for program in sorted(by_program, key=lambda p: p or ""):
		ranked = sorted(by_program[program], key=lambda r: (-(r[basis] or 0), r.student))
		for rank, result in zip(rules.competition_ranks([r[basis] or 0 for r in ranked]), ranked):
			out.append(
				{"program": program, "rank": rank, "student": result.student, "student_name": result.student_name,
				"sgpa": result.sgpa, "cgpa": result.cgpa}
			)  # fmt: skip
	return out
