"""M03-01 Data for the Curriculum Structure print format (semester-wise L-T-P-C, category totals)."""

import frappe
from frappe.utils import flt

from campus.curriculum.credit_rules import category_totals


def curriculum_structure(curriculum):
	"""Semesters with their rows and totals, plus per-category totals against the minimums."""
	semesters = {}
	for row in sorted(curriculum.courses, key=lambda r: (r.semester, r.idx)):
		semester = semesters.setdefault(
			row.semester, {"semester": row.semester, "rows": [], "lecture": 0, "tutorial": 0, "practical": 0, "credits": 0}
		)
		semester["rows"].append(row)
		for key, value in (("lecture", row.lecture_periods), ("tutorial", row.tutorial_periods), ("practical", row.practical_periods), ("credits", row.credits)):
			semester[key] = flt(semester[key] + flt(value), 2)
	titles = course_titles(curriculum)
	for semester in semesters.values():
		for row in semester["rows"]:
			row.course_title = titles.get(row.course, row.course)
	totals, counted = category_totals([(r.category, r.credits) for r in curriculum.courses], counts_toward(curriculum))
	minimums = {r.category: r.min_credits for r in curriculum.category_requirements}
	categories = [
		{"category": category, "credits": totals.get(category, 0), "minimum": minimums.get(category)}
		for category in sorted(set(totals) | set(minimums))
	]
	return {"semesters": list(semesters.values()), "categories": categories, "total_credits": counted}


def course_titles(curriculum):
	names = {row.course for row in curriculum.courses}
	return dict(frappe.get_all("Course", filters={"name": ["in", list(names)]}, fields=["name", "course_name"], as_list=True))


def counts_toward(curriculum):
	categories = {row.category for row in curriculum.courses}
	return dict(
		frappe.get_all(
			"Course Category", filters={"name": ["in", list(categories)]}, fields=["name", "counts_toward_credits"], as_list=True
		)
	)
