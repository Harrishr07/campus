"""M14-01 Placement eligibility rules (pure, no database): why a student does or does not meet a drive's criteria.

`criteria` is a dict (min_cgpa, any_standing_arrears, max_standing_arrears, allow_arrear_history, gender, programs,
batches); `student` the student's live standing (cgpa, standing_arrears, had_arrears, gender, program, batch).
An empty gender, programs or batches means no restriction there; a minimum CGPA of 0 means none.
"""

from frappe import _
from frappe.utils import cint, flt


def reasons(criteria, student):
	"""Why `student` fails `criteria`: a list of messages, empty when the student is eligible."""
	found = []
	minimum = flt(criteria.get("min_cgpa"))
	if minimum and flt(student.get("cgpa")) < minimum:
		found.append(
			_("CGPA {0} is below the minimum {1}").format(flt(student.get("cgpa"), 2), flt(minimum, 2))
		)
	allowed = cint(criteria.get("max_standing_arrears"))
	if not cint(criteria.get("any_standing_arrears")) and cint(student.get("standing_arrears")) > allowed:
		found.append(
			_("{0} standing arrears; at most {1} allowed").format(
				cint(student.get("standing_arrears")), allowed
			)
		)
	if not cint(criteria.get("allow_arrear_history")) and student.get("had_arrears"):
		found.append(_("A history of arrears is not allowed"))
	if criteria.get("gender") and student.get("gender") != criteria["gender"]:
		found.append(_("Open to {0} students only").format(criteria["gender"]))
	if criteria.get("programs") and student.get("program") not in criteria["programs"]:
		found.append(_("Program {0} is not eligible").format(student.get("program") or _("not set")))
	if criteria.get("batches") and student.get("batch") not in criteria["batches"]:
		found.append(_("Batch {0} is not eligible").format(student.get("batch") or _("not set")))
	return found
