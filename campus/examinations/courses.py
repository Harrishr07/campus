"""M12-02 What a course offering is worth in an examination: type, credits and mark maxima.

The curriculum row of the offering (course + semester of its Curriculum) is the source; a blank
cia_max / ese_max falls back to the student's Exam Rule Set.
"""

import frappe
from frappe import _
from frappe.utils import flt

from campus.campus_platform.api import get_rule

COURSE_FIELDS = ["exam_type", "credits", "cia_max", "ese_max", "practical_periods"]


def offering_course(offering):
	"""{course, course_type, credits, cia_max, ese_max} of an offering; course_type None for Internal Only."""
	group = frappe.db.get_value(
		"Student Group", offering, ["course", "oc_curriculum", "oc_semester"], as_dict=True
	)
	row = group and frappe.db.get_value(
		"Curriculum Course",
		{"parent": group.oc_curriculum, "parenttype": "Curriculum", "course": group.course, "semester": group.oc_semester},
		COURSE_FIELDS,
		as_dict=True,
	)
	if not row:
		frappe.throw(_("Offering {0} has no curriculum course row.").format(frappe.bold(offering)))
	return {
		"course": group.course,
		"course_type": course_type(row),
		"credits": flt(row.credits),
		"cia_max": flt(row.cia_max),
		"ese_max": flt(row.ese_max),
	}


def course_type(row):
	if row.exam_type == "Internal Only":
		return None
	if row.exam_type == "Practical":
		return "Lab"
	if row.exam_type == "Project":
		return "Project"
	return "Theory with Lab" if flt(row.practical_periods) else "Theory"


def student_limits(student, course):
	"""Exam Rule Set values of the student's regulation for `course` (an offering_course dict), maxima resolved."""
	for row in get_rule(student, "Exam Rule Set").types:
		if row.course_type == course["course_type"]:
			return {
				"cia_max": course["cia_max"] or row.cia_max,
				"ese_max": course["ese_max"] or row.ese_max,
				"ese_min_pct": row.ese_min_pct,
				"total_min_pct": row.total_min_pct,
			}
	frappe.throw(
		_("The Exam Rule Set of the regulation of {0} has no {1} course type.").format(
			frappe.bold(student), frappe.bold(_(course["course_type"]))
		)
	)
