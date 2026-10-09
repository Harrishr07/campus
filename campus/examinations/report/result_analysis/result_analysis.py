"""M17-06 Result Analysis: pass percentage by course, program or department (faculty) over the latest, ratified
results of the company's published sessions in the academic year (one session when given). By course each course
sitting counts; by program / department each Student Result counts, passing when every course is a Pass. The total
row with Final Year Only is the pass_percentage data point (AQAR 2.6.3); see campus.examinations.coe_reports.

Limited to the companies the user is permitted for and to the sessions and results the user may read."""

import frappe
from frappe import _
from frappe.utils import cint

from campus.examinations import coe_report_rules as rules
from campus.examinations import coe_reports

GROUPS = {"Course": "course", "Program": "program", "Department": "department"}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	group_by = filters.group_by if filters.group_by in GROUPS else "Program"
	return columns(group_by), data(filters, group_by) if coe_reports.in_scope(filters.company) else []


def columns(group_by):
	return [
		{"fieldname": "group", "label": _(group_by), "fieldtype": "Link", "options": group_by, "width": 200},
		{"fieldname": "appeared", "label": _("Appeared"), "fieldtype": "Int", "width": 110},
		{"fieldname": "passed", "label": _("Passed"), "fieldtype": "Int", "width": 110},
		{"fieldname": "pass_pct", "label": _("Pass %"), "fieldtype": "Percent", "width": 110},
	]


def data(filters, group_by):
	rows = coe_reports.year_outcomes(
		filters.company, filters.academic_year, lister=frappe.get_list, final_year=bool(cint(filters.final_year_only)),
		exam_session=filters.exam_session,
	)  # fmt: skip
	field = GROUPS[group_by]
	unit = (lambda r: (r["result"], r["course"])) if group_by == "Course" else (lambda r: r["result"])
	tally = rules.tally(rows, lambda r: r[field], unit)
	out = [line(group, counts) for group, counts in sorted(tally.items(), key=lambda item: item[0] or "")]
	if out:
		total = {"appeared": sum(c["appeared"] for c in tally.values()), "passed": sum(c["passed"] for c in tally.values())}
		out.append(line(_("Total"), total))
	return out


def line(group, counts):
	return {"group": group, **counts, "pass_pct": rules.percent(counts["passed"], counts["appeared"])}
