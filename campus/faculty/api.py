"""M07-01 Faculty service API. Other modules call these, never the controllers (D7).

The data point functions return {"value", "records"} for the IQAC registry (campus/iqac/datapoints.py); all take
(company, academic_year, department=None).
"""

from frappe.utils import flt

from campus.faculty import staffing
from campus.faculty.norms import cadre_rule, norm_in_force  # noqa: F401  (public API)


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


def result(teachers):
	return {"value": len(teachers), "records": refs("Employee", [t.name for t in teachers])}


def refs(doctype, names):
	return [{"doctype": doctype, "name": name} for name in sorted(names)]
