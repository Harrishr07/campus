"""Standard demo data for OneBook Campus (P1-T02): the data set every test and demo loads.

`make_demo(scale)` is idempotent: every record is looked up by its natural key (company name,
program name, regulation code, student email...) and created only when missing, so a second run
creates nothing and a partial run is completed.

    bench --site <site> execute campus.tests.demo.make_demo --kwargs "{'scale': 'full'}"

Not built yet (arrive with their own tasks): quota (Student has no quota field until T14),
roles "Exam Confidential" (skipped when the Role is absent) and regulation rule values.
"""

import frappe

from campus.campus_platform.doctype.regulation.regulation import regulation_name
from campus.campus_platform.regulation_rules import latest_enrollment, resolve_regulation
from campus.tests.factories import make_company

DOMAIN = "demo.campus.test"
TRUST = "Demo Educational Trust"
ENGINEERING = "Demo College of Engineering"
ARTS = "Demo Arts & Science College"
COMPANIES = [  # name, abbr, parent
	(TRUST, "DET", None),
	(ENGINEERING, "DCE", TRUST),
	(ARTS, "DAS", TRUST),
]
AFFILIATING_UNIVERSITY = "Anna University"
AUTONOMY_DATE = "2022-05-26"

CSE_DEPARTMENT = "Computer Science and Engineering"
ECE_DEPARTMENT = "Electronics and Communication Engineering"
ARTS_DEPARTMENT = "Mathematics"

# program name -> (company, department, student email slug)
PROGRAMS = {
	"B.E. CSE": (ENGINEERING, CSE_DEPARTMENT, "cse"),
	"B.E. ECE": (ENGINEERING, ECE_DEPARTMENT, "ece"),
	"M.E. CSE": (ENGINEERING, CSE_DEPARTMENT, "mecse"),
	"B.Sc. Mathematics": (ARTS, ARTS_DEPARTMENT, None),  # no demo students; scoping tests only
}
ENGINEERING_PROGRAMS = ["B.E. CSE", "B.E. ECE", "M.E. CSE"]

ACADEMIC_YEARS = [2021, 2022, 2023, 2024, 2025, 2026]  # start year; "2022-23" style names
FULL_BATCHES = [2022, 2023, 2024, 2025, 2026]
SMALL_BATCHES = [2026]
STUDENTS_PER_BATCH = {"small": 10, "full": 60}

# code, company, effective-from start year, programs
REGULATIONS = [
	("AU-R2021", ENGINEERING, 2021, ENGINEERING_PROGRAMS),
	("R2022", ENGINEERING, 2022, ENGINEERING_PROGRAMS),
	("R2026", ENGINEERING, 2026, ENGINEERING_PROGRAMS),
	("AS-R2022", ARTS, 2022, ["B.Sc. Mathematics"]),
]

# 20-student cycle approximating the Tamil Nadu community spread (OC 6, BC 5, MBC 4, SC 4, ST 1),
# interleaved so even the first 10 students of a small batch carry four categories.
CATEGORY_CYCLE = [*["OC", "BC", "MBC", "SC"] * 4, "OC", "BC", "OC", "ST"]
CATEGORIES = sorted(set(CATEGORY_CYCLE))

ALL_COMPANIES = [name for name, _abbr, _parent in COMPANIES]
# username -> (roles, companies the user is limited to)
USERS = {
	"principal": (["Principal"], [ENGINEERING]),
	"hod_cse": (["HOD", "Instructor"], [ENGINEERING]),
	"faculty_1": (["Instructor"], [ENGINEERING]),
	"faculty_2": (["Instructor"], [ENGINEERING]),
	"faculty_3": (["Instructor"], [ENGINEERING]),
	"coe": (["COE"], [ENGINEERING]),
	"exam_confidential": (["Exam Confidential"], [ENGINEERING]),
	"iqac": (["IQAC Coordinator"], [ENGINEERING]),
	"accounts": (["Accounts User"], ALL_COMPANIES),
	"warden": (["Warden"], ALL_COMPANIES),
	"student_1": (["Student"], [ENGINEERING]),
	"guardian_1": (["Guardian"], [ENGINEERING]),
}
# Roles granted by Position Holders instead of directly.
POSITION_ROLES = {"Principal", "HOD"}
EMPLOYEES = ["principal", "hod_cse", "faculty_1", "faculty_2", "faculty_3", "coe", "iqac"]
INSTRUCTORS = ["hod_cse", "faculty_1", "faculty_2", "faculty_3"]


def email(username):
	return f"{username}@{DOMAIN}"


def year_name(start_year):
	return f"{start_year}-{str(start_year + 1)[-2:]}"


def make_demo(scale="small"):
	"""Build the standard demo data. `scale` is "small" (fast tests) or "full" (demos, 60 per batch)."""
	if scale not in STUDENTS_PER_BATCH:
		frappe.throw(f"Unknown demo scale {scale!r}; use 'small' or 'full'.")
	was_importing = frappe.flags.in_import
	frappe.flags.in_import = True  # bulk load: skip Frappe's 60-users-per-minute creation throttle
	try:
		build_demo(scale)
	finally:
		frappe.flags.in_import = was_importing


def build_demo(scale):
	make_companies()
	make_departments()
	make_academic_years()
	make_programs()
	make_regulations()
	make_users()
	make_employees()
	make_institution_profiles()
	make_service_agreements()
	make_position_holders()
	make_categories()
	batches = FULL_BATCHES if scale == "full" else SMALL_BATCHES
	make_students(batches, STUDENTS_PER_BATCH[scale])
	make_student_users()
	assign_missing_regulations()


def get_or_insert(doctype, filters, values):
	"""Name of the `doctype` record matching `filters`; created from `filters` + `values` if missing."""
	name = frappe.db.exists(doctype, filters)
	if name:
		return name
	doc = frappe.get_doc({"doctype": doctype, **(filters if isinstance(filters, dict) else {}), **values})
	doc.insert(ignore_permissions=True)
	return doc.name


def make_companies():
	for name, abbr, parent in COMPANIES:
		make_company(name, abbr, is_group=0 if parent else 1, parent_company=parent)


def department_name(department, company):
	return f"{department} - {frappe.db.get_value('Company', company, 'abbr')}"


def make_departments():
	for company, department in {(c, d) for c, d, _slug in PROGRAMS.values()}:
		name = department_name(department, company)
		if not frappe.db.exists("Department", name):
			frappe.get_doc(
				{
					"doctype": "Department",
					"department_name": department,
					"company": company,
					"parent_department": "All Departments",
				}
			).insert(ignore_permissions=True)


def make_academic_years():
	for start in ACADEMIC_YEARS:
		year = year_name(start)
		get_or_insert(
			"Academic Year",
			{"academic_year_name": year},
			{"year_start_date": f"{start}-06-01", "year_end_date": f"{start + 1}-05-31"},
		)
		for term, term_start, term_end in (
			("Odd", f"{start}-06-01", f"{start}-11-30"),
			("Even", f"{start + 1}-01-01", f"{start + 1}-05-31"),
		):
			get_or_insert(
				"Academic Term",
				{"academic_year": year, "term_name": term},
				{"term_start_date": term_start, "term_end_date": term_end},
			)


def make_programs():
	for program, (company, department, _slug) in PROGRAMS.items():
		get_or_insert(
			"Program",
			{"program_name": program},
			{"oc_company": company, "department": department_name(department, company)},
		)


def make_regulations():
	for code, company, start, programs in REGULATIONS:
		if frappe.db.exists("Regulation", {"code": code, "company": company}):
			continue
		frappe.get_doc(
			{
				"doctype": "Regulation",
				"code": code,
				"company": company,
				"effective_from_year": year_name(start),
				"status": "Effective",
				"programs": [{"program": program} for program in programs],
			}
		).insert(ignore_permissions=True)


def make_users():
	for username, (roles, companies) in USERS.items():
		user = email(username)
		if not frappe.db.exists("User", user):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": user,
					"first_name": username,
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
		grant_roles(user, [r for r in roles if r not in POSITION_ROLES])
		for company in companies:
			get_or_insert("User Permission", {"user": user, "allow": "Company", "for_value": company}, {})


def grant_roles(user, roles):
	"""Add the roles that exist on this site; missing ones (not built yet) are skipped."""
	held = set(frappe.get_all("Has Role", filters={"parent": user, "parenttype": "User"}, pluck="role"))
	missing = [role for role in roles if role not in held and frappe.db.exists("Role", role)]
	if missing:
		frappe.get_doc("User", user).add_roles(*missing)


def make_employees():
	for username in EMPLOYEES:
		user = email(username)
		employee = frappe.db.get_value("Employee", {"user_id": user})
		if not employee:
			employee = frappe.get_doc(
				{
					"doctype": "Employee",
					"naming_series": "HR-EMP-",
					"first_name": username,
					"gender": get_or_insert("Gender", {"gender": "Female"}, {}),
					"date_of_birth": "1980-01-01",
					"date_of_joining": "2015-06-01",
					"status": "Active",
					"company": ENGINEERING,
					"user_id": user,
					"create_user_permission": 0,
				}
			)
			employee.insert(ignore_permissions=True)
			employee = employee.name
		if username in INSTRUCTORS:
			make_instructor(username, employee)


def make_instructor(username, employee):
	if frappe.db.exists("Instructor", {"employee": employee}):
		return
	frappe.get_doc(
		{
			"doctype": "Instructor",
			"instructor_name": username,
			"employee": employee,
			"oc_company": ENGINEERING,
			"department": department_name(CSE_DEPARTMENT, ENGINEERING),
		}
	).insert(ignore_permissions=True)


def employee_of(username):
	return frappe.db.get_value("Employee", {"user_id": email(username)})


def make_institution_profiles():
	profiles = {
		TRUST: {"institution_status": "Affiliated"},
		ENGINEERING: {
			"segment": "Engineering",
			"institution_status": "Autonomous",
			"status_effective_from": AUTONOMY_DATE,
			"autonomy_conferred_on": AUTONOMY_DATE,
			"affiliating_university": AFFILIATING_UNIVERSITY,
			"principal": employee_of("principal"),
			"coe": employee_of("coe"),
			"iqac_coordinator": employee_of("iqac"),
		},
		ARTS: {
			"segment": "Arts & Science",
			"institution_status": "Affiliated",
			"status_effective_from": "2015-06-01",
			"affiliating_university": "University of Madras",
		},
	}
	for company, values in profiles.items():
		if not frappe.db.exists("Institution Profile", company):
			frappe.get_doc({"doctype": "Institution Profile", "company": company, **values}).insert(
				ignore_permissions=True
			)


def make_service_agreements():
	"""The trust owns hostel and transport and serves both colleges."""
	for service in ("Hostel", "Transport"):
		if frappe.db.exists("Shared Service Agreement", {"provider_company": TRUST, "service": service}):
			continue
		frappe.get_doc(
			{
				"doctype": "Shared Service Agreement",
				"provider_company": TRUST,
				"service": service,
				"invoicing_company": TRUST,
				"from_date": "2022-06-01",
				"members": [{"company": ENGINEERING}, {"company": ARTS}],
			}
		).insert(ignore_permissions=True)


def make_position_holders():
	holdings = [
		("PRINCIPAL", ENGINEERING, "principal"),
		("HOD", department_name(CSE_DEPARTMENT, ENGINEERING), "hod_cse"),
	]
	for position, scope, username in holdings:
		get_or_insert(
			"Position Holder",
			{"position": position, "scope_value": scope, "user": email(username)},
			{"employee": employee_of(username), "from_date": "2022-06-01"},
		)


def make_categories():
	for category in CATEGORIES:
		get_or_insert("Student Category", {"category": category}, {})


def student_email(slug, batch, number):
	if (slug, batch, number) == ("cse", FULL_BATCHES[-1], 1):
		return email("student_1")
	return f"{slug}-{batch}-{number:03d}@{DOMAIN}"


def category_for(number):
	"""Student category of the `number`-th (1-based) student of every program batch."""
	return CATEGORY_CYCLE[(number - 1) % len(CATEGORY_CYCLE)]


def expected_regulation_code(batch):
	"""Code of the engineering regulation that governs admission year `batch` (start year)."""
	starts = [(start, code) for code, company, start, _programs in REGULATIONS if company == ENGINEERING]
	return max((start, code) for start, code in starts if start <= batch)[1]


def make_students(batches, per_batch):
	students = {
		row.student_email_id: row.name
		for row in frappe.get_all(
			"Student", filters=[["student_email_id", "like", f"%@{DOMAIN}"]], fields=["name", "student_email_id"]
		)
	}
	enrollments = {
		row.student: row
		for row in frappe.get_all(
			"Program Enrollment",
			filters={"student": ["in", list(students.values())], "docstatus": ["<", 2]},
			fields=["name", "student", "docstatus", "student_category"],
		)
	}
	for program, (company, _department, slug) in PROGRAMS.items():
		if not slug:
			continue
		for batch in batches:
			for number in range(1, per_batch + 1):
				address = student_email(slug, batch, number)
				student = students.get(address) or make_student(company, slug, batch, number, address)
				ensure_enrollment(student, program, batch, number, enrollments.get(student))


def make_student(company, slug, batch, number, address):
	student = frappe.get_doc(
		{
			"doctype": "Student",
			"first_name": "Student",
			"last_name": f"{slug.upper()}{batch}-{number:03d}",
			"student_email_id": address,
			"oc_company": company,
			"joining_date": f"{batch}-07-15",
		}
	)
	student.insert(ignore_permissions=True)
	return student.name


def ensure_enrollment(student, program, batch, number, enrollment):
	"""Make sure `student` has a submitted enrollment with its category (repairs interrupted runs)."""
	category = category_for(number)
	if enrollment and enrollment.docstatus == 1:
		if enrollment.student_category != category:
			frappe.db.set_value("Program Enrollment", enrollment.name, "student_category", category)
		return
	doc = frappe.get_doc("Program Enrollment", enrollment.name) if enrollment else frappe.new_doc(
		"Program Enrollment"
	)
	doc.update(
		{
			"student": student,
			"program": program,
			"academic_year": year_name(batch),
			"enrollment_date": f"{batch}-07-15",
			"student_category": category,
		}
	)
	doc.save(ignore_permissions=True)
	doc.submit()


def assign_missing_regulations():
	"""Fill-the-gaps: demo students created before their regulation existed get it now."""
	students = frappe.get_all(
		"Student",
		filters={"student_email_id": ["like", f"%@{DOMAIN}"], "oc_regulation": ["is", "not set"]},
		fields=["name", "oc_company", "oc_batch"],
	)
	for student in students:
		enrollment = latest_enrollment(student.name)
		regulation = enrollment and resolve_regulation(
			student.oc_company, enrollment.program, student.oc_batch or enrollment.academic_year
		)
		if regulation:
			frappe.db.set_value("Student", student.name, "oc_regulation", regulation)


def make_student_users():
	"""Link student_1 and guardian_1 to the first CSE student and a Guardian record."""
	student = frappe.db.get_value("Student", {"student_email_id": email("student_1")})
	if not student:
		return
	frappe.db.set_value("Student", student, "user", email("student_1"), update_modified=False)
	guardian = get_or_insert(
		"Guardian",
		{"email_address": email("guardian_1")},
		{"guardian_name": "Guardian One", "user": email("guardian_1")},
	)
	if not frappe.db.exists("Student Guardian", {"parent": student, "guardian": guardian}):
		doc = frappe.get_doc("Student", student)
		doc.append("guardians", {"guardian": guardian, "guardian_name": "Guardian One", "relation": "Father"})
		doc.save(ignore_permissions=True)


def counts():
	"""Record counts per doctype for the demo data (used by tests and the report)."""
	return {
		"Company": frappe.db.count("Company", {"name": ["in", ALL_COMPANIES]}),
		"Program": frappe.db.count("Program", {"name": ["in", list(PROGRAMS)]}),
		"Regulation": frappe.db.count(
			"Regulation", {"name": ["in", [regulation_name(code, company) for code, company, *_ in REGULATIONS]]}
		),
		"Student": frappe.db.count("Student", {"student_email_id": ["like", f"%@{DOMAIN}"]}),
		"User": frappe.db.count("User", {"name": ["like", f"%@{DOMAIN}"]}),
	}
