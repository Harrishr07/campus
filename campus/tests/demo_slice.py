"""S5 Demo builder: the whole thin-slice path on top of the "small" demo data (`make_demo("slice")`).

    admit -> fees (4 of 5 paid) -> Effective R2026 curriculum -> offerings -> course registration
    -> 8 weeks of schedules and attendance -> CIA + ESE marks -> Result Run -> publish -> Grade Sheet
    -> portal users -> AQAR cycle computed.

Every step looks its records up by natural key and creates only what is missing, so a second run creates
nothing. The Result Run is run synchronously (the same per-student computation the queued Bulk Run uses),
so the demo needs no worker and leaves nothing in the job queue.

The demo treats the Exam Session as the final-year session of the college (`is_final_year`): the data has
no real final-year batch, and flagging the session is what gives AQAR metric 2.6.3 data to show.
Attendance dates are fixed to the first eight weeks of the academic term, so the outcome does not change
from day to day once those weeks are past. Attendance counts only sessions dated up to today, so a demo built
before the end of week 8 of the term (1 June 2026 start for the demo year) shows fewer conducted sessions and
different percentages; build it after week 8.
"""

import frappe
from frappe.utils import add_days, getdate, now_datetime
from frappe.utils.password import update_password

from campus.admissions import eligibility
from campus.admissions.api import admit
from campus.campus_platform.doctype.regulation.regulation import regulation_name
from campus.campus_platform.verification import issue
from campus.curriculum.offerings import generate_offerings
from campus.examinations import results
from campus.iqac import compute
from campus.iqac.setup import FRAMEWORK, seed_framework
from campus.tests import demo
from campus.tests.finance_factories import make_fee_structure, make_finance_company

PASSWORD = "Campus@Demo2026"  # demo sites only; documented in docs/DEMO.md
PROGRAM = "B.E. CSE"
PROGRAM_CODE = "CSE"
REGULATION_CODE = "R2026"
YEAR = demo.year_name(2026)
TERM_NAME = "Odd"
SEMESTER = 1
SECTION = "A"
GOVERNMENT, MANAGEMENT = "GQ", "MQ"
ROOM = "Demo Room 101"
WEEKS = 8
SESSION_DAYS = (0, 2, 4)  # Monday, Wednesday, Friday
SESSIONS = WEEKS * len(SESSION_DAYS)

# slug, first name, last name, student category, quota
APPLICANTS = [
	("slice-1", "Aarav", "Kumar", "OC", GOVERNMENT),
	("slice-2", "Meena", "Lakshmi", "BC", GOVERNMENT),
	("slice-3", "Karthik", "Raja", "MBC", GOVERNMENT),
	("slice-4", "Divya", "Bharathi", "SC", GOVERNMENT),
	("slice-5", "Sanjay", "Prakash", "OC", MANAGEMENT),
]
LIVE_APPLICANT = ("slice-6", "Nithya", "Shree", "BC", GOVERNMENT)  # left Approved: the admission officer admits her live
PAID = 4  # the first four admitted students pay; the management-quota student's fee stays due
QUALIFYING_MARKS = (("Mathematics", 100, 96), ("Physics", 100, 91), ("Chemistry", 100, 89))
ELIGIBILITY_MINIMUMS = {"OC": 50, "BC": 45, "MBC": 45, "SC": 40, "ST": 40}
SEATS = {GOVERNMENT: ["OC", "BC", "MBC", "SC", "ST"], MANAGEMENT: ["OC", "BC"]}
FEES = {"Tuition": 60000, "Exam": 3000, "Library": 2000}
MANAGEMENT_FEES = {"Tuition": 150000, "Exam": 3000, "Library": 2000}

# course, category, L, T, P, exam type, instructor user. The 3-1-0 / 3-0-2 / 0-0-4 periods give 4, 4, 4 and 2 credits.
COURSES = [
	("Matrices and Calculus", "BSC", 3, 1, 0, "Theory", "hod_cse"),
	("Engineering Physics", "BSC", 3, 0, 2, "Theory", "faculty_1"),
	("Problem Solving and Python Programming", "ESC", 3, 0, 2, "Theory", "faculty_2"),
	("Physics and Chemistry Laboratory", "BSC", 0, 0, 4, "Practical", "faculty_3"),
]

# Attendance: session numbers (0..23) on which the student is absent; the medical-band student is on
# approved medical leave in week 4 (sessions 9-11) and absent on the others listed.
ABSENT = {
	0: lambda n, c: n == 7,  # 23 of 24: Eligible
	1: lambda n, c: n % 12 == c,  # 22 of 24: Eligible
	2: lambda n, c: n % 12 >= 7,  # 14 of 24 (58%): Shortage (SA)
	3: lambda n, c: n % 6 == 0,  # 17 of 24 present, 3 on leave: Medical band
	4: lambda n, c: n in (3, 16, 20),  # 21 of 24: Eligible
}
MEDICAL_STUDENT, MEDICAL_SESSIONS = 3, (9, 10, 11)

# Marks per student (index as in APPLICANTS) and course: (CIA, ESE), "AB" for absent. Student 3 is on
# attendance shortage (SA for every course; no marks needed), student 2 fails Matrices on ESE 40%.
MARKS = {
	0: [(36, 52), (45, 46), (40, 38), (54, 33)],
	1: [(30, 24), (38, 35), (35, 31), (45, 28)],
	2: [(0, 0)] * 4,
	3: [(28, 40), (32, 34), (30, 35), (40, 26)],
	4: ["AB", (40, 40), (36, 35), (50, 30)],
}


def build_slice():
	"""Run the whole path; call after the "small" demo data exists."""
	frappe.set_user("Administrator")
	was_importing, frappe.flags.in_import = frappe.flags.in_import, False  # import mode would skip DocType defaults
	try:
		run_path()
	finally:
		frappe.flags.in_import = was_importing


def run_path():
	finance = prepare_admissions()
	students = admit_applicants()
	invoice_fees(students, finance)
	curriculum = make_curriculum()
	term = academic_term()
	make_registration_window(term)
	offerings = make_offerings(curriculum, term)
	register_courses(students, term)
	make_attendance(students, offerings)
	session = make_exam_session(term)
	enter_marks(session, students, offerings)
	publish_results(session, students)
	issue_grade_sheet(session, students[0])
	link_portal_users(students[0])
	set_demo_passwords()
	compute_aqar_cycle()


def academic_term():
	return frappe.db.get_value("Academic Term", {"academic_year": YEAR, "term_name": TERM_NAME})


def slice_students():
	"""Student names of the five admitted applicants, in applicant order (None for one not admitted yet)."""
	return [frappe.db.get_value("Student", {"student_email_id": demo.email(slug)}) for slug, *_ in APPLICANTS]


# --- Admissions and fees ------------------------------------------------------------------------


def prepare_admissions():
	"""Quotas, seat matrix, eligibility and document rules, admission settings and the fee structures."""
	if not frappe.db.get_value("Program", PROGRAM, "program_abbreviation"):
		frappe.db.set_value("Program", PROGRAM, "program_abbreviation", PROGRAM_CODE)
	settings = frappe.get_doc("Admission Settings")
	if not settings.register_no_pattern or not settings.active_admission_year:
		settings.register_no_pattern = settings.register_no_pattern or "{abbr}{yy}{program_code}{####}"
		settings.active_admission_year = settings.active_admission_year or YEAR
		settings.save(ignore_permissions=True)
	for code, title in ((GOVERNMENT, "Government Quota"), (MANAGEMENT, "Management Quota")):
		demo.get_or_insert("Admission Quota", {"code": code}, {"title": title})
	demo.get_or_insert("Gender", {"gender": "Male"}, {})
	demo.get_or_insert("Gender", {"gender": "Female"}, {})
	demo.get_or_insert(
		"Seat Matrix",
		{"company": demo.ENGINEERING, "program": PROGRAM, "academic_year": YEAR},
		{"rows": [{"quota": q, "category": c, "sanctioned": 10} for q, cats in SEATS.items() for c in cats]},
	)
	make_eligibility_rule()
	demo.get_or_insert(
		"Admission Document Rule", {"document_type": "Transfer Certificate"}, {"mandatory": 1, "verification_needed": 0}
	)
	return make_fee_structures()


def make_eligibility_rule():
	if frappe.db.exists("Eligibility Rule", {"program": PROGRAM, "enabled": 1}):
		return
	frappe.get_doc(
		{
			"doctype": "Eligibility Rule", "program": PROGRAM, "enabled": 1, "qualifying_exam": "HSC (Class XII)",
			"required_subjects": "\n".join(subject for subject, *_ in QUALIFYING_MARKS),
			"category_marks": [{"student_category": c, "min_percent": p} for c, p in ELIGIBILITY_MINIMUMS.items()],
		}
	).insert(ignore_permissions=True)


def make_fee_structures():
	"""The base fee structure and a higher management-quota one; returns the finance accounts."""
	company = demo.ENGINEERING
	was_ignoring = frappe.flags.ignore_root_company_validation
	frappe.flags.ignore_root_company_validation = True  # the college is a child of the trust: its accounts are made directly
	try:
		accounts = make_finance_company(company, "DCE")
	finally:
		frappe.flags.ignore_root_company_validation = was_ignoring
	frappe.db.set_value("Company", company, "default_bank_account", accounts["bank"])
	for quota, components in ((None, FEES), (MANAGEMENT, MANAGEMENT_FEES)):
		filters = {"company": company, "program": PROGRAM, "academic_year": YEAR, "docstatus": 1}
		filters["oc_admission_quota"] = quota or ["is", "not set"]
		if not frappe.db.exists("Fee Structure", filters):
			make_fee_structure(company, PROGRAM, YEAR, components, accounts, **({"oc_admission_quota": quota} if quota else {}))
	return accounts


def admit_applicants():
	"""Create the five Approved, Eligible applicants and admit them; returns the Student names in order.

	A sixth applicant is created Approved and Eligible but not admitted, so the demo can show the Admit button."""
	live = LIVE_APPLICANT
	if not frappe.db.exists("Student Applicant", {"student_email_id": demo.email(live[0])}):
		make_applicant(*live)
	for slug, first, last, category, quota in APPLICANTS:
		applicant = frappe.db.get_value("Student Applicant", {"student_email_id": demo.email(slug)}, ["name", "application_status"], as_dict=True)
		if not applicant:
			applicant = make_applicant(slug, first, last, category, quota)
		if applicant.application_status != "Admitted":
			admit(applicant.name)
	return slice_students()


def make_applicant(slug, first, last, category, quota):
	doc = frappe.get_doc(
		{
			"doctype": "Student Applicant", "first_name": first, "last_name": last, "program": PROGRAM, "academic_year": YEAR,
			"student_email_id": demo.email(slug), "oc_company": demo.ENGINEERING, "student_category": category,
			"oc_admission_quota": quota, "application_status": "Approved", "gender": "Female" if first in ("Meena", "Divya", "Nithya") else "Male",
			"date_of_birth": "2008-03-15", "state": "Tamil Nadu",
			"oc_qualifying_marks": [{"subject": s, "max_marks": m, "obtained_marks": o} for s, m, o in QUALIFYING_MARKS],
			"oc_documents": [{"document_type": "Transfer Certificate", "status": "Submitted"}],
		}
	).insert(ignore_permissions=True)
	if not eligibility.evaluate(doc.name)["eligible"]:
		frappe.throw(f"Demo applicant {doc.name} should be eligible.")
	return frappe._dict(name=doc.name, application_status="Approved")


def invoice_fees(students, finance):
	"""Admission raised one fee invoice per student; the first PAID of them are paid in full."""
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	for student in students[:PAID]:
		for invoice in frappe.get_all("Sales Invoice", {"student": student, "docstatus": 1, "outstanding_amount": [">", 0]}, pluck="name"):
			payment = get_payment_entry("Sales Invoice", invoice)
			payment.reference_no, payment.reference_date = f"DEMO-UTR-{student}", getdate()
			payment.insert(ignore_permissions=True).submit()


# --- Curriculum, offerings, registration -------------------------------------------------------


def make_curriculum():
	"""Credit and registration rules of R2026 and an Effective semester-1 B.E. CSE curriculum of four courses.

	The slice curriculum has semester 1 only, so the R2026 Curriculum Rule leaves the minimum total credits
	unbounded (0); a real rule would carry the 165-170 range once all semesters are loaded.
	"""
	regulation = regulation_name(REGULATION_CODE, demo.ENGINEERING)
	demo.get_or_insert(
		"Curriculum Rule", {"regulation": regulation},
		{"lecture_credit_per_period": 1, "tutorial_credit_per_period": 1, "practical_credit_per_period": 0.5,
		"min_total_credits": 0, "max_total_credits": 170},
	)  # fmt: skip
	demo.get_or_insert(
		"Registration Rule", {"regulation": regulation},
		{"max_credits_per_semester": 36, "excluded_types": "Arrear\nDropped", "max_drop_credits": 6, "drop_window_days": 30,
		"add_from_semester": 5, "max_add_credits": 6, "max_add_courses": 2, "elective_min_enrolment": 10},
	)  # fmt: skip
	existing = frappe.db.get_value("Curriculum", {"program": PROGRAM, "regulation": regulation, "version": 1})
	if existing:
		return existing
	rows = []
	for course, category, lecture, tutorial, practical, exam_type, _instructor in COURSES:
		name = demo.get_or_insert("Course", {"course_name": course}, {"oc_company": demo.ENGINEERING})
		rows.append(
			{"semester": SEMESTER, "course": name, "category": category, "lecture_periods": lecture, "tutorial_periods": tutorial,
			"practical_periods": practical, "exam_type": exam_type}
		)  # fmt: skip
	doc = frappe.get_doc({"doctype": "Curriculum", "program": PROGRAM, "regulation": regulation, "version": 1, "courses": rows})
	doc.insert(ignore_permissions=True)
	for status in ("Approved", "Effective"):
		doc.status = status
		doc.save(ignore_permissions=True)
	return doc.name


def make_registration_window(term):
	start = frappe.db.get_value("Academic Term", term, "term_start_date")
	demo.get_or_insert(
		"Registration Window", {"company": demo.ENGINEERING, "academic_term": term, "program": PROGRAM},
		{"opens_on": start, "closes_on": add_days(start, 29)},
	)  # fmt: skip


def make_offerings(curriculum, term):
	"""Course offerings (Student Groups) of the term, each taught by its instructor; returns names in COURSES order."""
	generate_offerings(curriculum, term, [SECTION])
	offerings = []
	for course, *_rest, username in COURSES:
		name = f"{course}-{term}-{SECTION}"
		group = frappe.get_doc("Student Group", name)
		instructor = frappe.db.get_value("Instructor", {"employee": demo.employee_of(username)})
		if not group.instructors:
			group.append("instructors", {"instructor": instructor})
			group.save(ignore_permissions=True)
		offerings.append(name)
	return offerings


def register_courses(students, term):
	"""A submitted Course Registration of all four courses per student (no approval policy exists in the demo)."""
	registration_date = add_days(frappe.db.get_value("Academic Term", term, "term_start_date"), 7)
	for student in students:
		if frappe.db.exists("Course Registration", {"student": student, "academic_term": term, "docstatus": 1}):
			continue
		frappe.get_doc(
			{
				"doctype": "Course Registration", "student": student, "academic_term": term, "semester": SEMESTER,
				"registration_date": registration_date,
				"items": [{"course": course, "registration_type": "Regular"} for course, *_rest in COURSES],
			}
		).insert(ignore_permissions=True).submit()


# --- Attendance --------------------------------------------------------------------------------


def session_dates(term):
	"""The 24 session dates: Monday, Wednesday and Friday of the first eight weeks of the term."""
	start = getdate(frappe.db.get_value("Academic Term", term, "term_start_date"))
	monday = add_days(start, -start.weekday()) if start.weekday() == 0 else add_days(start, 7 - start.weekday())
	return [add_days(monday, 7 * week + day) for week in range(WEEKS) for day in SESSION_DAYS]


def make_attendance(students, offerings):
	"""Course Schedules for every session and a Student Attendance row per student, following ABSENT."""
	term = frappe.db.get_value("Student Group", offerings[0], "academic_term")
	room = demo.get_or_insert("Room", {"room_name": ROOM}, {"room_number": "101", "seating_capacity": "60", "oc_company": demo.ENGINEERING})
	dates = session_dates(term)
	leave = make_medical_leave(students[MEDICAL_STUDENT], dates[MEDICAL_SESSIONS[0]], dates[MEDICAL_SESSIONS[-1]])
	for course_number, offering in enumerate(offerings):
		if frappe.db.count("Course Schedule", {"student_group": offering}):
			continue
		instructor = frappe.db.get_value("Student Group Instructor", {"parent": offering}, "instructor")
		for n, date in enumerate(dates):
			schedule = make_schedule(offering, instructor, room, date, course_number)
			for number, student in enumerate(students):
				mark_attendance(student, offering, schedule, date, status_for(number, n, course_number), leave)


def status_for(number, session, course_number):
	if number == MEDICAL_STUDENT and session in MEDICAL_SESSIONS:
		return "Leave"
	return "Absent" if ABSENT[number](session, course_number) else "Present"


def make_medical_leave(student, from_date, to_date):
	"""An approved Student Leave Application covering the medical period (submitted directly: Education's
	submit hook needs a holiday list, which is not what the demo is about)."""
	name = frappe.db.get_value("Student Leave Application", {"student": student, "from_date": from_date})
	if name:
		return name
	doc = frappe.get_doc(
		{"doctype": "Student Leave Application", "student": student, "from_date": from_date, "to_date": to_date, "oc_leave_kind": "Medical"}
	)
	doc.flags.ignore_validate = True
	doc.insert(ignore_permissions=True)
	frappe.db.set_value("Student Leave Application", doc.name, "docstatus", 1)
	return doc.name


def make_schedule(offering, instructor, room, date, course_number):
	hour = 9 + course_number
	doc = frappe.get_doc(
		{
			"doctype": "Course Schedule", "student_group": offering, "course": COURSES[course_number][0], "instructor": instructor, "room": room,
			"schedule_date": date, "from_time": f"{hour:02d}:00:00", "to_time": f"{hour:02d}:50:00",
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def mark_attendance(student, offering, schedule, date, status, leave):
	"""A submitted Student Attendance row. Education's holiday-list check is skipped (the demo company has no
	holiday list); the date and group are set here because that skips Education's own validate too."""
	doc = frappe.get_doc(
		{
			"doctype": "Student Attendance", "student": student, "student_group": offering, "course_schedule": schedule,
			"date": date, "status": status, "leave_application": leave if status == "Leave" else None,
		}
	)
	doc.flags.ignore_validate = True
	doc.insert(ignore_permissions=True)
	doc.submit()


# --- Marks, results, grade sheet ---------------------------------------------------------------


def make_exam_session(term):
	"""The Exam Session of the term, flagged final-year (see the module docstring); Marks Entry until published."""
	name = frappe.db.get_value("Exam Session", {"company": demo.ENGINEERING, "academic_term": term})
	if name:
		return name
	return frappe.get_doc(
		{"doctype": "Exam Session", "company": demo.ENGINEERING, "academic_term": term, "status": "Marks Entry", "is_final_year": 1}
	).insert(ignore_permissions=True).name


def enter_marks(session, students, offerings):
	if frappe.db.get_value("Exam Session", session, "status") != "Marks Entry":
		return
	for course_number, offering in enumerate(offerings):
		if frappe.db.exists("Mark Sheet Entry", {"exam_session": session, "course_offering": offering}):
			continue
		rows = []
		for number, student in enumerate(students):
			marks = MARKS[number][course_number]
			rows.append({"student": student, "absent": 1} if marks == "AB" else {"student": student, "cia": marks[0], "ese": marks[1]})
		frappe.get_doc(
			{"doctype": "Mark Sheet Entry", "exam_session": session, "course_offering": offering, "marks": rows}
		).insert(ignore_permissions=True)


def publish_results(session, students):
	"""Run the results for the five students (as the queued Result Run would), then publish with publish_at in the past."""
	doc = frappe.get_doc("Exam Session", session)
	if doc.status == "Published":
		return
	for student in students:
		results.compute_student_result(student, session)
	doc.status = "Published"
	doc.publish_at = add_days(now_datetime(), -1)
	doc.flags.passing_board_approval = True  # the thin-slice demo has no Passing Board meeting (P2-T19 publish_results)
	doc.save(ignore_permissions=True)


def issue_grade_sheet(session, student):
	"""One verifiable Grade Sheet (QR) for the first student."""
	result = frappe.get_doc("Student Result", f"SR-{session}-{student}")
	if not frappe.db.exists("Verifiable Document", {"reference_doctype": "Student Result", "reference_name": result.name}):
		issue(result, "Grade Sheet")


# --- Portal users and AQAR ---------------------------------------------------------------------


def link_portal_users(student):
	"""student_1 becomes the portal login of `student`, guardian_1 its guardian (replacing the "small" demo link)."""
	user = demo.email("student_1")
	for other in frappe.get_all("Student", {"user": user, "name": ["!=", student]}, pluck="name"):
		frappe.db.set_value("Student", other, "user", None, update_modified=False)
	frappe.db.set_value("Student", student, "user", user, update_modified=False)
	guardian = frappe.db.get_value("Guardian", {"email_address": demo.email("guardian_1")})
	frappe.db.delete("Student Guardian", {"guardian": guardian, "parenttype": "Student", "parent": ["!=", student]})
	if not frappe.db.exists("Student Guardian", {"parent": student, "guardian": guardian}):
		doc = frappe.get_doc("Student", student)
		doc.append("guardians", {"guardian": guardian, "guardian_name": "Guardian One", "relation": "Father"})
		doc.save(ignore_permissions=True)


def set_demo_passwords():
	"""Enable every demo login (earlier builds left them disabled); a login with no password gets the demo one."""
	for username in demo.USERS:
		user = demo.email(username)
		frappe.db.set_value("User", user, "enabled", 1)
		if not frappe.db.exists("__Auth", {"doctype": "User", "name": user, "fieldname": "password"}):
			update_password(user, PASSWORD)


def compute_aqar_cycle():
	seed_framework()
	cycle = demo.get_or_insert(
		"Accreditation Cycle", {"framework": FRAMEWORK, "company": demo.ENGINEERING, "academic_year": YEAR}, {}
	)
	compute.compute_cycle(cycle)
	seed_validation_problems(cycle)


# --- Pre-validation: three rules and the three problems they flag (P3-T05) --------------------

VALIDATION_RULES = [  # (rule type, node code, severity, extra values)
	("Required Evidence", "2.6.3", "Blocking", {"slot_name": "Data Template", "message": "Attach the Data Template for 2.6.3 (demo rule)."}),
	("Word Limit", "4.1.1", "Warning", {"limit": 25, "message": "The 4.1.1 answer is over the word limit (demo rule)."}),
	("Comparison", "2.1.2", "Blocking", {"operator": "<=", "compare_node": "EP-4.1", "message": "2.1.2 must not exceed 4.1 (demo rule)."}),
]  # fmt: skip


def seed_validation_rules(framework):
	for rule_type, code, severity, extra in VALIDATION_RULES:
		node = f"{framework}-{code}"
		values = {**extra, "compare_node": extra.get("compare_node") and f"{framework}-{extra['compare_node']}"}
		demo.get_or_insert(
			"Validation Rule", {"framework": framework, "rule_type": rule_type, "node": node}, {"severity": severity, **values}
		)


def seed_validation_problems(cycle):
	"""The demo's three problems: no evidence for 2.6.3, a 30-word 4.1.1 answer (limit 25), 2.1.2 = 85 above 4.1 = 40."""
	framework = frappe.db.get_value("Accreditation Cycle", cycle, "framework")
	seed_validation_rules(framework)
	answers = {"2.1.2": {"manual_value": 85}, "EP-4.1": {"manual_value": 40}, "4.1.1": {"narrative": "<p>" + " ".join(["word"] * 30) + "</p>"}}
	for code, values in answers.items():
		demo.get_or_insert("Metric Value", {"cycle": cycle, "node": f"{framework}-{code}"}, values)
