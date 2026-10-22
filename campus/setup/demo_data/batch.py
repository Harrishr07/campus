"""PR-03 The 2025 batch: 20 students per programme (120), loaded the way a college loads existing students (Student and Program
Enrollment records with the legacy-import flag, a guardian each, register numbers and the regulation given), a class group
per programme, and a first year that is complete: Course Registration, Mark Sheet Entries, the Result Run and published
results (SGPA, CGPA, arrears) for the 2025-26 Odd and Even terms. The pilot student of the setup kit is the first CSE student.
Promotion into 2026-27 is the second-year Program Enrollment."""

import frappe

from campus.campus_platform.doctype.regulation.regulation import regulation_name
from campus.setup import people
from campus.setup.demo_data import academics
from campus.setup.records import upsert

BATCH_YEAR, SECOND_YEAR = "2025-26", "2026-27"
STUDENTS_PER_PROGRAMME = 20
JOINED_ON, PROMOTED_ON = "2025-07-15", "2026-06-01"
CATEGORIES = ["OC", "BC", "MBC", "SC", "BC", "OC", "MBC", "BC", "OC", "ST"]
FIRST_YEAR = (("Odd", 1, "2025-12-18"), ("Even", 2, "2026-05-22"))  # term, semester, last examination


class Cohort:
	"""Who is in the batch: [(programme, number, person)] in a fixed order; person is None for the pilot student."""

	def __init__(self, ctx):
		self.entries = []
		for programme in ctx.profile["programmes"]:
			slug = programme["abbr"].lower()
			for number in range(1, STUDENTS_PER_PROGRAMME + 1):
				person = ctx.people.make(f"student-2025-{slug}-{number:02d}", 2007, 2006)
				self.entries.append((programme, number, person))

	def students(self, ctx, programme):
		return [student_of(ctx, programme, number, person) for p, number, person in self.entries if p is programme]


def student_of(ctx, programme, number, person):
	"""Student name of a cohort entry (the pilot student for the first CSE entry), or None when not loaded yet."""
	email = pilot_email(ctx) if pilot_entry(programme, number) else person.email
	return frappe.db.get_value("Student", {"student_email_id": email})


def pilot_entry(programme, number):
	return programme["abbr"] == "CSE" and number == 1


def pilot_email(ctx):
	spec = next((u for u in ctx.profile["users"] if u.get("student")), None)
	return spec and people.user_email(ctx.profile, spec["key"])


def load(ctx):
	cohort = ctx.cohort
	regulation = regulation_name(ctx.profile["regulation"]["code"], ctx.college)
	for programme, number, person in cohort.entries:
		student = student_of(ctx, programme, number, person)
		if pilot_entry(programme, number) and not student:
			continue  # the setup kit made no pilot student (a profile without one)
		student = student or make_student(ctx, programme, number, person, regulation)
		adopt_pilot_student(ctx, student, programme, number, regulation)
		ensure_enrollment(ctx, student, programme, number, BATCH_YEAR, JOINED_ON)
	for programme in ctx.profile["programmes"]:
		ensure_class_group(ctx, programme, cohort.students(ctx, programme))
	for term_name, semester, exam_end in FIRST_YEAR:
		run_term(ctx, cohort, term_name, semester, exam_end)
	for programme, number, person in cohort.entries:
		student = student_of(ctx, programme, number, person)
		student and ensure_enrollment(ctx, student, programme, number, SECOND_YEAR, PROMOTED_ON)


def make_student(ctx, programme, number, person, regulation):
	father = ctx.people.make(f"guardian-student-2025-{programme['abbr'].lower()}-{number:02d}", 1975, 1960)
	guardian = upsert(
		ctx.out, "Guardian", {"email_address": father.email},
		{"guardian_name": f"{father.first_name} {person.last_name}", "mobile_number": father.mobile},
	)
	doc = frappe.get_doc(
		{
			"doctype": "Student", "first_name": person.first_name, "last_name": person.last_name,
			"student_email_id": person.email, "student_mobile_number": person.mobile, "date_of_birth": person.date_of_birth,
			"gender": person.gender, "joining_date": JOINED_ON, "oc_company": ctx.college, "oc_batch": BATCH_YEAR,
			"oc_regulation": regulation, "oc_register_no": register_no(ctx, programme, number), "state": "Tamil Nadu",
			"guardians": [{"guardian": guardian, "guardian_name": f"{father.first_name} {person.last_name}", "relation": "Father"}],
		}
	).insert(ignore_permissions=True)
	ctx.out.created["Student"] += 1
	return doc.name


def register_no(ctx, programme, number):
	abbr = frappe.db.get_value("Company", ctx.college, "abbr")
	return f"{abbr}25{programme['abbr']}{number:04d}"  # the pattern of the admission settings, for the year before the intake


def adopt_pilot_student(ctx, student, programme, number, regulation):
	"""The setup kit's pilot student has no register number, batch or regulation: give them those of a CSE 2025 student."""
	if not pilot_entry(programme, number):
		return
	wanted = {
		"oc_register_no": register_no(ctx, programme, number), "oc_batch": BATCH_YEAR, "oc_regulation": regulation,
		"joining_date": JOINED_ON, "date_of_birth": "2006-08-12", "gender": "Male",
	}  # fmt: skip
	stored = frappe.db.get_value("Student", student, list(wanted), as_dict=True)
	if any(str(stored[field] or "") != str(value) for field, value in wanted.items()):
		frappe.db.set_value("Student", student, wanted)
		ctx.out.updated["Student"] += 1


def ensure_enrollment(ctx, student, programme, number, year, date):
	"""The year's Program Enrollment (legacy-import flag: it is not a joining), with the batch's category and quota."""
	if frappe.db.exists("Program Enrollment", {"student": student, "academic_year": year, "docstatus": 1}):
		return
	enrollment = frappe.get_doc(
		{
			"doctype": "Program Enrollment", "student": student, "program": programme["name"], "academic_year": year,
			"enrollment_date": date, "oc_attendance_start_date": date, "student_category": CATEGORIES[(number - 1) % len(CATEGORIES)],
			"oc_admission_quota": "MQ" if number % 4 == 0 else "GQ",
		}
	)  # fmt: skip
	enrollment.flags.legacy_import = True
	enrollment.insert(ignore_permissions=True).submit()
	ctx.out.created["Program Enrollment"] += 1


def class_group_name(ctx, programme):
	return f"{frappe.db.get_value('Company', ctx.college, 'abbr')} {programme['name']} {BATCH_YEAR} A"


def ensure_class_group(ctx, programme, students):
	name = class_group_name(ctx, programme)
	if frappe.db.exists("Student Group", {"student_group_name": name}):
		return name
	frappe.get_doc(
		{
			"doctype": "Student Group", "student_group_name": name, "group_based_on": "Batch", "academic_year": BATCH_YEAR,
			"program": programme["name"], "oc_company": ctx.college, "oc_section": programme["abbr"],
			"students": [{"student": s} for s in students if s],
		}
	).insert(ignore_permissions=True)
	ctx.out.created["Student Group"] += 1
	return name


def run_term(ctx, cohort, term_name, semester, exam_end):
	"""Offerings, registrations, marks and published results of one first-year term, for every programme."""
	term = academics.term_of(BATCH_YEAR, term_name)
	session = academics.ensure_session(ctx, term, exam_end)
	everyone = []
	for programme in ctx.profile["programmes"]:
		students = cohort.students(ctx, programme)
		offerings = academics.make_offerings(ctx, programme, term, semester)
		academics.register_students(ctx, programme, students, term, semester)
		academics.enter_marks(ctx, session, offerings, students)
		everyone += students
	academics.publish_term(ctx, session, everyone, exam_end)
