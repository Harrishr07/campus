"""M03-08 Course Registrations made before the Program Enrollment field existed: bind each to the enrollment its
Course Enrollment rows already use, else the student's latest. DML only."""

import frappe

from campus.campus_platform.api import latest_enrollment


def execute():
	for registration in frappe.get_all(
		"Course Registration", {"program_enrollment": ["is", "not set"]}, ["name", "student"]
	):
		enrollment = enrollment_in_use(registration) or (latest_enrollment(registration.student) or {}).get("name")
		if enrollment:
			frappe.db.set_value("Course Registration", registration.name, "program_enrollment", enrollment, update_modified=False)


def enrollment_in_use(registration):
	courses = frappe.get_all("Course Registration Item", {"parent": registration.name}, pluck="course")
	return frappe.db.get_value(
		"Course Enrollment", {"student": registration.student, "course": ["in", courses or [""]]}, "program_enrollment"
	)
