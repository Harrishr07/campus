"""M03-04 Course offerings: course-based Student Groups per curriculum course, term and section.

An offering is a Student Group named "{course}-{term}-{section}". The term's semester parity (odd or
even) selects which curriculum semesters are offered. Generation is idempotent.
"""

import frappe
from frappe import _
from frappe.utils import cint

from campus.curriculum.registration_rules import term_parity

OFFERABLE = ("Approved", "Effective")


@frappe.whitelist()
def generate_offerings(curriculum, academic_term, sections):
	"""Create the missing offerings of `curriculum` for `academic_term`; `sections` is a list or comma text.

	Returns {"created": [...], "existing": [...]} of Student Group names. A few hundred groups at most
	per call, so it runs inline rather than through the bulk runner.
	"""
	frappe.has_permission("Student Group", "create", throw=True)
	doc = frappe.get_doc("Curriculum", curriculum)
	frappe.has_permission("Curriculum", "read", doc=doc, throw=True)
	if doc.status not in OFFERABLE:
		frappe.throw(
			_("Curriculum {0} is {1}; offerings need an Approved or Effective curriculum.").format(
				doc.name, _(doc.status)
			)
		)
	term = frappe.db.get_value(
		"Academic Term",
		academic_term,
		["academic_year", "term_name", "term_start_date", "oc_semester_parity"],
		as_dict=True,
	)
	if not term:
		frappe.throw(_("Academic Term {0} does not exist.").format(frappe.bold(academic_term)))
	sections = parse_sections(sections)
	if not sections:
		frappe.throw(_("Give at least one section."))
	parity = term_parity(term.term_name, term.term_start_date, term.oc_semester_parity)
	elective_caps = seat_caps(doc.name)
	result = {"created": [], "existing": [], "skipped": []}
	for row in doc.courses:
		if not row.semester:
			result["skipped"].append(row.course)  # no semester: cannot tell which term offers it
			continue
		if row.semester % 2 != parity:
			continue
		for section in sections:
			name = f"{row.course}-{academic_term}-{section}"
			if frappe.db.exists("Student Group", name):
				result["existing"].append(name)
				continue
			make_offering(doc, row, term.academic_year, academic_term, section, name, elective_caps)
			result["created"].append(name)
	return result


def parse_sections(sections):
	if isinstance(sections, str):
		sections = frappe.parse_json(sections) if sections.strip().startswith("[") else sections.split(",")
	return list(dict.fromkeys(s.strip() for s in sections if s and s.strip()))


def seat_caps(curriculum):
	return {
		g.name: cint(g.seat_cap_per_course)
		for g in frappe.get_all(
			"Elective Group", filters={"curriculum": curriculum}, fields=["name", "seat_cap_per_course"]
		)
	}


def make_offering(curriculum, row, academic_year, academic_term, section, name, elective_caps):
	frappe.get_doc(
		{
			"doctype": "Student Group",
			"student_group_name": name,
			"group_based_on": "Course",
			"academic_year": academic_year,
			"academic_term": academic_term,
			"program": curriculum.program,
			"course": row.course,
			"max_strength": elective_caps.get(row.elective_group, 0),
			"oc_curriculum": curriculum.name,
			"oc_semester": row.semester,
			"oc_section": section,
			"oc_course_category": row.category,
		}
	).insert()
