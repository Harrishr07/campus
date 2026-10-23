"""PR-03 Shared academic steps for the 2025 batch's terms: offerings with their instructors, Course Registrations, an Exam
Session per term, Mark Sheet Entries with generated marks, and the Result Run + publication of a finished term. Every step
finds its record first, so a term is built once however often the dataset is loaded."""

import random

import frappe
from frappe.utils import add_days

from campus.curriculum.offerings import generate_offerings
from campus.examinations.courses import offering_course, student_limits
from campus.setup.demo_data import shortcuts
from campus.setup.demo_data.curriculum import semester_courses

LATE_REASON = "Demo data is loaded after the registration window closed"


def term_of(year, term_name):
	return frappe.db.get_value("Academic Term", {"academic_year": year, "term_name": term_name})


def curriculum_of(ctx, programme):
	name = frappe.db.get_value("Curriculum", {"program": programme["name"], "status": "Effective"})
	if not name:
		frappe.throw(f"{programme['name']} has no Effective curriculum: load the 'curriculum' step before the steps that need it.")
	return name


def make_offerings(ctx, programme, term, semester):
	"""Offerings of the programme's semester courses in `term` (section = the programme's abbreviation), each taught by one of the
	department's instructors in turn; returns {course: offering}."""
	generate_offerings(curriculum_of(ctx, programme), term, [programme["abbr"]])
	instructors = department_instructors(ctx, programme)
	offerings = {}
	for number, (course, *_rest) in enumerate(semester_courses(programme["abbr"], semester)):
		name = f"{course}-{term}-{programme['abbr']}"
		group = frappe.get_doc("Student Group", name)
		if not group.instructors:
			group.append("instructors", {"instructor": instructors[number % len(instructors)]})
			group.save(ignore_permissions=True)
		offerings[course] = name
	return offerings


def department_instructors(ctx, programme):
	department = f"{programme['department']} - {frappe.db.get_value('Company', ctx.college, 'abbr')}"
	return frappe.get_all("Instructor", {"department": department}, pluck="name", order_by="name")


def register_students(ctx, programme, students, term, semester):
	"""A submitted Course Registration of the semester's courses for each student (late: the window is long closed)."""
	date = add_days(frappe.db.get_value("Academic Term", term, "term_start_date"), 7)
	courses = [course for course, *_rest in semester_courses(programme["abbr"], semester)]
	for student in students:
		if frappe.db.exists("Course Registration", {"student": student, "academic_term": term, "docstatus": 1}):
			continue
		frappe.get_doc(
			{
				"doctype": "Course Registration", "student": student, "academic_term": term, "semester": semester,
				"registration_date": date, "late_reason": LATE_REASON,
				"items": [{"course": course, "registration_type": "Regular"} for course in courses],
			}
		).insert(ignore_permissions=True).submit()
		ctx.out.created["Course Registration"] += 1


def ensure_session(ctx, term, exam_end=None):
	name = frappe.db.get_value("Exam Session", {"company": ctx.college, "academic_term": term})
	if name:
		return name
	ctx.out.created["Exam Session"] += 1
	return frappe.get_doc(
		{"doctype": "Exam Session", "company": ctx.college, "academic_term": term, "status": "Marks Entry", "exam_end": exam_end}
	).insert(ignore_permissions=True).name


def enter_marks(ctx, session, offerings, students, cia_only=False):
	"""One Mark Sheet Entry per offering. Each student has an ability (seeded, by Student); marks are that ability with some noise
	per course, inside the course's CIA and ESE limits. `cia_only` leaves the end-semester marks blank (a term in progress)."""
	for course, offering in offerings.items():
		if frappe.db.exists("Mark Sheet Entry", {"exam_session": session, "course_offering": offering}):
			continue
		info = offering_course(offering)
		rows = []
		for student in students:
			limits = student_limits(student, info)
			rng = random.Random(f"{ctx.seed}:marks:{student}:{course}")
			ability = ability_of(ctx, student)
			share = lambda: min(1.0, max(0.0, ability + rng.gauss(0, 0.07)))  # noqa: E731
			row = {"student": student, "cia": round(limits["cia_max"] * share())}
			if not cia_only:
				row["ese"] = round(limits["ese_max"] * share())
			rows.append(row)
		frappe.get_doc({"doctype": "Mark Sheet Entry", "exam_session": session, "course_offering": offering, "marks": rows}).insert(
			ignore_permissions=True
		)
		ctx.out.created["Mark Sheet Entry"] += 1


def ability_of(ctx, student):
	"""0.52 to 1.0, mostly high: a student near the floor sometimes fails a course, none fails them all."""
	return max(0.52, 0.40 + 0.60 * random.Random(f"{ctx.seed}:ability:{student}").betavariate(4, 2))


def publish_term(ctx, session, students, exam_end):
	"""Run the results of `students` and publish the session without a Passing Board meeting (`shortcuts.publish_results`, the
	demo's one skipped control), dated like a real term."""
	if frappe.db.get_value("Exam Session", session, "status") == "Published":
		return
	frappe.db.set_value("Exam Session", session, "exam_end", exam_end)
	shortcuts.publish_results(session, students)
	shortcuts.date_publication(session, exam_end)
	ctx.out.created["Student Result"] += len(students)
