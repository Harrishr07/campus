"""PR-03 Faculty: three Instructors in each of the six departments (the three CSE ones come from the pilot kit), each a
user with an Employee record, designation and gender for the faculty tables, and a Head of Department position holder
in each department. Built with the pilot kit's own user, employee and position helpers."""

import frappe

from campus.setup import people
from campus.setup.pilot import decide_passwords
from campus.setup.records import upsert

DESIGNATIONS = ("Professor", "Associate Professor", "Assistant Professor")
FACULTY_PER_DEPARTMENT = 2  # besides the Head of Department
# The pilot kit's teacher role sets: teachers do not hold the office role (Academics User); a re-run takes it away.
HOD_ROLES = ["HOD", "Instructor"]
FACULTY_ROLES = ["Instructor"]


def load(ctx):
	"""Add the Heads of Department and faculty the pilot kit's CSE trio does not cover."""
	for designation in DESIGNATIONS:
		upsert(ctx.out, "Designation", {"designation_name": designation})
	upsert(ctx.out, "Employment Type", {"employee_type_name": "Full-time"})
	test_passwords = decide_passwords(None)
	result = {"reset_links": {}}
	pilot_departments = {user["department"] for user in ctx.profile["users"] if user.get("instructor")}
	for programme in ctx.profile["programmes"]:
		if programme["department"] not in pilot_departments:
			for spec in department_specs(ctx, programme):
				add_member(ctx, spec, test_passwords, result)
	profile_staff = [u for u in ctx.profile["users"] if u.get("instructor")]
	for index, spec in enumerate(profile_staff):
		set_personnel_details(ctx, spec["key"], spec["name"], "Professor" if spec.get("position") else DESIGNATIONS[1 + index % 2])
	ctx.result_links = result["reset_links"]


def department_specs(ctx, programme):
	"""User specs (the pilot kit's shape) of one department: its Head and its faculty."""
	slug = programme["abbr"].lower()
	specs = []
	for number in range(FACULTY_PER_DEPARTMENT + 1):
		head = number == 0
		key = f"hod-{slug}" if head else f"faculty-{slug}-{number}"
		person = ctx.people.make(key, 1990, 1968)
		spec = {
			"key": key, "name": ("Dr. " if head else "") + person.full_name, "department": programme["department"],
			"roles": HOD_ROLES if head else FACULTY_ROLES, "companies": ["college"], "employee": True, "instructor": True,
			"person": person, "designation": "Professor" if head else DESIGNATIONS[number],
		}  # fmt: skip
		if head:
			spec["position"] = {"code": "HOD", "scope": "department", "department": programme["department"]}
		specs.append(spec)
	return specs


def add_member(ctx, spec, test_passwords, result):
	profile = ctx.profile
	user = people.ensure_user(profile, spec, ctx.out, test_passwords, result)
	for token in spec["companies"]:
		upsert(ctx.out, "User Permission", {"user": user, "allow": "Company", "for_value": ctx.college})
	employee = people.ensure_employee(profile, spec, user, ctx.college, ctx.out)
	if spec.get("position"):
		people.ensure_position(profile, spec, user, ctx.college, None, employee, ctx.out)
	people.sync_roles(user, spec["roles"], people.kit_roles(profile))
	set_personnel_details(ctx, spec["key"], spec["name"], spec["designation"], spec["person"])


def set_personnel_details(ctx, key, name, designation, person=None):
	"""Designation, employment type, staff type (Teaching: the faculty data points count it), gender and birth date of the employee behind user `key` (the pilot kit sets one default)."""
	employee = frappe.db.get_value("Employee", {"user_id": people.user_email(ctx.profile, key)})
	if not employee:
		return
	person = person or ctx.people.make(f"profile-{key}", 1990, 1968)
	wanted = {"designation": designation, "employment_type": "Full-time", "oc_staff_type": "Teaching", "gender": person.gender, "date_of_birth": person.date_of_birth}
	stored = frappe.db.get_value("Employee", employee, list(wanted), as_dict=True)
	if any(stored[field] != value and str(stored[field]) != str(value) for field, value in wanted.items()):
		frappe.db.set_value("Employee", employee, wanted)
