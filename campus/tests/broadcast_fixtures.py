"""Shared fixtures for the broadcast and circular tests (P1-T11): one college with students, guardians, staff."""

import frappe
from frappe.utils import add_days, today

from campus.tests.factories import make_company, make_user

COLLEGE = "T11 College"
OTHER_COLLEGE = "T11 Other College"
CSE = "T11 B.E. CSE"
ECE = "T11 B.E. ECE"
YEAR = "T11 AY"
DEPARTMENT = "T11 Computing"
OTHER_DEPARTMENT = "T11 Mechanics"
GROUP = "T11 Group A"
STUDENT_USER = "t11-student@example.com"
GUARDIAN_USER = "t11-guardian@example.com"
OUTSIDE_GUARDIAN_USER = "t11-guardian-outside@example.com"
OTHER_COLLEGE_USER = "t11-other@example.com"
STAFF_USER = "t11-staff@example.com"
LOOKUP = {}


def ensure(doctype, filters, values=None):
	name = frappe.db.exists(doctype, filters)
	if name:
		return name
	return frappe.get_doc({"doctype": doctype, **filters, **(values or {})}).insert(ignore_permissions=True).name


def make_login(email, role, companies=(COLLEGE,)):
	make_user(email, list(companies))
	user = frappe.get_doc("User", email)
	user.roles = [r for r in user.roles if r.role != "Academics User"]
	if role and not any(r.role == role for r in user.roles):
		user.append("roles", {"role": role})
	user.save(ignore_permissions=True)


def make_student(first_name, company, program, enabled=1, user=None):
	name = frappe.db.get_value("Student", {"student_email_id": f"{first_name.lower()}@t11.example.com"})
	if name:
		return name
	# Education creates a website user per student unless told otherwise; `user` re-points it afterwards.
	student = frappe.get_doc(
		{
			"doctype": "Student",
			"first_name": first_name,
			"student_email_id": f"{first_name.lower()}@t11.example.com",
			"oc_company": company,
			"enabled": enabled,
		}
	).insert(ignore_permissions=True)
	if user:
		frappe.db.set_value("Student", student.name, "user", user)
	enrollment = frappe.get_doc(
		{"doctype": "Program Enrollment", "student": student.name, "program": program, "academic_year": YEAR}
	)
	enrollment.insert(ignore_permissions=True)
	enrollment.submit()
	return student.name


def make_guardian(first_name, students, user=None):
	name = frappe.db.get_value("Guardian", {"guardian_name": first_name})
	if name:
		return name
	guardian = frappe.get_doc(
		{
			"doctype": "Guardian",
			"guardian_name": first_name,
			"email_address": f"{first_name.lower().replace(' ', '')}@t11.example.com",
			"user": user,
		}
	).insert(ignore_permissions=True)
	for student in students:
		doc = frappe.get_doc("Student", student)
		doc.append("guardians", {"guardian": guardian.name, "guardian_name": first_name, "relation": "Father"})
		doc.save(ignore_permissions=True)
	return guardian.name


def make_employee(first_name, department):
	return ensure(
		"Employee",
		{"first_name": first_name, "company": COLLEGE},
		{
			"naming_series": "HR-EMP-",
			"gender": ensure("Gender", {"gender": "Female"}),
			"date_of_birth": "1985-01-01",
			"date_of_joining": "2020-06-01",
			"status": "Active",
			"department": department,
			"create_user_permission": 0,
		},
	)


def setup_world():
	"""Idempotent: companies, programs, students (and their guardians), a group, departments, employees, logins."""
	make_company(COLLEGE, "T11C")
	make_company(OTHER_COLLEGE, "T11O")
	ensure("Academic Year", {"academic_year_name": YEAR}, {"year_start_date": add_days(today(), -100), "year_end_date": add_days(today(), 200)})
	for program in (CSE, ECE):
		ensure("Program", {"program_name": program}, {"oc_company": COLLEGE})
	make_login(STUDENT_USER, "Student")
	make_login(GUARDIAN_USER, "Guardian")
	make_login(STAFF_USER, "Academics User")
	make_login(OUTSIDE_GUARDIAN_USER, "Guardian")
	make_login(OTHER_COLLEGE_USER, "Student", companies=(OTHER_COLLEGE,))
	s = LOOKUP
	s["asha"] = make_student("T11Asha", COLLEGE, CSE, user=STUDENT_USER)
	s["bala"] = make_student("T11Bala", COLLEGE, CSE)
	s["chitra"] = make_student("T11Chitra", COLLEGE, CSE)
	s["dev"] = make_student("T11Dev", COLLEGE, ECE)
	s["disabled"] = make_student("T11Gone", COLLEGE, CSE, enabled=0)
	s["g_asha"] = make_guardian("T11 Guardian Asha", [s["asha"], s["bala"]], user=GUARDIAN_USER)
	s["g_chitra"] = make_guardian("T11 Guardian Chitra", [s["chitra"]])
	s["g_dev"] = make_guardian("T11 Guardian Dev", [s["dev"]], user=OUTSIDE_GUARDIAN_USER)
	s["group"] = ensure_group()
	for department in (DEPARTMENT, OTHER_DEPARTMENT):
		ensure("Department", {"department_name": department, "company": COLLEGE})
	s["dept"] = frappe.db.get_value("Department", {"department_name": DEPARTMENT, "company": COLLEGE})
	s["other_dept"] = frappe.db.get_value("Department", {"department_name": OTHER_DEPARTMENT, "company": COLLEGE})
	s["emp_1"] = make_employee("T11Ravi", s["dept"])
	s["emp_2"] = make_employee("T11Meena", s["dept"])
	s["emp_other"] = make_employee("T11Kumar", s["other_dept"])
	return s


def ensure_group():
	name = frappe.db.get_value("Student Group", {"student_group_name": GROUP})
	if name:
		return name
	group = frappe.get_doc(
		{
			"doctype": "Student Group",
			"student_group_name": GROUP,
			"academic_year": YEAR,
			"group_based_on": "Batch",
			"program": CSE,
			"students": [
				{"student": LOOKUP["asha"]},
				{"student": LOOKUP["bala"]},
				{"student": LOOKUP["chitra"], "active": 0},  # left the group
				{"student": LOOKUP["disabled"], "active": 0},
			],
		}
	)
	return group.insert(ignore_permissions=True).name


def make_rule(name, rule_type, **filters):
	return frappe.get_doc(
		{"doctype": "Audience Rule", "rule_name": name, "company": COLLEGE, "rule_type": rule_type, **filters}
	).insert()


def make_template(event_key, purpose="transactional"):
	"""A one-channel (email) test template; urgent so quiet hours never delay it."""
	return ensure(
		"Message Template",
		{"event_key": event_key},
		{
			"purpose": purpose,
			"urgent": 1,
			"channels": [{"channel": "email"}],
			"bodies": [{"language": "en", "subject": "T11 {{ doc.title }}", "body": "Hello {{ doc.title }}"}],
		},
	)


def make_policy(document_type, approver=STAFF_USER):
	return frappe.get_doc(
		{
			"doctype": "Approval Policy",
			"policy_name": f"T11 {document_type} Policy",
			"document_type": document_type,
			"priority": 1,
			"levels": [{"approver_type": "User", "approver": approver}],
		}
	).insert()


def clear_documents():
	"""Remove broadcasts, circulars and their messages from earlier tests."""
	for doctype in ("Broadcast", "Circular"):
		names = frappe.get_all(doctype, pluck="name")
		frappe.db.delete("Message Log", {"reference_doctype": doctype})
		frappe.db.delete("Circular Acknowledgement", {"circular": ["in", names or [""]]})
		frappe.db.delete("Approval Request", {"reference_doctype": doctype})
		frappe.db.delete(doctype)
	runs = [
		name
		for prefix in ("Broadcast", "Circular")
		for name in frappe.get_all("Bulk Run", filters={"run_type": ["like", f"{prefix} %"]}, pluck="name")
	]
	for child in ("Bulk Run Item Key", "Bulk Run Row Error"):
		frappe.db.delete(child, {"parent": ["in", runs or [""]]})
	frappe.db.delete("Bulk Run", {"name": ["in", runs or [""]]})
	frappe.db.delete("Audience Rule", {"rule_name": ["like", "T11 %"]})
	frappe.db.delete("Approval Level", {"parenttype": "Approval Policy", "parent": ["like", "T11 %"]})
	frappe.db.delete("Approval Policy", {"name": ["like", "T11 %"]})
