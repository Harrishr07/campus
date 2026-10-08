"""M15-01 Data points of the thin slice.

students_admitted: submitted Program Enrollments of the company in the academic year.
final_year_appeared / final_year_passed: Student Results of the company's Exam Sessions flagged `is_final_year`
whose term belongs to the academic year. A student appeared when at least one course was sat (Pass or Fail;
SA and AB rows are not sittings) and passed when, in addition, every course of the result is Pass.
Counts are per Student Result, i.e. per student per final-year session.
scholarship_govt_students / scholarship_inst_students (AQAR 5.1.1 / 5.1.2): distinct students with a sanctioned
Scholarship Application of a government / institutional scheme of the company in the academic year.

Phase 1 data points, all (company, academic_year, department=None); `department` narrows by Program.department:
reserved_seats_filled / seats_earmarked_reserved: filled (submitted Program Enrollments) / sanctioned (Seat Matrix
rows) of the matrix-counted quotas in categories flagged Student Category.oc_is_reserved, as the Live Seat Matrix
report. total_students: distinct students with a submitted Program Enrollment in the year. outgoing_students:
students whose date_of_leaving falls in the year. programmes_offered: Programs with a Seat Matrix in the year.
courses_offered: Courses with a course Student Group (offering) in the year. mentor_ratio: students of the year
with a mentor (Student.oc_mentor) per distinct mentor. scholarship_beneficiaries_govt / _institution are the
AQAR 5.1.1 / 5.1.2 functions above under the names the plan uses.
"""

import frappe
from frappe.utils import getdate

from campus.campus_finance.api import scholarship_beneficiaries
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
		"Exam Session",
		{"company": company, "is_final_year": 1, "status": "Published", "academic_term": ["in", terms]},
		pluck="name",
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


def scholarship_students(company, academic_year, scheme_type):
	rows = scholarship_beneficiaries(company, academic_year, scheme_type)
	return {"value": len({r.student for r in rows}), "records": refs("Scholarship Application", sorted(r.name for r in rows))}


@campus_metric("scholarship_govt_students")
@campus_metric("scholarship_beneficiaries_govt")
def scholarship_govt_students(company, academic_year, department=None):
	return scholarship_students(company, academic_year, "Government")


@campus_metric("scholarship_inst_students")
@campus_metric("scholarship_beneficiaries_institution")
def scholarship_inst_students(company, academic_year, department=None):
	return scholarship_students(company, academic_year, "Institutional")


def department_programs(department):
	"""Programs of the department, or None when no department filter applies."""
	return frappe.get_all("Program", {"department": department}, pluck="name") if department else None


def program_filter(filters, department, fieldname="program"):
	programs = department_programs(department)
	if programs is not None:
		filters[fieldname] = ["in", programs or [""]]
	return filters


def reserved_categories():
	return frappe.get_all("Student Category", {"oc_is_reserved": 1}, pluck="name")


def counted_quotas():
	return [q.name for q in frappe.get_all("Admission Quota", ["name", "is_supernumerary", "counts_in_seat_matrix"])
		if not q.is_supernumerary and q.counts_in_seat_matrix]  # fmt: skip


@campus_metric("reserved_seats_filled")
def reserved_seats_filled(company, academic_year, department=None):
	filters = {
		"oc_company": company, "academic_year": academic_year, "docstatus": 1,
		"student_category": ["in", reserved_categories() or [""]], "oc_admission_quota": ["in", counted_quotas() or [""]],
	}  # fmt: skip
	names = frappe.get_all("Program Enrollment", program_filter(filters, department), pluck="name", order_by="name")
	return {"value": len(names), "records": refs("Program Enrollment", names)}


@campus_metric("seats_earmarked_reserved")
def seats_earmarked_reserved(company, academic_year, department=None):
	matrices = frappe.get_all(
		"Seat Matrix", program_filter({"company": company, "academic_year": academic_year}, department), pluck="name"
	)
	rows = frappe.get_all(
		"Seat Matrix Row",
		{"parent": ["in", matrices or [""]], "category": ["in", reserved_categories() or [""]],
			"quota": ["in", counted_quotas() or [""]]},
		["parent", "sanctioned"], limit=0,
	)  # fmt: skip
	return {"value": sum(r.sanctioned or 0 for r in rows), "records": refs("Seat Matrix", sorted({r.parent for r in rows}))}


def year_students(company, academic_year, department=None):
	"""Distinct students with a submitted Program Enrollment of the company in the year."""
	filters = {"oc_company": company, "academic_year": academic_year, "docstatus": 1}
	return sorted(set(frappe.get_all("Program Enrollment", program_filter(filters, department), pluck="student")))


@campus_metric("total_students")
def total_students(company, academic_year, department=None):
	students = year_students(company, academic_year, department)
	return {"value": len(students), "records": refs("Student", students)}


@campus_metric("outgoing_students")
def outgoing_students(company, academic_year, department=None):
	start, end = frappe.db.get_value("Academic Year", academic_year, ["year_start_date", "year_end_date"])
	leavers = frappe.get_all(
		"Student", {"oc_company": company, "date_of_leaving": ["between", [getdate(start), getdate(end)]]}, pluck="name"
	)
	if department:
		enrolled = frappe.get_all(
			"Program Enrollment",
			program_filter({"student": ["in", leavers or [""]], "docstatus": 1}, department),
			pluck="student",
		)
		leavers = [s for s in leavers if s in set(enrolled)]
	return {"value": len(leavers), "records": refs("Student", sorted(leavers))}


@campus_metric("programmes_offered")
def programmes_offered(company, academic_year, department=None):
	rows = frappe.get_all(
		"Seat Matrix", program_filter({"company": company, "academic_year": academic_year}, department), pluck="program"
	)
	programs = sorted(set(rows))
	return {"value": len(programs), "records": refs("Program", programs)}


@campus_metric("courses_offered")
def courses_offered(company, academic_year, department=None):
	filters = {"oc_company": company, "academic_year": academic_year, "group_based_on": "Course", "disabled": 0}
	courses = sorted(set(frappe.get_all("Student Group", program_filter(filters, department), pluck="course")) - {None})
	return {"value": len(courses), "records": refs("Course", courses)}


@campus_metric("mentor_ratio")
def mentor_ratio(company, academic_year, department=None):
	students = year_students(company, academic_year, department)
	rows = frappe.get_all(
		"Student", {"name": ["in", students or [""]], "oc_mentor": ["is", "set"]}, ["name", "oc_mentor"], order_by="name"
	)
	mentors = {r.oc_mentor for r in rows}
	value = round(len(rows) / len(mentors), 2) if mentors else 0
	return {"value": value, "records": refs("Student", [r.name for r in rows])}
