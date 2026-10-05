"""M12-02 Seed values: Grading Scheme and Exam Rule Set of the Anna University autonomous regulations.

Source: docs/research/anna-university-autonomous-rules.md, section 3. Keyed by regulation code.
"""

import frappe

# letter, grade point, min mark, max mark, is pass
GRADES = {
	"R2022": [
		("O", 10, 91, 100, 1), ("A+", 9, 81, 90, 1), ("A", 8, 71, 80, 1), ("B+", 7, 61, 70, 1),
		("B", 6, 56, 60, 1), ("C", 5, 50, 55, 1), ("U", 0, 0, 49, 0),
	],
	"R2026": [
		("S", 10, 91, 100, 1), ("A+", 9, 81, 90, 1), ("A", 8, 71, 80, 1), ("B+", 7, 66, 70, 1),
		("B", 6.5, 61, 65, 1), ("C+", 6, 56, 60, 1), ("C", 5, 50, 55, 1), ("U", 0, 0, 49, 0),
	],
}  # fmt: skip
CODES = [("U", "Re-appear"), ("SA", "Shortage of attendance"), ("AB", "Absent")]
# course type, CIA max, ESE max, ESE minimum %, total minimum %; the same for both regulations
EXAM_RULES = {
	code: [
		("Theory", 40, 60, 45, 50), ("Theory with Lab", 50, 50, 45, 50),
		("Lab", 60, 40, 45, 50), ("Project", 60, 40, 45, 50),
	]
	for code in GRADES
}  # fmt: skip


def seed_regulation(regulation, code):
	"""Create the Grading Scheme and Exam Rule Set of `regulation` (a Regulation name) when absent."""
	if not frappe.db.exists("Grading Scheme", regulation):
		frappe.get_doc(
			{
				"doctype": "Grading Scheme",
				"regulation": regulation,
				"grades": [
					dict(zip(("letter", "grade_point", "min_mark", "max_mark", "is_pass"), row)) for row in GRADES[code]
				],
				"codes": [{"code": c, "meaning": meaning} for c, meaning in CODES],
			}
		).insert(ignore_permissions=True)
	if not frappe.db.exists("Exam Rule Set", regulation):
		frappe.get_doc(
			{
				"doctype": "Exam Rule Set",
				"regulation": regulation,
				"types": [
					dict(zip(("course_type", "cia_max", "ese_max", "ese_min_pct", "total_min_pct"), row))
					for row in EXAM_RULES[code]
				],
			}
		).insert(ignore_permissions=True)
