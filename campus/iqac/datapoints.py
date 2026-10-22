"""M01-02 / M17-06 Data points, all (company, academic_year, department=None); `department` narrows by Program.department.

Thin slice: students_admitted: submitted Program Enrollments of the company in the academic year.
final_year_appeared / final_year_passed: Student Results of the company's released (publish_at passed) Exam Sessions flagged `is_final_year`
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

Phase 2 (P2-T09): fdp_teachers (NAAC 6.3.4: distinct teachers present at an FDP Training Event started in the year) and
teachers_financially_supported (NAAC 6.3.2: distinct teachers with a verified Conference / Membership achievement in the year
that has a financial support amount), see campus/faculty/development.py.

Phase 2 (P2-T03): syllabus_revised_programmes (AQAR 1.1.2: distinct programmes whose curriculum an approved Syllabus Revision
proposal changed) and new_courses_introduced (AQAR 1.2.1: distinct courses named on approved New Course proposals), both
finally approved within the academic year (`department` is the proposal's department); see
campus.academic_governance.api.proposal_programmes / proposal_courses.

Phase 2 (P2-T20): evaluation_grievances (AQAR 2.5.2): distinct students with a submitted Revaluation or Review
application in the company's published Exam Sessions of the academic year (a photocopy request alone is not a
grievance); `department` narrows by the application's program; see campus.examinations.api.evaluation_grievances.

Phase 2 (P2-T24): students_appeared, pass_percentage (AQAR 2.6.3) and days_exam_to_result (AQAR 2.5.1) read the latest,
ratified results of the year's published sessions, as the COE reports do; see campus/examinations/coe_reports.py.

Phase 3 (P3-T21): publications_published (NIRF), ugc_care_papers (AQAR 3.4.3), books_and_chapters (AQAR 3.4.4), publication_citations
(AQAR 3.4.5), publication_h_index (AQAR 3.4.6) and patents_filed / patents_published / patents_granted (AQAR 3.3, NIRF IPR) count the
year's publications (by publication date) and patents (by the date of the stage), each once for the institution; see
campus/research/publications.py for the counting rules. citations and the h-index cover a window of academic years ending with the one reported; `department` narrows to the department's
teachers' work.
"""

import frappe
from frappe.utils import getdate

from campus.academic_governance import api as governance
from campus.campus_finance.api import scholarship_beneficiaries
from campus.examinations import api as exams
from campus.faculty import api as faculty
from campus.iqac.registry import campus_metric
from campus.research import api as research


def refs(doctype, names):
	return [{"doctype": doctype, "name": name} for name in names]


@campus_metric("students_admitted", "Admissions", "Students with a submitted Program Enrollment in the academic year")
def students_admitted(company, academic_year, department=None):
	filters = {"oc_company": company, "academic_year": academic_year, "docstatus": 1}
	names = frappe.get_all("Program Enrollment", program_filter(filters, department), pluck="name", order_by="name")
	return {"value": len(names), "records": refs("Program Enrollment", names)}


@campus_metric("final_year_appeared", "Examinations", "Final-year students who sat at least one course in the published final-year sessions")
def final_year_appeared(company, academic_year, department=None):
	names = sorted(appeared_results(company, academic_year, department))
	return {"value": len(names), "records": refs("Student Result", names)}


@campus_metric("final_year_passed", "Examinations", "Final-year students who appeared and passed every course")
def final_year_passed(company, academic_year, department=None):
	outcomes = appeared_results(company, academic_year, department)
	names = sorted(name for name, results in outcomes.items() if set(results) == {"Pass"})
	return {"value": len(names), "records": refs("Student Result", names)}


def appeared_results(company, academic_year, department=None):
	"""{Student Result: [course results]} of the final-year results in which at least one course was sat."""
	sessions = exams.released_sessions(company, academic_year, final_year=True)  # Published, publish_at passed
	if not sessions:
		return {}
	results = frappe.get_all(
		"Student Result", program_filter({"exam_session": ["in", sessions], "is_latest": 1}, department), pluck="name"
	)  # the latest version of each result (P2-T19)
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


@campus_metric("scholarship_govt_students", "Campus Finance", "Distinct students with a sanctioned government scholarship (AQAR 5.1.1)")
@campus_metric("scholarship_beneficiaries_govt", "Campus Finance", "Distinct students with a sanctioned government scholarship (AQAR 5.1.1)")
def scholarship_govt_students(company, academic_year, department=None):
	return scholarship_students(company, academic_year, "Government", department)


@campus_metric("scholarship_inst_students", "Campus Finance", "Distinct students with a sanctioned institutional scholarship (AQAR 5.1.2)")
@campus_metric("scholarship_beneficiaries_institution", "Campus Finance", "Distinct students with a sanctioned institutional scholarship (AQAR 5.1.2)")
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


@campus_metric("reserved_seats_filled", "Admissions", "Seats filled in reserved categories")
def reserved_seats_filled(company, academic_year, department=None):
	filters = {
		"oc_company": company, "academic_year": academic_year, "docstatus": 1,
		"student_category": ["in", reserved_categories() or [""]], "oc_admission_quota": ["in", counted_quotas() or [""]],
	}  # fmt: skip
	names = frappe.get_all("Program Enrollment", program_filter(filters, department), pluck="name", order_by="name")
	return {"value": len(names), "records": refs("Program Enrollment", names)}


@campus_metric("seats_earmarked_reserved", "Admissions", "Seats sanctioned for reserved categories")
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


@campus_metric("total_students", "Admissions", "Distinct students with a submitted Program Enrollment in the year")
def total_students(company, academic_year, department=None):
	students = year_students(company, academic_year, department)
	return {"value": len(students), "records": refs("Student", students)}


@campus_metric("outgoing_students", "Student Services", "Students who left with a transfer certificate in the year, less cancelled admissions")
def outgoing_students(company, academic_year, department=None):
	start, end = frappe.db.get_value("Academic Year", academic_year, ["year_start_date", "year_end_date"])
	leavers = set(frappe.get_all("Student", {"oc_company": company, "leaving_certificate_number": ["is", "set"],
		"date_of_leaving": ["between", [getdate(start), getdate(end)]]}, pluck="name"))  # fmt: skip
	leavers -= set(frappe.get_all("Admission Cancellation", {"student": ["in", list(leavers) or [""]], "docstatus": 1}, pluck="student"))
	if department:
		leavers &= department_students(list(leavers), department)
	return {"value": len(leavers), "records": refs("Student", sorted(leavers))}


@campus_metric("programmes_offered", "Admissions", "Programs with a Seat Matrix in the year")
def programmes_offered(company, academic_year, department=None):
	rows = frappe.get_all(
		"Seat Matrix", program_filter({"company": company, "academic_year": academic_year}, department), pluck="program"
	)
	programs = sorted(set(rows))
	return {"value": len(programs), "records": refs("Program", programs)}


@campus_metric("courses_offered", "Curriculum", "Courses with a course Student Group in the year")
def courses_offered(company, academic_year, department=None):
	filters = {"oc_company": company, "academic_year": academic_year, "group_based_on": "Course", "disabled": 0}
	courses = sorted(set(frappe.get_all("Student Group", program_filter(filters, department), pluck="course")) - {None})
	return {"value": len(courses), "records": refs("Course", courses)}


@campus_metric("mentor_ratio", "Student Services", "Students per active mentor (NAAC 2.3.3)")
def mentor_ratio(company, academic_year, department=None):
	students = year_students(company, academic_year, department)
	assigned = frappe.get_all("Student", {"name": ["in", students or [""]], "oc_mentor": ["is", "set"]}, pluck="oc_mentor")
	mentors = frappe.get_all("Employee", {"name": ["in", list(set(assigned)) or [""]], "status": "Active"}, pluck="name")
	value = round(len(students) / len(mentors), 2) if mentors else 0
	return {"value": value, "records": refs("Student", students)}


# P2-T05 faculty data points (NAAC 2.2.2, 2.4.1-2.4.3), computed by the Faculty module.
@campus_metric("full_time_teachers", "Faculty", "Full-time teachers in the year (NAAC 2.4.1)")
def full_time_teachers(company, academic_year, department=None):
	return faculty.full_time_teachers(company, academic_year, department)


@campus_metric("sanctioned_posts", "Faculty", "Sanctioned teaching posts in the year")
def sanctioned_posts(company, academic_year, department=None):
	return faculty.sanctioned_posts(company, academic_year, department)


@campus_metric("phd_teachers", "Faculty", "Teachers with a Ph.D. (NAAC 2.4.3)")
def phd_teachers(company, academic_year, department=None):
	return faculty.phd_teachers(company, academic_year, department)


@campus_metric("teacher_experience_years", "Faculty", "Teaching experience of the full-time teachers in years (NAAC 2.4.2)")
def teacher_experience_years(company, academic_year, department=None):
	return faculty.teacher_experience_years(company, academic_year, department)


@campus_metric("student_teacher_ratio", "Faculty", "Students per full-time teacher (NAAC 2.2.2)")
def student_teacher_ratio(company, academic_year, department=None):
	return faculty.student_teacher_ratio(company, academic_year, department)


# P2-T09 faculty development data points (NAAC 6.3.4 FDPs, 6.3.2 conference support).
@campus_metric("fdp_teachers", "Faculty", "Distinct teachers present at a Faculty Development Programme in the year (NAAC 6.3.4)")
def fdp_teachers(company, academic_year, department=None):
	return faculty.fdp_teachers(company, academic_year, department)


@campus_metric("teachers_financially_supported", "Faculty", "Teachers financially supported for conferences or memberships (NAAC 6.3.2)")
def teachers_financially_supported(company, academic_year, department=None):
	return faculty.teachers_financially_supported(company, academic_year, department)


@campus_metric("syllabus_revised_programmes", "Academic Governance", "Programmes whose syllabus was revised by an approved proposal (AQAR 1.1.2)")
def syllabus_revised_programmes(company, academic_year, department=None):
	programmes = governance.proposal_programmes(company, academic_year, "Syllabus Revision", department)
	return {"value": len(programmes), "records": refs("Program", programmes)}


@campus_metric("new_courses_introduced", "Academic Governance", "New courses introduced by approved proposals (AQAR 1.2.1)")
def new_courses_introduced(company, academic_year, department=None):
	courses = governance.proposal_courses(company, academic_year, "New Course", department)
	return {"value": len(courses), "records": refs("Course", courses)}


@campus_metric("evaluation_grievances", "Examinations", "Students with a revaluation or review application in the year's published exam sessions (AQAR 2.5.2)")
def evaluation_grievances(company, academic_year, department=None):
	return exams.evaluation_grievances(company, academic_year, department_programs(department))


# P2-T24 COE data points (AQAR 2.5.1, 2.6.3 and the 2.5.2 denominator), see campus.examinations.coe_reports.
@campus_metric("students_appeared", "Examinations", "Distinct students who sat at least one course in the year's published exam sessions")
def students_appeared(company, academic_year, department=None):
	return exams.students_appeared(company, academic_year, department_programs(department))


@campus_metric("pass_percentage", "Examinations", "Final-year results that passed every course, as % of those that appeared (AQAR 2.6.3)")
def pass_percentage(company, academic_year, department=None):
	return exams.pass_percentage(company, academic_year, department_programs(department))


@campus_metric("days_exam_to_result", "Examinations", "Average days from the last exam to the publication of results (AQAR 2.5.1)")
def days_exam_to_result(company, academic_year, department=None):
	return exams.days_exam_to_result(company, academic_year, department_programs(department))


# P3-T21 research output data points (AQAR 3.3, 3.4.3-3.4.6, NIRF IPR and publications), see campus.research.publications.
@campus_metric("publications_published", "Research", "Distinct publications dated in the year (NIRF publications)")
def publications_published(company, academic_year, department=None):
	return research.publications_published(company, academic_year, department)


@campus_metric("ugc_care_papers", "Research", "Journal articles of the year in UGC-CARE listed journals (AQAR 3.4.3)")
def ugc_care_papers(company, academic_year, department=None):
	return research.ugc_care_papers(company, academic_year, department)


@campus_metric("books_and_chapters", "Research", "Books, book chapters and conference papers of the year (AQAR 3.4.4)")
def books_and_chapters(company, academic_year, department=None):
	return research.books_and_chapters(company, academic_year, department)


@campus_metric("publication_citations", "Research", "Citations of the publications of the last N academic years, N in Research Settings (AQAR 3.4.5)")
def publication_citations(company, academic_year, department=None):
	return research.publication_citations(company, academic_year, department)


@campus_metric("publication_h_index", "Research", "h-index of the publications of the last N academic years, N in Research Settings (AQAR 3.4.6)")
def publication_h_index(company, academic_year, department=None):
	return research.publication_h_index(company, academic_year, department)


@campus_metric("patents_filed", "Research", "Patents filed in the year (AQAR 3.3, NIRF IPR)")
def patents_filed(company, academic_year, department=None):
	return research.patents_filed(company, academic_year, department)


@campus_metric("patents_published", "Research", "Patents published in the year (NIRF IPR)")
def patents_published(company, academic_year, department=None):
	return research.patents_published(company, academic_year, department)


@campus_metric("patents_granted", "Research", "Patents granted in the year (AQAR 3.3, NIRF IPR)")
def patents_granted(company, academic_year, department=None):
	return research.patents_granted(company, academic_year, department)
