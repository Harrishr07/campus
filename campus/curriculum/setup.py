"""M03-01 Curriculum module setup: Program and Course custom fields and the seeded Course Categories."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

MODULE = "Curriculum"

# code -> (title, counts toward programme credits). MC/AC/VAC are earned but not counted (R2022 4.9 / 12.6).
COURSE_CATEGORIES = {
	"HSMC": ("Humanities and Social Sciences including Management Courses", 1),
	"BSC": ("Basic Science Courses", 1),
	"ESC": ("Engineering Science Courses", 1),
	"PCC": ("Professional Core Courses", 1),
	"PEC": ("Professional Elective Courses", 1),
	"OEC": ("Open Elective Courses", 1),
	"EEC": ("Employability Enhancement Courses", 1),
	"MC": ("Mandatory Courses", 0),
	"AC": ("Audit Courses", 0),
	"VAC": ("Value Added Courses", 0),
}


def setup_curriculum():
	setup_curriculum_fields()
	seed_course_categories()


def setup_curriculum_fields():
	"""Create/refresh the curriculum fields on Program and Course. Idempotent."""
	program = [
		field("oc_curriculum_section", "Section Break", "Curriculum", "oc_company"),
		field(
			"oc_level", "Select", "Level", "oc_curriculum_section",
			options="\nUG\nPG\nDiploma\nPhD", in_standard_filter=1,
		),
		field("oc_degree", "Data", "Degree", "oc_level"),
		field("oc_discipline", "Data", "Discipline", "oc_degree"),
		field("oc_duration_years", "Float", "Duration (Years)", "oc_discipline"),
		field("oc_total_semesters", "Int", "Total Semesters", "oc_duration_years"),
		field("oc_curriculum_column", "Column Break", None, "oc_total_semesters"),
		field("oc_sanctioned_intake", "Int", "Sanctioned Intake", "oc_curriculum_column"),
		field("oc_lateral_entry_allowed", "Check", "Lateral Entry Allowed", "oc_sanctioned_intake"),
		field("oc_nba_accredited_until", "Date", "NBA Accredited Until", "oc_lateral_entry_allowed"),
	]  # fmt: skip
	course = [
		field("oc_course_section", "Section Break", "Curriculum Defaults", "oc_company"),
		field("oc_course_code", "Data", "Course Code", "oc_course_section", in_standard_filter=1, search_index=1),
		field(
			"oc_course_type", "Select", "Course Type", "oc_course_code",
			options="\nTheory\nLab\nTheory+Lab\nProject\nInternship\nClinical\nAudit",
		),
		field("oc_course_column", "Column Break", None, "oc_course_type"),
		field("oc_lecture_hours", "Float", "Default Lecture Periods", "oc_course_column"),
		field("oc_tutorial_hours", "Float", "Default Tutorial Periods", "oc_lecture_hours"),
		field("oc_practical_hours", "Float", "Default Practical Periods", "oc_tutorial_hours"),
		field("oc_credits", "Float", "Default Credits", "oc_practical_hours"),
	]  # fmt: skip
	student_group = [
		field("oc_offering_section", "Section Break", "Offering", "course"),
		field("oc_curriculum", "Link", "Curriculum", "oc_offering_section", options="Curriculum", read_only=1),
		field("oc_semester", "Int", "Semester", "oc_curriculum", read_only=1),
		field("oc_offering_column", "Column Break", None, "oc_semester"),
		field("oc_section", "Data", "Section", "oc_offering_column", in_standard_filter=1),
		field("oc_course_category", "Link", "Course Category", "oc_section", options="Course Category", read_only=1),
	]  # fmt: skip
	term = [
		field(
			"oc_semester_parity", "Select", "Semester Parity", "term_name",
			options="\nOdd\nEven", description="Which curriculum semesters run in this term; blank: guessed from the name or start month.",
		),
	]  # fmt: skip
	create_custom_fields(
		{"Program": program, "Course": course, "Student Group": student_group, "Academic Term": term}, update=True
	)


def field(fieldname, fieldtype, label, insert_after, **kwargs):
	return {
		"fieldname": fieldname,
		"fieldtype": fieldtype,
		"label": label,
		"insert_after": insert_after,
		"module": MODULE,
		**kwargs,
	}


def seed_course_categories():
	"""Create the standard categories that are missing; never overwrite a college's own edits."""
	for code, (title, counts) in COURSE_CATEGORIES.items():
		if not frappe.db.exists("Course Category", code):
			frappe.get_doc(
				{"doctype": "Course Category", "code": code, "title": title, "counts_toward_credits": counts}
			).insert(ignore_permissions=True)
