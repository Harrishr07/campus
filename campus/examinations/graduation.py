"""M06-07, M05-03 Graduate record: a student's consolidated result from published results only, the source of the
consolidated grade sheet, provisional and degree certificates, degree data sheet, transcript, Convocation List and
Progression Run.

Published means the latest, ratified version of a Student Result (is_latest, not pending_ratification: P2-T19 fix 1)
whose Exam Session is Published with publish_at passed. Values come from campus.examinations.graduation_rules: CGPA and % (CGPA x 10) with the additional / Honours /
Minor courses of the student's Course Registrations per the Grading Scheme and Classification Rule, the outstanding
arrears, and the class (rules.classify with the student's entry type, years of study and break of study). A student
has completed the programme with a published final-year session result, no outstanding core arrear and, when the
regulation's Curriculum Rule sets min_total_credits, at least that many core credits passed.
"""

import frappe
from frappe.query_builder.functions import Coalesce
from frappe.utils import now_datetime

from campus.campus_platform.api import get_regulation
from campus.examinations import graduation_rules, rules
from campus.examinations.results import RESULT, break_years, study_years

PUBLISHED = "Published"


def graduate_record(student):
	"""The consolidated record of `student` (a frappe._dict) from published results."""
	info = frappe.db.get_value(
		"Student", student,
		["name as student", "student_name", "oc_register_no as register_no", "date_of_birth", "oc_company as company",
		"oc_batch as batch", "oc_lateral_entry"],
		as_dict=True,
	)  # fmt: skip
	regulation = get_regulation(student)
	attempts = published_attempts(student)
	semesters = group_semesters(attempts)
	scheme_counts = frappe.db.get_value(
		"Grading Scheme", {"regulation": regulation}, "count_additional_with_honours"
	)
	rule = classification_rule(regulation)
	consolidated = graduation_rules.consolidate(
		attempts, registration_types(student), rule.honours_credits if rule else 0, scheme_counts
	)
	record = frappe._dict(info, **consolidated, regulation=regulation, semesters=semesters)
	record.program = (
		semesters[-1].program
		if semesters
		else frappe.db.get_value("Program Enrollment", {"student": student, "docstatus": 1}, "program")
	)
	record.completion_term = semesters[-1].academic_term if semesters else None
	record.completed = (
		bool(semesters) and any(s.is_final_year for s in semesters) and not record.arrears
		and graduation_rules.credits_complete(consolidated, required_credits(regulation))
	)  # fmt: skip
	record.classification = record.class_variant = None
	if record.completed and rule:
		found = graduation_rules.classification(
			consolidated, [c.as_dict() for c in rule.classes], study_years(info.batch, record.completion_term),
			break_years(student), rules.LATERAL if info.oc_lateral_entry else rules.REGULAR,
		)  # fmt: skip
		record.classification, record.class_variant = found or (None, None)
	return record


def cgpa(student, courses=None):
	"""The student's core CGPA from published results, over `courses` only when given (Honours / Minor eligibility)."""
	attempts = published_attempts(student)
	if courses is not None:
		attempts = [a for a in attempts if a.course in courses]
	return graduation_rules.consolidate(attempts, registration_types(student))["cgpa"]


def had_arrears(student):
	"""Whether `student` failed, missed or fell short in any course at its first appearance in a published result,
	cleared since or not (the placement "history of arrears" criterion, M14-01)."""
	history = {}
	for row in published_attempts(student):
		history.setdefault(row.course, []).append(row.result)
	appeared = {
		course: found for course, found in history.items() if any(r not in rules.NOT_SAT for r in found)
	}
	return not rules.passed_at_first_appearance(appeared)  # a course only ever withdrawn from was never sat


def required_credits(regulation):
	"""The regulation's credit total for the degree (Curriculum Rule min_total_credits), or 0 when none is set."""
	return (
		regulation
		and frappe.db.get_value("Curriculum Rule", {"regulation": regulation}, "min_total_credits")
		or 0
	)


def classification_rule(regulation):
	name = regulation and frappe.db.get_value("Classification Rule", {"regulation": regulation})
	return frappe.get_doc("Classification Rule", name) if name else None


def published_attempts(student):
	"""Course rows of the student's published latest result versions, oldest term first."""
	result, row, session, term, course = (
		frappe.qb.DocType(n)
		for n in (RESULT, "Student Result Course", "Exam Session", "Academic Term", "Course")
	)
	return (
		frappe.qb.from_(result)
		.join(row)
		.on((row.parent == result.name) & (row.parenttype == RESULT))
		.join(session)
		.on(session.name == result.exam_session)
		.join(term)
		.on(term.name == result.academic_term)
		.left_join(course)
		.on(course.name == row.course)
		.select(
			result.name.as_("student_result"),
			result.exam_session,
			result.academic_term,
			result.program,
			result.sgpa,
			session.is_final_year,
			row.course,
			course.course_name,
			row.credits,
			row.grade,
			row.grade_point,
			row.result,
			row.in_gpa,
		)  # fmt: skip
		.where(
			(result.student == student)
			& (result.is_latest == 1)
			& (Coalesce(result.pending_ratification, 0) == 0)
		)
		.where((session.status == PUBLISHED) & (session.publish_at <= now_datetime()))
		.orderby(term.term_start_date)
		.orderby(result.creation)
		.orderby(row.idx)
		.run(as_dict=True)
	)


def group_semesters(attempts):
	"""One entry per published result, with its course rows, in the order of `attempts`."""
	semesters = {}
	for row in attempts:
		semester = semesters.setdefault(
			row.student_result,
			frappe._dict(
				student_result=row.student_result, exam_session=row.exam_session, academic_term=row.academic_term,
				program=row.program, sgpa=row.sgpa, is_final_year=row.is_final_year, courses=[],
			),
		)  # fmt: skip
		semester.courses.append(row)
	return list(semesters.values())


def registration_types(student):
	"""{course: Additional / Honours / Minor} from the student's submitted Course Registrations."""
	registration, item = (
		frappe.qb.DocType("Course Registration"),
		frappe.qb.DocType("Course Registration Item"),
	)
	rows = (
		frappe.qb.from_(registration)
		.join(item)
		.on((item.parent == registration.name) & (item.parenttype == "Course Registration"))
		.select(item.course, item.registration_type)
		.where((registration.student == student) & (registration.docstatus == 1))
		.where(item.registration_type.isin(graduation_rules.ADDITIONAL_TYPES))
		.run()
	)
	return dict(rows)


def final_year_students(company, program=None):
	"""Students of `company` (and `program`) with a published final-year result: the graduate candidates."""
	result, session = frappe.qb.DocType(RESULT), frappe.qb.DocType("Exam Session")
	query = (
		frappe.qb.from_(result)
		.join(session)
		.on(session.name == result.exam_session)
		.select(result.student)
		.distinct()
		.where((result.company == company) & (result.is_latest == 1) & (session.is_final_year == 1))
		.where(Coalesce(result.pending_ratification, 0) == 0)
		.where((session.status == PUBLISHED) & (session.publish_at <= now_datetime()))
		.orderby(result.student)
	)
	if program:
		query = query.where(result.program == program)
	return query.run(pluck=True)
