"""M01-02 / M17-06 Data points, all (company, academic_year, department=None); `department` narrows by Program.department.

Thin slice: students_admitted: submitted Program Enrollments of the company in the academic year.
final_year_appeared / final_year_passed: Student Results of the company's Exam Sessions flagged `is_final_year`
whose term belongs to the academic year. A student appeared when at least one course was sat (Pass or Fail;
SA and AB rows are not sittings) and passed when, in addition, every course of the result is Pass.
Counts are per Student Result, i.e. per student per final-year session.
scholarship_govt_students / scholarship_inst_students (AQAR 5.1.1 / 5.1.2): distinct students with a sanctioned
Scholarship Application of a government / institutional scheme of the company in the academic year.

Phase 1: reserved_seats_filled / seats_earmarked_reserved: filled (submitted Program Enrollments) / sanctioned (Seat Matrix
rows) of the matrix-counted quotas in categories flagged Student Category.oc_is_reserved, as the Live Seat Matrix
report. total_students: distinct students with a submitted Program Enrollment in the year. outgoing_students:
students who left with a transfer certificate (leaving_certificate_number) dated (date_of_leaving) in the year, less
those with a submitted Admission Cancellation. programmes_offered: Programs with a Seat Matrix in the year.
courses_offered: Courses with a course Student Group (offering) in the year. mentor_ratio (NAAC 2.3.3): students of the year
per distinct active Employee who mentors (Student.oc_mentor) one of them; the records are all the students.
scholarship_beneficiaries_govt / _institution are the AQAR 5.1.1 / 5.1.2 functions above under the names the plan
uses; a department keeps the students with a submitted Program Enrollment in one of its programs.

Phase 2 (P2-T05): full_time_teachers, sanctioned_posts, phd_teachers, teacher_experience_years and student_teacher_ratio
come from campus.faculty.api (see campus/faculty/staffing.py for the counting rules); `department` is Employee.department.

Phase 2 (P2-T03): syllabus_revised_programmes (AQAR 1.1.2: distinct programmes whose curriculum an approved Syllabus Revision
proposal changed) and new_courses_introduced (AQAR 1.2.1: distinct courses named on approved New Course proposals), both
finally approved within the academic year (`department` is the proposal's department); see
campus.academic_governance.api.proposal_programmes / proposal_courses.
"""

import frappe
from frappe.utils import getdate

from campus.academic_governance import api as governance
from campus.campus_finance.api import scholarship_beneficiaries
from campus.faculty import api as faculty
from campus.iqac.registry import campus_metric


def refs(doctype, names):
	return [{"doctype": doctype, "name": name} for name in names]


@campus_metric("students_admitted")
def students_admitted(company, academic_year, department=None):
	filters = {"oc_company": company, "academic_year": academic_year, "docstatus": 1}
	names = frappe.get_all("Program Enrollment", program_filter(filters, department), pluck="name", order_by="name")
	return {"value": len(names), "records": refs("Program Enrollment", names)}


@campus_metric("final_year_appeared")
def final_year_appeared(company, academic_year, department=None):
	names = sorted(appeared_results(company, academic_year, department))
	return {"value": len(names), "records": refs("Student Result", names)}


@campus_metric("final_year_passed")
def final_year_passed(company, academic_year, department=None):
	outcomes = appeared_results(company, academic_year, department)
	names = sorted(name for name, results in outcomes.items() if set(results) == {"Pass"})
	return {"value": len(names), "records": refs("Student Result", names)}


def appeared_results(company, academic_year, department=None):
	"""{Student Result: [course results]} of the final-year results in which at least one course was sat."""
	terms = frappe.get_all("Academic Term", {"academic_year": academic_year}, pluck="name")
	sessions = frappe.get_all(
		"Exam Session",
		{"company": company, "is_final_year": 1, "status": "Published", "academic_term": ["in", terms]},
		pluck="name",
	)
	if not sessions:
		return {}
	results = frappe.get_all("Student Result", program_filter({"exam_session": ["in", sessions]}, department), pluck="name")
	rows = frappe.get_all(
		"Student Result Course",
		{"parenttype": "Student Result", "parent": ["in", results or [""]]},
		["parent", "result"],
	)
	by_result = {}
	for row in rows:
		by_result.setdefault(row.parent, []).append(row.result)
	return {name: outcomes for name, outcomes in by_result.items() if {"Pass", "Fail"} & set(outcomes)}


def scholarship_students(company, academic_year, scheme_type, department=None):
	rows = scholarship_beneficiaries(company, academic_year, scheme_type)
	if department:
		enrolled = department_students([r.student for r in rows], department)
		rows = [r for r in rows if r.student in enrolled]
	return {"value": len({r.student for r in rows}), "records": refs("Scholarship Application", sorted(r.name for r in rows))}


@campus_metric("scholarship_govt_students")
@campus_metric("scholarship_beneficiaries_govt")
def scholarship_govt_students(company, academic_year, department=None):
	return scholarship_students(company, academic_year, "Government", department)


@campus_metric("scholarship_inst_students")
@campus_metric("scholarship_beneficiaries_institution")
def scholarship_inst_students(company, academic_year, department=None):
	return scholarship_students(company, academic_year, "Institutional", department)


def department_programs(department):
	"""Programs of the department, or None when no department filter applies."""
	return frappe.get_all("Program", {"department": department}, pluck="name") if department else None


def program_filter(filters, department, fieldname="program"):
	programs = department_programs(department)
	if programs is not None:
		filters[fieldname] = ["in", programs or [""]]
	return filters


def department_students(students, department):
	"""Those of `students` with a submitted Program Enrollment in a program of `department`."""
	filters = program_filter({"student": ["in", students or [""]], "docstatus": 1}, department)
	return set(frappe.get_all("Program Enrollment", filters, pluck="student"))


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
	leavers = set(frappe.get_all("Student", {"oc_company": company, "leaving_certificate_number": ["is", "set"],
		"date_of_leaving": ["between", [getdate(start), getdate(end)]]}, pluck="name"))  # fmt: skip
	leavers -= set(frappe.get_all("Admission Cancellation", {"student": ["in", list(leavers) or [""]], "docstatus": 1}, pluck="student"))
	if department:
		leavers &= department_students(list(leavers), department)
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
	assigned = frappe.get_all("Student", {"name": ["in", students or [""]], "oc_mentor": ["is", "set"]}, pluck="oc_mentor")
	mentors = frappe.get_all("Employee", {"name": ["in", list(set(assigned)) or [""]], "status": "Active"}, pluck="name")
	value = round(len(students) / len(mentors), 2) if mentors else 0
	return {"value": value, "records": refs("Student", students)}


# P2-T05 faculty data points (NAAC 2.2.2, 2.4.1-2.4.3), computed by the Faculty module.
@campus_metric("full_time_teachers")
def full_time_teachers(company, academic_year, department=None):
	return faculty.full_time_teachers(company, academic_year, department)


@campus_metric("sanctioned_posts")
def sanctioned_posts(company, academic_year, department=None):
	return faculty.sanctioned_posts(company, academic_year, department)


@campus_metric("phd_teachers")
def phd_teachers(company, academic_year, department=None):
	return faculty.phd_teachers(company, academic_year, department)


@campus_metric("teacher_experience_years")
def teacher_experience_years(company, academic_year, department=None):
	return faculty.teacher_experience_years(company, academic_year, department)


@campus_metric("student_teacher_ratio")
def student_teacher_ratio(company, academic_year, department=None):
	return faculty.student_teacher_ratio(company, academic_year, department)


@campus_metric("syllabus_revised_programmes")
def syllabus_revised_programmes(company, academic_year, department=None):
	programmes = governance.proposal_programmes(company, academic_year, "Syllabus Revision", department)
	return {"value": len(programmes), "records": refs("Program", programmes)}


@campus_metric("new_courses_introduced")
def new_courses_introduced(company, academic_year, department=None):
	courses = governance.proposal_courses(company, academic_year, "New Course", department)
	return {"value": len(courses), "records": refs("Course", courses)}
