"""M07-02 Workload rules: weekly teaching hours of a teacher against the cadre's Faculty Norm.

A teacher's workload in a term is the sum of Lecture + Tutorial + Practical hours over every submitted Course
Allocation of the term, plus the allocation being checked. Over the cadre maximum is a warning; over the maximum
plus the Faculty Norm's block margin needs a Dean override. The limits are Faculty Norm records, not constants.
"""

import frappe
from frappe.utils import flt

from campus.faculty.norms import norm_in_force

OK, WARN, BLOCK = "ok", "warn", "block"


def row_hours(row):
	return flt(row.lecture_hours) + flt(row.tutorial_hours) + flt(row.practical_hours)


def classify(total, maximum, margin):
	"""OK within the maximum, WARN above it, BLOCK above maximum + margin. No maximum set means no limit."""
	if not maximum or total <= maximum:
		return OK
	return BLOCK if total > maximum + flt(margin) else WARN


def hours_by_faculty(rows):
	totals = {}
	for row in rows:
		totals[row.faculty] = totals.get(row.faculty, 0) + row_hours(row)
	return totals


def limits(company, cadre, on_date):
	"""(minimum, maximum, margin) weekly hours of `cadre` under the Faculty Norm in force, or None without one."""
	norm = norm_in_force(company, on_date)
	rule = norm and next((r for r in norm.cadres if r.cadre == cadre), None)
	if not rule:
		return None
	return flt(rule.min_hours_per_week), flt(rule.max_hours_per_week), flt(norm.overload_block_margin_hours)


def submitted_hours(academic_term, exclude=None):
	"""{employee: weekly hours} over the submitted Course Allocations of the term, except `exclude`."""
	rows = frappe.get_all(
		"Course Allocation Row",
		filters={"parenttype": "Course Allocation", "parent": ["in", submitted_allocations(academic_term, exclude)]},
		fields=["faculty", "lecture_hours", "tutorial_hours", "practical_hours"],
	)
	return hours_by_faculty(rows)


def submitted_allocations(academic_term, exclude=None):
	filters = {"academic_term": academic_term, "docstatus": 1}
	if exclude:
		filters["name"] = ["!=", exclude]
	return frappe.get_all("Course Allocation", filters=filters, pluck="name") or [""]


def term_offerings(department, academic_term):
	"""Enabled course offerings (Student Groups) of the term for the programs of `department`."""
	programs = frappe.get_all("Program", filters={"department": department}, pluck="name") or [""]
	return frappe.get_all(
		"Student Group",
		filters={"group_based_on": "Course", "academic_term": academic_term, "program": ["in", programs], "disabled": 0},
		pluck="name",
		order_by="name",
	)
