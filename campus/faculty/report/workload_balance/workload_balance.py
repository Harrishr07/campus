"""M07-02 Workload Balance: per teacher, the weekly hours allocated in the term (submitted Course Allocations) against
the cadre's minimum and maximum in the Faculty Norm in force, with a total row per report. Teachers of the company
with no allocation show as Under. Company and Academic Term are required; a user limited to other companies sees nothing."""

import frappe
from frappe import _
from frappe.utils import flt

from campus.campus_platform.company_scope import permitted_companies
from campus.faculty import workload

STATUS = {"under": "Under", "within": "Within", "over": "Over", "blocked": "Beyond Limit"}


def execute(filters=None):
	filters = scoped(filters)
	if not filters:
		return columns(), []
	rows = faculty_rows(filters)
	return columns(), with_department_totals(rows), None, None, summary(rows)


def scoped(filters):
	filters = frappe._dict(filters or {})
	if not (filters.company and filters.academic_term):
		return None
	permitted = permitted_companies(frappe.session.user)
	if permitted is not None and filters.company not in permitted:
		return None
	return filters


def faculty_rows(filters):
	on_date = frappe.db.get_value("Academic Term", filters.academic_term, "term_start_date")
	hours = allocated_hours(filters)
	rows = []
	for employee in teachers(filters, set(hours)):
		own = hours.get(employee.name, {"lecture": 0, "tutorial": 0, "practical": 0})
		total = own["lecture"] + own["tutorial"] + own["practical"]
		rule = employee.oc_cadre and workload.limits(filters.company, employee.oc_cadre, on_date)
		minimum, maximum, margin = rule or (0, 0, 0)
		rows.append({
			"faculty": employee.name, "faculty_name": employee.employee_name, "department": employee.department,
			"cadre": employee.oc_cadre, "lecture": own["lecture"], "tutorial": own["tutorial"], "practical": own["practical"],
			"total": total, "minimum": minimum, "maximum": maximum, "status": status_of(total, minimum, maximum, margin),
		})  # fmt: skip
	return rows


def with_department_totals(rows):
	"""The teacher rows, each department's rows followed by a bold total row of its hours."""
	result = []
	for department in dict.fromkeys(r["department"] for r in rows):
		members = [r for r in rows if r["department"] == department]
		result += members
		total = {"faculty_name": _("Total"), "department": department, "bold": 1}
		for field in ("lecture", "tutorial", "practical", "total"):
			total[field] = sum(r[field] for r in members)
		result.append(total)
	return result


def allocated_hours(filters):
	"""{employee: {"lecture", "tutorial", "practical"}} over the submitted allocations of the term and company."""
	names = frappe.get_all(
		"Course Allocation",
		filters={"academic_term": filters.academic_term, "company": filters.company, "docstatus": 1},
		pluck="name",
	)
	rows = frappe.get_all(
		"Course Allocation Row",
		filters={"parenttype": "Course Allocation", "parent": ["in", names or [""]]},
		fields=["faculty", "lecture_hours", "tutorial_hours", "practical_hours"],
	)
	hours = {}
	for row in rows:
		own = hours.setdefault(row.faculty, {"lecture": 0, "tutorial": 0, "practical": 0})
		own["lecture"] += flt(row.lecture_hours)
		own["tutorial"] += flt(row.tutorial_hours)
		own["practical"] += flt(row.practical_hours)
	return hours


def teachers(filters, allocated):
	"""Active teaching staff of the company (and department, if given), plus anyone allocated in the term."""
	conditions = {"company": filters.company, "status": "Active", "oc_staff_type": "Teaching"}
	if filters.department:
		conditions["department"] = filters.department
	found = frappe.get_all(
		"Employee",
		filters=conditions,
		fields=["name", "employee_name", "department", "oc_cadre"],
		order_by="department, employee_name",
	)
	extra = [a for a in allocated if a not in {e.name for e in found}]
	if extra and not filters.department:
		found += frappe.get_all(
			"Employee",
			filters={"name": ["in", extra]},
			fields=["name", "employee_name", "department", "oc_cadre"],
		)
	return found


def status_of(total, minimum, maximum, margin):
	level = workload.classify(total, maximum, margin)
	if level == workload.BLOCK:
		return STATUS["blocked"]
	if level == workload.WARN:
		return STATUS["over"]
	return STATUS["under"] if total < minimum else STATUS["within"]


def summary(rows):
	return [
		{"label": _("Teachers"), "value": len(rows), "datatype": "Int"},
		{"label": _("Total Weekly Hours"), "value": sum(r["total"] for r in rows), "datatype": "Float"},
		{"label": _("Under Minimum"), "value": sum(r["status"] == STATUS["under"] for r in rows), "datatype": "Int", "indicator": "orange"},
		{"label": _("Over Maximum"), "value": sum(r["status"] in (STATUS["over"], STATUS["blocked"]) for r in rows), "datatype": "Int", "indicator": "red"},
	]  # fmt: skip


def columns():
	hours = {"fieldtype": "Float", "width": 90}
	return [
		{"fieldname": "faculty", "label": _("Faculty"), "fieldtype": "Link", "options": "Employee", "width": 130},
		{"fieldname": "faculty_name", "label": _("Name"), "fieldtype": "Data", "width": 170},
		{"fieldname": "department", "label": _("Department"), "fieldtype": "Link", "options": "Department", "width": 200},
		{"fieldname": "cadre", "label": _("Cadre"), "fieldtype": "Data", "width": 150},
		{"fieldname": "lecture", "label": _("Lecture"), **hours},
		{"fieldname": "tutorial", "label": _("Tutorial"), **hours},
		{"fieldname": "practical", "label": _("Practical"), **hours},
		{"fieldname": "total", "label": _("Total / Week"), **hours},
		{"fieldname": "minimum", "label": _("Norm Min"), **hours},
		{"fieldname": "maximum", "label": _("Norm Max"), **hours},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 110},
	]  # fmt: skip
