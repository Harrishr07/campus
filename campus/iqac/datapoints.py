"""M15-01 Data points of the thin slice.

students_admitted: submitted Program Enrollments of the company in the academic year.
final_year_appeared / final_year_passed: Student Results of the company's Exam Sessions flagged `is_final_year`
whose term belongs to the academic year. A student appeared when at least one course was sat (Pass or Fail;
SA and AB rows are not sittings) and passed when, in addition, every course of the result is Pass.
Counts are per Student Result, i.e. per student per final-year session.
"""

import frappe

from campus.iqac.registry import campus_metric


def refs(doctype, names):
	return [{"doctype": doctype, "name": name} for name in names]


@campus_metric("students_admitted")
def students_admitted(company, academic_year):
	names = frappe.get_all(
		"Program Enrollment",
		{"oc_company": company, "academic_year": academic_year, "docstatus": 1},
		pluck="name",
		order_by="name",
	)
	return {"value": len(names), "records": refs("Program Enrollment", names)}


@campus_metric("final_year_appeared")
def final_year_appeared(company, academic_year):
	names = sorted(appeared_results(company, academic_year))
	return {"value": len(names), "records": refs("Student Result", names)}


@campus_metric("final_year_passed")
def final_year_passed(company, academic_year):
	outcomes = appeared_results(company, academic_year)
	names = sorted(name for name, results in outcomes.items() if set(results) == {"Pass"})
	return {"value": len(names), "records": refs("Student Result", names)}


def appeared_results(company, academic_year):
	"""{Student Result: [course results]} of the final-year results in which at least one course was sat."""
	terms = frappe.get_all("Academic Term", {"academic_year": academic_year}, pluck="name")
	sessions = frappe.get_all(
		"Exam Session", {"company": company, "is_final_year": 1, "academic_term": ["in", terms]}, pluck="name"
	)
	if not sessions:
		return {}
	results = frappe.get_all("Student Result", {"exam_session": ["in", sessions]}, pluck="name")
	rows = frappe.get_all(
		"Student Result Course",
		{"parenttype": "Student Result", "parent": ["in", results or [""]]},
		["parent", "result"],
	)
	by_result = {}
	for row in rows:
		by_result.setdefault(row.parent, []).append(row.result)
	return {name: outcomes for name, outcomes in by_result.items() if {"Pass", "Fail"} & set(outcomes)}
