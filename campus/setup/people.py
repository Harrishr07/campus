"""PR-02 Pilot people: one user per role of the profile with its Company User Permissions, the employees and instructors
behind the staff users, their Position Holders, the class group, and a pilot student with a guardian.

Passwords: on a developer-mode or demo site (`campus_demo_site`) a new user gets the profile's fixed TEST password. On any
other site no password is stored: each new user gets a one-time reset link in the run's `reset_links`, so the first login
sets their own password. On a demo site every desk user also gets the UAT Tester role (campus.campus_platform.uat). The generated people are synthetic; no real personal data is used.

Roles: the kit owns the roles its profile hands out (`kit_roles`). A re-run takes such a role away from a kit user whose
spec no longer lists it (e.g. Academics User, the office role, once given to teachers), so a site is corrected by re-running
the kit. Roles outside that set (HRMS's Employee, anything granted by hand) and roles an active position gives are left alone.
"""

import frappe
from frappe import _
from frappe.utils.password import update_password

from campus.campus_platform.positions import active_holdings
from campus.campus_platform.uat import tester_roles_for
from campus.setup.records import upsert
from campus.setup.structure import department_name


def test_passwords_allowed():
	return bool(frappe.conf.developer_mode or frappe.conf.campus_demo_site)


def user_email(profile, key):
	return f"{key}@{profile['user_domain']}"


def missing_roles(profile):
	roles = {role for user in profile.get("users", []) for role in user["roles"]}
	return sorted(role for role in roles if not frappe.db.exists("Role", role))


def kit_roles(profile):
	"""The roles the kit manages: every role a user of the profile is given."""
	return {role for user in profile.get("users", []) for role in user["roles"]}


def ensure_people(profile, companies, out, test_passwords, result):
	"""Create the users and what hangs on them; returns {user key: Employee name} for the staff with an employee record."""
	if test_passwords and not test_passwords_allowed():
		frappe.throw(_("Test passwords are for developer-mode or demo sites only."))
	group = ensure_class_group(profile, companies["college"], out)
	managed = kit_roles(profile)
	employees = {}
	for spec in profile["users"]:
		user = ensure_user(profile, spec, out, test_passwords, result)
		for token in spec.get("companies", []):
			upsert(out, "User Permission", {"user": user, "allow": "Company", "for_value": companies[token]})
		if spec.get("employee"):
			employees[spec["key"]] = ensure_employee(profile, spec, user, companies["college"], out)
		if spec.get("position"):
			ensure_position(profile, spec, user, companies["college"], group, employees.get(spec["key"]), out)
		wanted = spec["roles"] + (tester_roles_for(spec["roles"]) if test_passwords_allowed() else [])
		if sync_roles(user, wanted, managed):
			out.updated["User"] += 1
	ensure_pilot_student(profile, companies["college"], out)
	return employees


def ensure_user(profile, spec, out, test_passwords, result):
	email = user_email(profile, spec["key"])
	if frappe.db.exists("User", email):
		return email
	was_importing, frappe.flags.in_import = frappe.flags.in_import, True  # skip Frappe's 60-users-per-minute creation throttle
	try:
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": spec["name"], "enabled": 1, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	finally:
		frappe.flags.in_import = was_importing
	out.created["User"] += 1
	if test_passwords:
		if not test_passwords_allowed():
			frappe.throw(_("Test passwords are for developer-mode or demo sites only."))
		update_password(email, profile["test_password"])
	else:
		result["reset_links"][email] = user._reset_password(send_email=False, password_expired=True)
	return email


def sync_roles(user, roles, managed=()):
	"""Give `user` the `roles` it lacks and take away the `managed` roles it holds beyond them, except a role an active
	Position Holder gives it (campus.campus_platform.positions owns those); returns the roles taken away."""
	held = set(frappe.get_all("Has Role", filters={"parent": user, "parenttype": "User"}, pluck="role"))
	missing = [role for role in roles if role not in held]
	from_positions = {holding.role for holding in active_holdings(user)}
	surplus = sorted((held & set(managed)) - set(roles) - from_positions)
	if surplus:
		frappe.get_doc("User", user).remove_roles(*surplus)
	if missing:
		frappe.get_doc("User", user).add_roles(*missing)
	return surplus


def ensure_employee(profile, spec, user, college, out):
	defaults = profile["people_defaults"]
	employee = frappe.db.get_value("Employee", {"user_id": user})
	if not employee:
		employee = frappe.get_doc(
			{
				"doctype": "Employee", "naming_series": "HR-EMP-", "first_name": spec["name"], "gender": defaults["gender"],
				"date_of_birth": defaults["date_of_birth"], "date_of_joining": defaults["date_of_joining"],
				"status": "Active", "company": college, "user_id": user, "create_user_permission": 0,
				"department": department_name(spec["department"], college) if spec.get("department") else None,
			}
		).insert(ignore_permissions=True).name
		out.created["Employee"] += 1
	if spec.get("instructor"):
		upsert(
			out, "Instructor", {"employee": employee},
			{"instructor_name": spec["name"], "oc_company": college, "department": department_name(spec["department"], college)},
		)
	return employee


def ensure_class_group(profile, college, out):
	spec = profile.get("class_group")
	if not spec:
		return None
	return upsert(
		out, "Student Group", {"student_group_name": spec["name"], "academic_year": spec["academic_year"]},
		{"group_based_on": "Batch", "program": spec["programme"]},
	)


def ensure_position(profile, spec, user, college, group, employee, out):
	position = spec["position"]
	scopes = {
		"college": college,
		"department": position.get("department") and department_name(position["department"], college),
		"group": group,
	}
	upsert(
		out, "Position Holder", {"position": position["code"], "scope_value": scopes[position["scope"]], "user": user},
		{"employee": employee, "from_date": profile["people_defaults"]["positions_from"]},
	)


def ensure_pilot_student(profile, college, out):
	"""The student user's Student record and the guardian user's Guardian record, linked to each other."""
	student_spec = next((u for u in profile["users"] if u.get("student")), None)
	if not student_spec:
		return
	email = user_email(profile, student_spec["key"])
	student = upsert(
		out, "Student", {"student_email_id": email},
		{"first_name": student_spec["name"], "oc_company": college, "joining_date": student_spec["student"]["joining_date"]},
	)
	if frappe.db.get_value("Student", student, "user") != email:
		frappe.db.set_value("Student", student, "user", email, update_modified=False)
	guardian_spec = next((u for u in profile["users"] if u.get("guardian")), None)
	if not guardian_spec:
		return
	guardian_email = user_email(profile, guardian_spec["key"])
	guardian = upsert(
		out, "Guardian", {"email_address": guardian_email}, {"guardian_name": guardian_spec["name"], "user": guardian_email}
	)
	if not frappe.db.exists("Student Guardian", {"parent": student, "guardian": guardian}):
		doc = frappe.get_doc("Student", student)
		doc.append("guardians", {"guardian": guardian, "guardian_name": guardian_spec["name"], "relation": guardian_spec["guardian"]["relation"]})
		doc.save(ignore_permissions=True)
		out.updated["Student"] += 1
