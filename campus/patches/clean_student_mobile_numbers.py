"""BUG-08: Strip floating-point decimal suffix ('.0') from mobile numbers across student, applicant and guardian records."""

import frappe
from campus.campus_platform.sanitize import clean_mobile_number

TARGETS = [
	("Student", "student_mobile_number"),
	("Student Applicant", "student_mobile_number"),
	("Guardian", "mobile_number"),
	("Student Attendance", "student_mobile_number"),
]


def execute():
	"""Cleans existing records in Student, Student Applicant, Guardian and Student Attendance."""
	for doctype, field in TARGETS:
		if not frappe.db.has_column(doctype, field):
			continue

		# Fast direct SQL update for trailing .0
		frappe.db.sql(
			f"""
			UPDATE `tab{doctype}`
			SET `{field}` = SUBSTRING(`{field}`, 1, LENGTH(`{field}`) - 2)
			WHERE `{field}` LIKE '%.0'
			"""
		)

		# Normalize any other formatting artifacts
		records = frappe.db.sql(
			f"""
			SELECT name, `{field}`
			FROM `tab{doctype}`
			WHERE `{field}` IS NOT NULL AND `{field}` != ''
			""",
			as_dict=True,
		)
		for row in records:
			original = row[field]
			cleaned = clean_mobile_number(original)
			if cleaned != original:
				frappe.db.set_value(doctype, row["name"], field, cleaned, update_modified=False)
