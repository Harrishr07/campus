"""P3-T10 attainment fixture on the standard demo (campus.tests.demo): B.E. CSE, batch 2022, regulation R2022.

`seed_outcome_demo()` is idempotent and also serves a demo site (after make_demo):
    bench --site <site> execute campus.tests.attainment_fixtures.seed_outcome_demo
It adds the NBA PO1-PO12 and PSO1-PSO2 of B.E. CSE under R2022 and R2026, CO1-CO3 of Data Structures in the R2022
curriculum, its CO-PO matrix approved by the CSE HOD through the approval engine, and the Attainment Policies: R2022
the SXCCE rule (80 % direct + 20 % indirect; direct 60 % ESE + 40 % CIA; threshold 60 %; bands L1 40 %, L2 50 %,
L3 60 %; targets 2) and R2026 a different one.

`make_assessment()` is for tests only: it stores (without controllers, as the attainment readers only read them) the
released, ratified results, CIA question marks, double-valued ESE scripts and closed feedback of one Data Structures
offering of twelve batch-2022 students, built so every figure can be worked out by hand:

            CIA (>= 60 %)     ESE (>= 60 %)     direct            indirect          final (80/20)
    CO1     7/10 = 70 % L3    5/9 = 55.56 % L2  .4*3 + .6*2 = 2.4 avg 4.0 -> 2.4    2.4  (target 2 met)
    CO2     6/10 = 60 % L3    4/9 = 44.44 % L1  1.2 + .6 = 1.8    avg 3.6 -> 2.16   1.44 + .432 = 1.87
    CO3     3/9 = 33.33 % L0  5/9 = 55.56 % L2  0 + 1.2 = 1.2     3 answers: hidden 1.2  (direct only)

s10 was absent from the ESE (AB) and from CIA 2 Q2 (CO3); s9 from CIA 2 Q1 (its CO2 is CIA 1 Q2 alone); s11 is short of
attendance (SA) and s12's only result awaits ratification, so neither counts. s9's script went to a third valuation:
rounds 2 and 3 decide. Matrix: CO1-PO1 3, CO2-PO1 2, CO2-PO2 3, CO3-PO2 1, CO3-PSO1 2, so
    PO1 = (2.4*3 + 1.87*2) / 5 = 2.19, with the exit survey (avg 4.4 -> 2.64, 20 %): 2.28
    PO2 = (1.87*3 + 1.2*1) / 4 = 1.7 (its survey question had 2 answers: hidden), PSO1 = 1.2, PO3-PO12 not mapped.
"""

import frappe

from campus.campus_platform.approvals import approve, request_approval
from campus.campus_platform.doctype.regulation.regulation import regulation_name
from campus.curriculum.outcomes import seed_program_outcomes
from campus.tests.demo import CSE_DEPARTMENT, ENGINEERING, department_name, email, year_name

PROGRAM, COURSE = "B.E. CSE", "Data Structures"
BATCH = year_name(2022)
CO_CODES = ("CO1", "CO2", "CO3")
MATRIX = {("CO1", "PO1"): 3, ("CO2", "PO1"): 2, ("CO2", "PO2"): 3, ("CO3", "PO2"): 1, ("CO3", "PSO1"): 2}
POLICIES = {
	"R2022": {
		"direct_weight": 80, "indirect_weight": 20, "cia_weight": 40, "ese_weight": 60, "student_threshold": 60,
		"target_level": 2, "po_indirect_weight": 20, "po_target_level": 2,
		"level_bands": [{"level": 1, "min_students_percent": 40}, {"level": 2, "min_students_percent": 50}, {"level": 3, "min_students_percent": 60}],
	},
	"R2026": {
		"direct_weight": 70, "indirect_weight": 30, "cia_weight": 50, "ese_weight": 50, "student_threshold": 50,
		"target_level": 2, "po_indirect_weight": 30, "po_target_level": 2,
		"level_bands": [{"level": 1, "min_students_percent": 50}, {"level": 2, "min_students_percent": 60}, {"level": 3, "min_students_percent": 70}],
	},
}  # fmt: skip

OFFERING, SESSION, BUNDLE = "ATT-DS-2022-A", "ATT-ES-1", "ATT-BUNDLE-1"
CO_CAMPAIGN, EXIT_CAMPAIGN = "ATT-FBC-CO", "ATT-FBC-EXIT"
STUDENTS = [f"ATT22-{n:02d}" for n in range(1, 13)]
# CIA questions (component, question, max, CO) and per student marks in that order; None = absent
CIA_QUESTIONS = (("CIA 1", "Q1", 10, "CO1"), ("CIA 1", "Q2", 10, "CO2"), ("CIA 2", "Q1", 10, "CO2"), ("CIA 2", "Q2", 10, "CO3"), ("CIA 2", "Q3", 5, ""))
CIA_MARKS = {
	1: (8, 7, 7, 8, 5), 2: (8, 7, 7, 8, 5), 3: (8, 7, 7, 8, 5), 4: (8, 7, 7, 3, 5), 5: (8, 7, 7, 3, 5),
	6: (8, 6, 6, 3, 5), 7: (6, 5, 5, 3, 5), 8: (4, 5, 5, 3, 5), 9: (4, 5, None, 3, 5), 10: (4, 5, 5, None, 5),
	11: (10, 10, 10, 10, 5), 12: (10, 10, 10, 10, 5),
}  # fmt: skip
# ESE questions (question, max, CO) and the agreed per-question marks; round 1 is one above, round 2 one below
ESE_QUESTIONS = (("Q1", 20, "CO1"), ("Q2", 20, "CO2"), ("Q3", 10, "CO3"), ("Q4", 10, "CO3"), ("Q5", 10, ""))
ESE_MARKS = {
	1: (14, 12, 7, 6, 5), 2: (14, 12, 7, 6, 5), 3: (14, 12, 7, 6, 5), 4: (14, 12, 7, 6, 5), 5: (14, 8, 7, 6, 5),
	6: (10, 8, 4, 4, 5), 7: (10, 8, 4, 4, 5), 8: (10, 8, 4, 4, 5), 9: (10, 8, 4, 4, 5),
	11: (20, 20, 10, 10, 5), 12: (20, 20, 10, 10, 5),
}  # fmt: skip
RESULTS = {10: "AB", 11: "SA"}  # others Pass; 12 pending ratification


def regulation(code):
	return regulation_name(code, ENGINEERING)


def curriculum(code="R2022"):
	return frappe.db.get_value("Curriculum", {"program": PROGRAM, "regulation": regulation(code)}, order_by="version desc")


def course():
	return frappe.db.get_value("Course", {"course_name": COURSE})


# ---- the demo seed -------------------------------------------------------------------------


def seed_outcome_demo():
	"""Outcomes, approved matrix and attainment policies for B.E. CSE (see the module docstring); returns the matrix."""
	department = department_name(CSE_DEPARTMENT, ENGINEERING)
	if not frappe.db.get_value("Course", course(), "department"):
		frappe.db.set_value("Course", course(), "department", department)
	for code in ("R2022", "R2026"):
		seed_program_outcomes(PROGRAM, regulation(code))
		for pso in ("PSO1", "PSO2"):
			if not frappe.db.exists("Program Specific Outcome", {"program": PROGRAM, "regulation": regulation(code), "pso_code": pso}):
				frappe.get_doc(
					{"doctype": "Program Specific Outcome", "program": PROGRAM, "regulation": regulation(code), "pso_code": pso,
					"statement": f"{pso} (placeholder - replace with the department's statement)"}
				).insert()  # fmt: skip
		seed_policy(code)
	for n, code in enumerate(CO_CODES):
		if not frappe.db.exists("Course Outcome", {"course": course(), "curriculum": curriculum(), "co_code": code}):
			frappe.get_doc(
				{"doctype": "Course Outcome", "course": course(), "curriculum": curriculum(), "co_code": code,
				"statement": f"{code} of {COURSE} (demo)", "bloom_level": ("Understand", "Apply", "Analyse")[n]}
			).insert()  # fmt: skip
	return approved_matrix()


def seed_policy(code):
	name = frappe.db.get_value("Attainment Policy", {"regulation": regulation(code)})
	if not name:
		name = frappe.get_doc({"doctype": "Attainment Policy", "regulation": regulation(code), **POLICIES[code]}).insert().name
	return name


def approved_matrix():
	name = frappe.db.get_value("CO-PO Matrix", {"course": course(), "curriculum": curriculum(), "docstatus": ["<", 2]})
	doc = frappe.get_doc("CO-PO Matrix", name) if name else frappe.get_doc({"doctype": "CO-PO Matrix", "course": course(), "curriculum": curriculum()}).insert()
	if doc.docstatus == 1:
		return doc.name
	for row in doc.correlations:
		row.correlation = MATRIX.get((row.co_code, row.outcome_code), 0)
	doc.save()
	request = request_approval(doc.doctype, doc.name)
	if request:
		user = frappe.session.user
		frappe.set_user(email("hod_cse"))
		try:
			approve(request)
		finally:
			frappe.set_user(user)
	return doc.name


# ---- stored assessment data (tests) --------------------------------------------------------


def insert(values):
	"""Store a source record as data, without its controller (the attainment readers only read it)."""
	doc = frappe.get_doc(values)
	doc.db_insert()
	for child in doc.get_all_children():
		child.db_insert()
	return doc


def make_assessment():
	term = frappe.db.get_value("Academic Term", {"academic_year": BATCH, "term_name": "Even"})
	instructor = frappe.db.get_value("Instructor", {"employee": frappe.db.get_value("Employee", {"user_id": email("faculty_1")})})
	for n, student in enumerate(STUDENTS, 1):
		insert({"doctype": "Student", "name": student, "first_name": "Attainment", "last_name": f"{n:02d}",
			"student_name": f"Attainment {n:02d}", "student_email_id": f"{student.lower()}@attainment.example.com",
			"oc_company": ENGINEERING, "oc_batch": BATCH, "oc_regulation": regulation("R2022"), "enabled": 1})  # fmt: skip
	insert({"doctype": "Student Group", "name": OFFERING, "student_group_name": OFFERING, "group_based_on": "Course",
		"academic_year": BATCH, "academic_term": term, "program": PROGRAM, "course": course(), "oc_company": ENGINEERING,
		"oc_curriculum": curriculum(), "oc_semester": 2, "oc_section": "A",
		"students": [{"student": s, "active": 1} for s in STUDENTS], "instructors": [{"instructor": instructor}]})  # fmt: skip
	insert({"doctype": "Exam Session", "name": SESSION, "company": ENGINEERING, "academic_term": term,
		"status": "Published", "publish_at": "2023-06-01 10:00:00"})  # fmt: skip
	make_results()
	make_cia_marks()
	make_scripts()
	make_feedback()
	return frappe._dict(offering=OFFERING, session=SESSION, term=term, instructor=instructor)


def make_results():
	for n, student in enumerate(STUDENTS, 1):
		pending = n == 12
		insert({"doctype": "Student Result", "name": f"SR-ATT-{student}", "student": student, "exam_session": SESSION,
			"company": ENGINEERING, "program": PROGRAM, "regulation": regulation("R2022"), "version": 1,
			"is_latest": 0 if pending else 1, "pending_ratification": 1 if pending else 0,
			"courses": [{"course": course(), "course_offering": OFFERING, "result": RESULTS.get(n, "Pass")}]})  # fmt: skip


def make_cia_marks():
	rows = []
	for n, student in enumerate(STUDENTS, 1):
		for (component, question, maximum, co), marks in zip(CIA_QUESTIONS, CIA_MARKS[n]):
			absent = marks is None
			rows.append({"student": student, "component": component, "question": question, "max_marks": maximum,
				"course_outcome": co, "absent": int(absent), "marks": 0 if absent else marks})  # fmt: skip
	insert({"doctype": "Mark Sheet Entry", "name": "MSE-ATT-1", "exam_session": SESSION, "course_offering": OFFERING,
		"company": ENGINEERING, "course": course(), "cia_marks": rows})  # fmt: skip


def make_scripts():
	insert({"doctype": "Answer Script Bundle", "name": BUNDLE, "exam_session": SESSION, "course": course(), "company": ENGINEERING,
		"expected_count": len(ESE_MARKS), "questions": [{"question": q, "max_marks": m, "course_outcome": co} for q, m, co in ESE_QUESTIONS]})  # fmt: skip
	for n, marks in ESE_MARKS.items():
		student, dummy = STUDENTS[n - 1], f"ATTD{n:04d}"
		insert({"doctype": "Dummy Number Map", "name": f"DNM-ATT-{n}", "exam_session": SESSION, "company": ENGINEERING,
			"course": course(), "student": student, "dummy_number": dummy, "finalised": 1, "final_ese": sum(marks)})  # fmt: skip
		rounds = {1: [m + 1 for m in marks], 2: [m - 1 for m in marks]}
		if n == 9:  # a third valuation: round 1 is far off, rounds 2 and 3 decide
			rounds = {1: [0] * len(marks), 2: [m + 1 for m in marks], 3: [m - 1 for m in marks]}
		for round_, values in rounds.items():
			valuation_entry(f"VE-ATT-{n}-{round_}", dummy, round_, values)
	valuation_entry("VE-ATT-1-X", "ATTD0001", 1, [0] * len(ESE_QUESTIONS), docstatus=2)  # cancelled: never counted


def valuation_entry(name, dummy, round_, values, docstatus=1):
	insert({"doctype": "Valuation Entry", "name": name, "dummy_number": dummy, "valuation_round": str(round_),
		"exam_session": SESSION, "course": course(), "bundle": BUNDLE, "docstatus": docstatus, "total": sum(values),
		"marks": [{"question": q, "marks": v} for (q, _m, _co), v in zip(ESE_QUESTIONS, values)]})  # fmt: skip


def make_feedback():
	frappe.db.set_single_value("Campus Settings", "feedback_minimum_group_size", 5)
	co_answers = [  # (CO1, CO2, CO3 or None)
		(4, 4, 5), (4, 3, 5), (4, 4, 5), (4, 3, None), (4, 4, None),
	]
	campaign(CO_CAMPAIGN, "Course Offering Students", OFFERING, [
		[("q1", "CO1", a), ("q2", "CO2", b), *([("q3", "CO3", c)] if c else [])] for a, b, c in co_answers
	])  # fmt: skip
	exit_answers = [(5, 4), (5, 4), (4, None), (4, None), (4, None)]  # PO1 avg 4.4; PO2 answered twice
	campaign(EXIT_CAMPAIGN, "Students", None, [
		[("q1", "PO1", a), *([("q2", "PO2", b)] if b else [])] for a, b in exit_answers
	])  # fmt: skip


def campaign(name, audience, offering, responses, end_date="2023-05-15"):
	insert({"doctype": "Feedback Campaign", "name": name, "campaign_title": name, "company": ENGINEERING,
		"academic_year": BATCH, "audience": audience, "course_offering": offering, "start_date": "2023-05-01",
		"end_date": end_date, "is_anonymous": 1})  # fmt: skip
	for k, answers in enumerate(responses, 1):
		insert({"doctype": "Feedback Response", "name": f"{name}-R{k}", "campaign": name, "company": ENGINEERING,
			"course_offering": offering, "response_date": "2023-05-10",
			"answers": [{"question_row": row, "question": row, "question_type": "Likert", "course_outcome": tag, "rating": rating}
				for row, tag, rating in answers]})  # fmt: skip
