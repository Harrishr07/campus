"""M12-02 Result Run: Student Results (course grades, SGPA, CGPA) from Mark Sheet Entries.

Per student and course of the session's term, the first applicable outcome wins:
SA when attendance eligibility (Student Services) is Shortage; AB when the mark row says absent;
else pass or fail by the student's Exam Rule Set and a grade from the student's Grading Scheme
(a fail is grade U, grade point 0). SGPA counts passed courses only (credits from the curriculum row of
the offering); CGPA is cumulative over the student's Student Results up to this session's term.
Re-running replaces the content of the existing Student Result in place; a Published session is refused.
"""

import frappe
from frappe import _

from campus.campus_platform.api import get_regulation, get_rule
from campus.examinations import rules
from campus.examinations.access import COE_ROLE
from campus.examinations.courses import offering_course, student_limits
from campus.student_services.api import eligibility_status, student_offerings

RUN_TYPE = "Result Run"
HANDLER = "campus.examinations.results.run_student"
RESULT = "Student Result"
SA, AB, FAIL = "SA", "AB", "U"


def start_run(exam_session, program):
	"""Queue the Result Run of `program` students for the session; returns the Bulk Run name."""
	from campus.campus_platform.bulk import run_bulk

	frappe.only_for((COE_ROLE, "System Manager"))
	session = frappe.get_doc("Exam Session", exam_session)
	session.check_permission("write")
	if session.status == "Published":
		frappe.throw(_("Results of a published Exam Session cannot be re-run."))
	if frappe.db.get_value("Program", program, "oc_company") != session.company:
		frappe.throw(_("Program {0} does not belong to {1}.").format(frappe.bold(program), frappe.bold(session.company)))
	return run_bulk(RUN_TYPE, program_students(session, program), HANDLER, parameters={"exam_session": exam_session})


def program_students(session, program):
	year = frappe.db.get_value("Academic Term", session.academic_term, "academic_year")
	return sorted(
		frappe.get_all(
			"Program Enrollment",
			{"program": program, "academic_year": year, "docstatus": 1, "oc_company": session.company},
			pluck="student",
			distinct=True,
		)
	)


def run_student(student, run):
	"""Bulk handler: (re)compute one student's Student Result for the run's session."""
	return compute_student_result(student, run.get_parameters()["exam_session"])


def compute_student_result(student, exam_session):
	"""Create or replace the Student Result of `student` in `exam_session`; returns its name."""
	session = frappe.db.get_value(
		"Exam Session", exam_session, ["company", "academic_term", "status"], as_dict=True, for_update=True
	)
	if session.status == "Published":
		frappe.throw(_("Results of a published Exam Session cannot be re-run."))
	scheme, rows = get_rule(student, "Grading Scheme"), []
	shortage = eligibility_status(student, session.academic_term) == "Shortage"
	for offering in student_offerings(student, session.academic_term):
		row = course_result(student, exam_session, offering.name, scheme, shortage)
		if row:
			rows.append(row)
	doc = result_doc(student, exam_session, session)
	doc.set("courses", rows)
	doc.sgpa = rules.sgpa([(r["credits"], r["grade_point"], r["result"] == "Pass") for r in rows])
	doc.credits_earned = sum(r["credits"] for r in rows if r["result"] == "Pass")
	doc.cgpa = cumulative_gpa(student, exam_session, session.academic_term, rows)
	doc.save(ignore_permissions=True)
	return doc.name


def result_doc(student, exam_session, session):
	name = f"SR-{exam_session}-{student}"
	if frappe.db.exists(RESULT, name):
		return frappe.get_doc(RESULT, name)
	program = frappe.db.get_value("Program Enrollment", {"student": student, "docstatus": 1}, "program")
	return frappe.get_doc(
		{
			"doctype": RESULT,
			"student": student,
			"exam_session": exam_session,
			"company": session.company,
			"academic_term": session.academic_term,
			"program": program,
			"regulation": get_regulation(student),
		}
	)


def course_result(student, exam_session, offering, scheme, shortage):
	"""The Student Result Course row of one offering, or None for a course the Result Run does not grade."""
	course = offering_course(offering)
	if not course["course_type"]:  # Internal Only: no end-semester exam
		return None
	row = {"course": course["course"], "course_offering": offering, "course_type": course["course_type"],
		"credits": course["credits"], "cia": 0, "ese": 0, "total": 0, "grade_point": 0}  # fmt: skip
	if shortage:
		return {**row, "grade": SA, "result": SA}
	marks = marks_of(student, exam_session, offering)
	if marks.absent:
		return {**row, "grade": AB, "result": AB}
	limits = student_limits(student, course)
	total = rules.total_pct(marks.cia, marks.ese, limits["cia_max"], limits["ese_max"])
	row.update(cia=marks.cia, ese=marks.ese, total=rules.round_half_up(total, 2))
	passed = rules.pass_status(
		marks.cia, marks.ese, limits["cia_max"], limits["ese_max"], limits["ese_min_pct"], limits["total_min_pct"]
	)
	if not passed:
		return {**row, "grade": FAIL, "result": "Fail"}
	letter, point = rules.grade(total, [g.as_dict() for g in scheme.grades])
	return {**row, "grade": letter, "grade_point": point, "result": "Pass"}


def marks_of(student, exam_session, offering):
	sheet = frappe.db.get_value("Mark Sheet Entry", {"exam_session": exam_session, "course_offering": offering})
	marks = sheet and frappe.db.get_value(
		"Mark Sheet Entry Row",
		{"parent": sheet, "parenttype": "Mark Sheet Entry", "student": student},
		["cia", "ese", "absent"],
		as_dict=True,
	)
	if not marks:
		frappe.throw(_("No marks entered for {0} in {1}.").format(frappe.bold(student), frappe.bold(offering)))
	return marks


def cumulative_gpa(student, exam_session, term, rows):
	"""CGPA over this result's `rows` and the student's other Student Results of terms starting no later than `term`."""
	start = frappe.db.get_value("Academic Term", term, "term_start_date")
	earlier = []
	for result in frappe.get_all(RESULT, {"student": student, "exam_session": ["!=", exam_session]}, ["name", "academic_term"]):
		began = frappe.db.get_value("Academic Term", result.academic_term, "term_start_date")
		if began <= start:
			earlier.append((began, result.name))
	attempts = []
	for _began, name in sorted(earlier):
		attempts += [
			(c.course, c.credits, c.grade_point, c.result == "Pass") for c in frappe.get_doc(RESULT, name).courses
		]
	attempts += [(r["course"], r["credits"], r["grade_point"], r["result"] == "Pass") for r in rows]
	return rules.cgpa(attempts)
