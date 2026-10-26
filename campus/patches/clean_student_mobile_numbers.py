"""BUG-08: Strip floating-point decimal suffix ('.0') from mobile numbers across student, applicant and guardian records."""

import frappe


TARGETS = [
	("Student", "student_mobile_number"),
	("Student Applicant", "student_mobile_number"),
	("Guardian", "mobile_number"),
	("Student Attendance", "student_mobile_number"),
]


def execute():
	"""Cleans existing records in Student, Student Applicant, Guardian and Student Attendance that end in .0 or .00."""
	for doctype, field in TARGETS:
		if not frappe.db.has_column(doctype, field):
			continue

		frappe.db.sql(
			f"""
			UPDATE `tab{doctype}`
			SET `{field}` = SUBSTRING(`{field}`, 1, LENGTH(`{field}`) - 2)
			WHERE `{field}` LIKE '%.0'
			"""
		)
		frappe.db.sql(
			f"""
			UPDATE `tab{doctype}`
			SET `{field}` = SUBSTRING(`{field}`, 1, LENGTH(`{field}`) - 3)
			WHERE `{field}` LIKE '%.00'
			"""
		)

