"""M07-01 Faculty service API. Other modules call these, never the controllers (D7).

The data point functions return {"value", "records"} for the IQAC registry (campus/iqac/datapoints.py); all take
(company, academic_year, department=None).
"""

import frappe
from frappe import _
from frappe.utils import flt

from campus.faculty import development, self_appraisal, staffing, substitute_attendance
from campus.faculty import substitution as substitutions


def full_time_teachers(company, academic_year, department=None):
	"""NAAC 2.4.1 / 2.2.2: teachers on roll in the year."""
	return result(staffing.teachers(company, academic_year, department))


def sanctioned_posts(company, academic_year, department=None):
	"""NAAC 2.4.1: total sanctioned posts in the year."""
	posts = staffing.sanctioned_posts(company, academic_year, department)
	return {"value": sum(p.sanctioned_count or 0 for p in posts), "records": refs("Sanctioned Post", [p.name for p in posts])}


def phd_teachers(company, academic_year, department=None):
	"""NAAC 2.4.2: teachers with a PhD awarded by the year end."""
	return result([t for t in staffing.teachers(company, academic_year, department) if staffing.has_phd(t, academic_year)])


def teacher_experience_years(company, academic_year, department=None):
	"""NAAC 2.4.3: total years of teaching experience in this institution (divide by full_time_teachers for the average)."""
	rows = staffing.teachers(company, academic_year, department)
	total = sum(staffing.experience_years(t, academic_year) for t in rows)
	return {"value": flt(total, 1), "records": refs("Employee", [t.name for t in rows])}


def student_teacher_ratio(company, academic_year, department=None):
	"""NAAC 2.2.2: distinct students of the year per teacher (0 without teachers)."""
	by_department = staffing.students_by_department(company, academic_year)
	students = by_department.get(department, set()) if department else set().union(*by_department.values())
	staff = staffing.teachers(company, academic_year, department)
	return {"value": flt(len(students) / len(staff), 2) if staff else 0, "records": refs("Employee", [t.name for t in staff])}


def fdp_teachers(company, academic_year, department=None):
	"""NAAC 6.3.4: distinct teachers who attended at least one FDP (HRMS Training Event flagged as an FDP) in the year."""
	rows = development.fdp_attendances(company, academic_year, department)
	return {"value": len({r["employee"] for r in rows}), "records": refs("Employee", {r["employee"] for r in rows})}


def teachers_financially_supported(company, academic_year, department=None):
	"""NAAC 6.3.2: distinct teachers given financial support for conferences, workshops or membership of professional bodies."""
	rows = development.supported_achievements(company, academic_year, department)
	return {"value": len({r["employee"] for r in rows}), "records": refs("Employee", {r["employee"] for r in rows})}


def result(teachers):
	return {"value": len(teachers), "records": refs("Employee", [t.name for t in teachers])}


def refs(doctype, names):
	return [{"doctype": doctype, "name": name} for name in sorted(names)]


# ---- M07-03 substitution ---------------------------------------------------------------------


def can_mark_substituted_attendance(user, course_schedule):
	"""True when a Confirmed Substitution makes `user` the substitute for exactly this Course Schedule."""
	return substitute_attendance.can_mark(user, course_schedule)


@frappe.whitelist(methods=["POST"])
def mark_substituted_attendance(substitution, present=None, absent=None):
	"""The confirmed substitute marks the substituted period (lists of Student names, or JSON); returns the attendance names."""
	return substitute_attendance.mark(substitution, present, absent)


def on_leave(employee, date):
	"""True when the employee has approved leave covering `date` (the check Substitutions use)."""
	return substitutions.on_leave(employee, date)


@frappe.whitelist(methods=["POST"])
def suggest_substitutes(course_schedule):
	"""Free teachers of the absent teacher's department for a period, for the Substitution form."""
	if not (frappe.has_permission("Substitution", "write") and frappe.has_permission("Course Schedule", "read", course_schedule)):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return substitutions.free_faculty(course_schedule)


# ---- M07-04 / M07-05 self-appraisal ----------------------------------------------------------


@frappe.whitelist()
def self_appraisal_preview(employee, appraisal_cycle):
	"""The API computation (points per activity, KRA scores) without saving anything."""
	self_appraisal.check_may_act_for(employee)
	computation = self_appraisal.compute(employee, appraisal_cycle)
	return {
		"rule": computation.rule.name, "total": computation.total, "kras": [dict(k) for k in computation.kras],
		"activities": [dict(r) for r in computation.results],
	}  # fmt: skip


@frappe.whitelist(methods=["POST"])
def create_self_appraisal(employee, appraisal_cycle):
	"""Create or recompute the draft HRMS Appraisal of `employee` for the cycle; returns its name."""
	return self_appraisal.create_or_update(employee, appraisal_cycle).name


@frappe.whitelist(methods=["POST"])
def request_appraisal_review(appraisal):
	"""Send the draft Appraisal to the HOD; returns the Appraisal Review name."""
	return self_appraisal.request_review(appraisal)
