"""M03-08 Course Registrations made before the Program Enrollment field existed: bind each to the enrollment it
was made for. DML only.

The enrollment is the student's one created on or before the registration and whose academic year covers the
registration date. When several qualify, the Course Enrollment rows of the registration's courses decide, but only
if they name exactly one of them. Anything else is reported and left blank: never a guess.
"""

import frappe


def execute():
	unresolved = bind_registrations()
	if unresolved:
		print(
			f"Course Registration: no unique Program Enrollment for {', '.join(unresolved)}; left blank for review."
		)


def bind_registrations():
	"""Bind every unbound registration (any docstatus). Returns the names left unresolved."""
	unresolved = []
	for registration in frappe.get_all(
		"Course Registration",
		{"program_enrollment": ["is", "not set"]},
		["name", "student", "registration_date", "creation"],
		order_by="creation",
	):
		enrollment = choose_enrollment(covering_enrollments(registration), enrollments_in_use(registration))
		if enrollment:
			frappe.db.set_value(
				"Course Registration",
				registration.name,
				"program_enrollment",
				enrollment,
				update_modified=False,
			)
		else:
			unresolved.append(registration.name)
	return unresolved


def choose_enrollment(candidates, in_use):
	"""The only candidate, else the only candidate the Course Enrollment rows use, else None."""
	if len(candidates) == 1:
		return candidates[0]
	used = [name for name in candidates if name in in_use]
	return used[0] if len(used) == 1 else None


def covering_enrollments(registration):
	years = {
		year.name: year
		for year in frappe.get_all("Academic Year", fields=["name", "year_start_date", "year_end_date"])
	}
	return [
		enrollment.name
		for enrollment in frappe.get_all(
			"Program Enrollment",
			{
				"student": registration.student,
				"docstatus": ["<", 2],
				"creation": ["<=", registration.creation],
			},
			["name", "academic_year"],
		)
		if covers(years.get(enrollment.academic_year), registration.registration_date)
	]


def covers(year, date):
	return bool(year) and year.year_start_date <= date <= year.year_end_date


def enrollments_in_use(registration):
	courses = frappe.get_all("Course Registration Item", {"parent": registration.name}, pluck="course")
	return set(
		frappe.get_all(
			"Course Enrollment",
			{"student": registration.student, "course": ["in", courses or [""]]},
			pluck="program_enrollment",
		)
	)
