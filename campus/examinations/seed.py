"""M12-02, M06-05, M05-03, M06-08 Seed values: Grading Scheme, Exam Rule Set, Classification Rule and CIA
Component Templates of the Anna University R2021 (affiliated) and the autonomous R2022 / R2026 regulations.

Source: docs/research/anna-university-autonomous-rules.md, section 3. Keyed by regulation code.
Where the note is silent the seed says so next to the value (see the P2-T12 report).
"""

import frappe

# letter, grade point, min mark, max mark, is pass, relative minimum (SD from the Box-Cox mean)
R2022_GRADES = [
	("O", 10, 91, 100, 1, 1.5), ("A+", 9, 81, 90, 1, 0.5), ("A", 8, 71, 80, 1, -0.5), ("B+", 7, 61, 70, 1, -1.0),
	("B", 6, 56, 60, 1, -1.5), ("C", 5, 50, 55, 1, 0), ("U", 0, 0, 49, 0, 0),
]  # fmt: skip
GRADES = {
	# R2021: the note lists the letters and points only; the ranges are those of R2022.
	"AU-R2021": [(*row[:5], 0) for row in R2022_GRADES],
	# R2022: the relative SD bounds are the classic mean +1.5 / +0.5 / -0.5 / -1.0 / -1.5 SD cut-offs.
	"R2022": R2022_GRADES,
	"R2026": [
		("S", 10, 91, 100, 1, 0), ("A+", 9, 81, 90, 1, 0), ("A", 8, 71, 80, 1, 0), ("B+", 7, 66, 70, 1, 0),
		("B", 6.5, 61, 65, 1, 0), ("C+", 6, 56, 60, 1, 0), ("C", 5, 50, 55, 1, 0), ("U", 0, 0, 49, 0, 0),
	],
}  # fmt: skip
GRADE_FIELDS = ("letter", "grade_point", "min_mark", "max_mark", "is_pass", "relative_min_z")
BASE_CODES = [("U", "Re-appear"), ("SA", "Shortage of attendance"), ("AB", "Absent")]
CODES = {
	"AU-R2021": [*BASE_CODES, ("W", "Withdrawal")],
	"R2022": [*BASE_CODES, ("WD", "Withdrawal")],
	"R2026": [*BASE_CODES, ("WC", "Withdrawal")],
}
# course type, method, minimum cohort; course types without a row are graded absolutely
METHODS = {
	"AU-R2021": [],
	"R2022": [("Theory", "Relative Box-Cox", 30), ("Theory with Lab", "Relative Box-Cox", 30)],
	"R2026": [],
}
# Online-course tables are not seeded: the note gives only their end rows (R2026 S 91-100 … C 40-45, U < 40).
GPA_EXCLUDED_CATEGORIES = ["MC"]
COUNT_ADDITIONAL_WITH_HONOURS = {"AU-R2021": 0, "R2022": 1, "R2026": 1}

# course type, CIA max, ESE max, ESE min %, total min %, ESE alone from attempt, ESE alone min %, revaluation
EXAM_RULE_FIELDS = (
	"course_type", "cia_max", "ese_max", "ese_min_pct", "total_min_pct",
	"ese_only_from_attempt", "ese_only_min_pct", "revaluation_allowed",
)  # fmt: skip
EXAM_RULES = {
	# R2021 has no theory-with-lab pattern; revaluation is for theory only.
	"AU-R2021": [
		("Theory", 40, 60, 45, 50, 0, 0, 1), ("Lab", 60, 40, 45, 50, 0, 0, 0), ("Project", 40, 60, 45, 50, 0, 0, 0),
	],
	# R2022: from the 3rd attempt the ESE alone at 50% passes; no revaluation for labs and projects (EEC).
	"R2022": [
		("Theory", 40, 60, 45, 50, 3, 50, 1), ("Theory with Lab", 50, 50, 45, 50, 3, 50, 1),
		("Lab", 60, 40, 45, 50, 3, 50, 0), ("Project", 60, 40, 45, 50, 3, 50, 0),
	],
	"R2026": [
		("Theory", 40, 60, 45, 50, 0, 0, 1), ("Theory with Lab", 50, 50, 45, 50, 0, 0, 1),
		("Lab", 60, 40, 45, 50, 0, 0, 0), ("Project", 60, 40, 45, 50, 0, 0, 0),
	],
}  # fmt: skip
# CIA carry-forward is stated for R2022 only. Absence as an attempt and the attempt cap are not in the note:
# an absence counts (university practice) and there is no cap beyond the programme duration.
ATTEMPT_RULES = {
	"AU-R2021": {"cia_carry_forward": 0, "absent_counts_as_attempt": 1, "max_attempts": 0, "internal_only_min_pct": 50},
	"R2022": {"cia_carry_forward": 1, "absent_counts_as_attempt": 1, "max_attempts": 0, "internal_only_min_pct": 50},
	"R2026": {"cia_carry_forward": 0, "absent_counts_as_attempt": 1, "max_attempts": 0, "internal_only_min_pct": 50},
}  # fmt: skip

# class, variant, CGPA min, first appearance required, max years (0: none), break of study included
CLASS_FIELDS = (
	"class_name",
	"variant",
	"cgpa_min",
	"first_appearance_required",
	"max_years",
	"break_of_study_included",
)
CLASSES = {
	"AU-R2021": [
		("First Class with Distinction", "Regular", 8.5, 1, 0, 0), ("First Class", "Regular", 6.5, 0, 0, 0),
		("Second Class", "Regular", 0, 0, 0, 0),
	],
	# R2022: within 5 years including the authorised break of study; Honours first class needs 7.5.
	"R2022": [
		("First Class with Distinction", "Honours", 8.5, 1, 5, 1), ("First Class", "Honours", 7.5, 0, 5, 1),
		("First Class with Distinction", "Regular", 8.5, 1, 5, 1), ("First Class", "Regular", 6.5, 0, 5, 1),
		("Second Class", "Regular", 0, 0, 0, 0),
	],
	"R2026": [
		("First Class with Distinction", "Honours", 8.5, 1, 0, 0),
		("First Class with Distinction", "Regular", 8.5, 1, 0, 0), ("First Class", "Regular", 6.5, 0, 0, 0),
		("Second Class", "Regular", 0, 0, 0, 0),
	],
}  # fmt: skip


# M06-08 CIA templates: course type -> (converted CIA max, attendance marks max, [(component, out of, weight)]).
# R2022 theory: two assessments of 100 (40 assignment + 60 test) -> 40; lab: 75 observation/record + 25 test -> 60.
# R2026 theory: the note gives 40 with up to 5 attendance marks; the assessment split is taken from R2022 (35 left).
# Theory with Lab (split by L-T-P), projects and the R2021 / R2026 labs are not seeded: the note gives no split.
TWO_ASSESSMENTS = [("Assignment 1", 40), ("Test 1", 60), ("Assignment 2", 40), ("Test 2", 60)]
CIA_TEMPLATES = {
	"AU-R2021": {},
	"R2022": {
		"Theory": (40, 0, [(c, out_of, out_of * 40 / 200) for c, out_of in TWO_ASSESSMENTS]),
		"Lab": (60, 0, [("Observation and Record", 75, 45), ("Test", 25, 15)]),
	},
	"R2026": {
		"Theory": (40, 5, [(c, out_of, out_of * 35 / 200) for c, out_of in TWO_ASSESSMENTS]),
	},
}


def rows(fields, values):
	return [dict(zip(fields, row, strict=True)) for row in values]


def grading_scheme(regulation, code):
	return {
		"doctype": "Grading Scheme",
		"regulation": regulation,
		"grades": rows(GRADE_FIELDS, GRADES[code]),
		"codes": rows(("code", "meaning"), CODES[code]),
		"methods": rows(("course_type", "method", "min_cohort"), METHODS[code]),
		"gpa_excluded_categories": [{"course_category": c} for c in GPA_EXCLUDED_CATEGORIES],
		"count_additional_with_honours": COUNT_ADDITIONAL_WITH_HONOURS[code],
	}


def exam_rule_set(regulation, code):
	return {
		"doctype": "Exam Rule Set",
		"regulation": regulation,
		"types": rows(EXAM_RULE_FIELDS, EXAM_RULES[code]),
		**ATTEMPT_RULES[code],
	}


def classification_rule(regulation, code):
	return {
		"doctype": "Classification Rule",
		"regulation": regulation,
		"classes": rows(CLASS_FIELDS, CLASSES[code]),
	}


def cia_templates(regulation, code):
	for course_type, (cia_max, attendance_max, components) in CIA_TEMPLATES[code].items():
		yield {
			"doctype": "CIA Component Template", "regulation": regulation, "course_type": course_type,
			"cia_max": cia_max, "round_to_integer": 1, "includes_attendance_marks": int(bool(attendance_max)),
			"attendance_max": attendance_max,
			"components": rows(("component", "max_marks", "weight"), components),
		}  # fmt: skip


def seed_regulation(regulation, code):
	"""Create the Grading Scheme, Exam Rule Set and Classification Rule of `regulation` (a Regulation name)
	from the values of regulation `code` when absent. Existing records are never changed (they lock once
	the regulation is Effective), so re-running is a no-op."""
	for doctype, values in (
		("Grading Scheme", grading_scheme),
		("Exam Rule Set", exam_rule_set),
		("Classification Rule", classification_rule),
	):
		if not frappe.db.exists(doctype, {"regulation": regulation}):
			frappe.get_doc(values(regulation, code)).insert(ignore_permissions=True)
	for template in cia_templates(regulation, code):
		if not frappe.db.exists("CIA Component Template", {"regulation": regulation, "course_type": template["course_type"]}):
			frappe.get_doc(template).insert(ignore_permissions=True)
