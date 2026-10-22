"""M07-01 Faculty counts for one company and academic year (NAAC 2.2.2, 2.4.1-2.4.3), shared by the reports and the
IQAC data points so both give the same numbers.

A teacher of the year is an Employee with Staff Type Teaching who joined on or before the year end and was not
relieved before the year start: Left staff count only with a relieving date on or after the year start (Left with no
relieving date is a data issue, see `left_without_relieving_date`). Employees are read with the session user's
permissions, so a user limited to a department or company sees only that part. Teaching experience (2.4.3) is experience in this institution: joining date to the
year end (or the relieving date), in years of 365.25 days. Students are those with a submitted Program Enrollment in
the year, by the program's department (as the IQAC `total_students` data point).
"""

from math import ceil

import frappe
from frappe.utils import date_diff, flt, getdate

from campus.faculty.norms import norm_in_force
from campus.faculty.setup import CADRES


def teachers(company, academic_year, department=None):
	start, end = year_bounds(academic_year)
	rows = frappe.get_list(
		"Employee", teaching_filters(company, end, department),
		["name", "employee_name", "department", "oc_cadre", "oc_phd_status", "oc_phd_awarded_on",
			"date_of_joining", "relieving_date", "status"],
		order_by="department, name", limit_page_length=0,
	)  # fmt: skip
	return [r for r in rows if on_roll(r, start)]


def teaching_filters(company, year_end, department=None):
	filters = {"company": company, "oc_staff_type": "Teaching", "date_of_joining": ["<=", year_end]}
	if department:
		filters["department"] = department
	return filters


def on_roll(employee, year_start):
	if employee.status == "Left" and not employee.relieving_date:
		return False
	return not employee.relieving_date or getdate(employee.relieving_date) >= year_start


def left_without_relieving_date(company, academic_year, department=None):
	"""Teaching employees marked Left with no relieving date: left out of the counts until HR fixes the record."""
	filters = {**teaching_filters(company, year_bounds(academic_year)[1], department), "status": "Left", "relieving_date": ["is", "not set"]}
	return frappe.get_list("Employee", filters, ["name", "employee_name"], order_by="name", limit_page_length=0)


def sanctioned_posts(company, academic_year, department=None):
	filters = {"company": company, "academic_year": academic_year}
	if department:
		filters["department"] = department
	return frappe.get_all("Sanctioned Post", filters, ["name", "department", "cadre", "sanctioned_count"], order_by="department")


def has_phd(teacher, academic_year):
	if teacher.oc_phd_status != "Awarded":
		return False
	return not teacher.oc_phd_awarded_on or getdate(teacher.oc_phd_awarded_on) <= year_bounds(academic_year)[1]


def experience_years(teacher, academic_year):
	end = year_bounds(academic_year)[1]
	until = min(end, getdate(teacher.relieving_date)) if teacher.relieving_date else end
	return flt(max(date_diff(until, teacher.date_of_joining) + 1, 0) / 365.25, 1)


def students_by_department(company, academic_year):
	"""{department: distinct students} with a submitted Program Enrollment of the company in the year."""
	rows = frappe.get_all(
		"Program Enrollment", {"oc_company": company, "academic_year": academic_year, "docstatus": 1}, ["student", "program"]
	)
	departments = dict(frappe.get_all("Program", {"name": ["in", list({r.program for r in rows}) or [""]]}, ["name", "department"], as_list=1))
	students = {}
	for row in rows:
		students.setdefault(departments.get(row.program), set()).add(row.student)
	return students


def faculty_vs_sanctioned(company, academic_year, department=None):
	filled = {}
	for teacher in teachers(company, academic_year, department):
		filled.setdefault((teacher.department, teacher.oc_cadre), []).append(teacher.name)
	posts = {(p.department, p.cadre): p.sanctioned_count for p in sanctioned_posts(company, academic_year, department)}
	rows = []
	for key in sorted(set(posts) | set(filled), key=sort_key):
		count = len(filled.get(key, []))
		sanctioned = posts.get(key, 0)
		rows.append({"department": key[0], "cadre": key[1], "sanctioned": sanctioned, "filled": count, "vacant": max(sanctioned - count, 0)})
	return rows


def cadre_ratio(company, academic_year, department=None):
	"""Per department and cadre: required = ceil(students / SFR) split by the norm's shares (half-up), vs actual."""
	norm = norm_in_force(company, year_bounds(academic_year)[1])
	if not norm:
		return []
	shares = {row.cadre: row.ratio_share for row in norm.cadres}
	total_share = sum(shares.values()) or 1
	students = students_by_department(company, academic_year)
	actual = {}
	for teacher in teachers(company, academic_year, department):
		actual.setdefault(teacher.department, {}).setdefault(teacher.oc_cadre, 0)
		actual[teacher.department][teacher.oc_cadre] += 1
	departments = sorted((set(students) | set(actual)) - {None})
	rows = []
	for dept in [d for d in departments if not department or d == department]:
		required_total = ceil(len(students.get(dept, ())) / norm.student_faculty_ratio) if norm.student_faculty_ratio else 0
		for cadre in [c for c in CADRES if c in shares]:
			required = int(required_total * shares[cadre] / total_share + 0.5)
			have = actual.get(dept, {}).get(cadre, 0)
			rows.append({"department": dept, "cadre": cadre, "share": shares[cadre], "required": required,
				"actual": have, "shortfall": max(required - have, 0)})  # fmt: skip
	return rows


def student_teacher_ratio(company, academic_year, department=None):
	norm = norm_in_force(company, year_bounds(academic_year)[1])
	students = students_by_department(company, academic_year)
	staff = {}
	for teacher in teachers(company, academic_year, department):
		staff[teacher.department] = staff.get(teacher.department, 0) + 1
	rows = []
	for dept in sorted((set(students) | set(staff)) - {None}):
		if department and dept != department:
			continue
		count, teaching = len(students.get(dept, ())), staff.get(dept, 0)
		rows.append({"department": dept, "students": count, "teachers": teaching,
			"ratio": flt(count / teaching, 2) if teaching else None, "norm": norm.student_faculty_ratio if norm else None})  # fmt: skip
	return rows


def year_bounds(academic_year):
	start, end = frappe.get_cached_value("Academic Year", academic_year, ["year_start_date", "year_end_date"])
	return getdate(start), getdate(end)


def sort_key(key):
	department, cadre = key
	return (department or "", CADRES.index(cadre) if cadre in CADRES else len(CADRES))
