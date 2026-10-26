"""M17-06 COE reports and data points (AQAR 2.5.1, 2.6.3; 2.5.2 is campus.examinations.revaluation).

The reports and the data points read the same rows: the latest, ratified version of each Student Result (is_latest,
not pending_ratification: P2-T19) of the company's released Exam Sessions (Published, publish_at passed:
released_sessions) whose term belongs to the academic year.
Appeared / passed follow campus.examinations.coe_report_rules.

- students_appeared: distinct students who sat at least one course in the year's sessions (the denominator of AQAR
  2.5.2, the total row of Evaluation Grievances vs Appeared).
- pass_percentage (AQAR 2.6.3): of the results of the year's final-year sessions that appeared, the percentage that
  passed every course (final_year_passed / final_year_appeared x 100; the Result Analysis total, final year only).
- days_exam_to_result (AQAR 2.5.1): the average, over the year's sessions, of the days from the last exam (the
  session's exam_end, else its last scheduled exam) to the day of publication (publish_at); sessions without either
  are left out.
`programs` (a department's programs, or None) narrows by the result's program; a session counts for
days_exam_to_result when it has a result of one of them.

Reports call these with `lister=frappe.get_list` so the user's permissions apply, after `in_scope(company)`.
"""

import frappe
from frappe.utils import now_datetime

from campus.campus_platform.company_scope import permitted_companies
from campus.examinations import coe_report_rules as rules

RESULT, SESSION = "Student Result", "Exam Session"
PUBLISHED = "Published"


def in_scope(company):
	"""True when the user may report on `company` (no Company User Permission, or one for it)."""
	permitted = permitted_companies(frappe.session.user)
	return bool(company) and (permitted is None or company in permitted)


def refs(doctype, names):
	return [{"doctype": doctype, "name": name} for name in names]


# ---- reading ------------------------------------------------------------------------------------


def released_sessions(company, academic_year=None, lister=frappe.get_all, final_year=False, fields=("name",)):
	"""The company's released Exam Sessions (Published and publish_at passed: an embargoed session counts nowhere),
	optionally only those whose term belongs to `academic_year`. The one session reader of every COE report and
	examination data point (P2-T24 fix 1 ruling), so their figures stay equal."""
	filters = {"company": company, "status": PUBLISHED, "publish_at": ["<=", now_datetime()]}
	if academic_year:
		terms = frappe.get_all("Academic Term", {"academic_year": academic_year}, pluck="name")
		filters["academic_term"] = ["in", terms or [""]]
	if final_year:
		filters["is_final_year"] = 1
	return lister(SESSION, filters=filters, fields=list(fields), order_by="name")


def year_sessions(company, academic_year, lister=frappe.get_all, final_year=False, fields=("name",)):
	"""The company's released Exam Sessions whose term belongs to the academic year."""
	return released_sessions(company, academic_year, lister, final_year, fields)


def published_results(sessions, programs=None, lister=frappe.get_all):
	"""The latest, ratified Student Results of `sessions` (names), optionally of `programs`."""
	filters = {"exam_session": ["in", sessions or [""]], "is_latest": 1, "pending_ratification": 0}
	if programs is not None:
		filters["program"] = ["in", programs or [""]]
	fields = ["name", "student", "student_name", "program", "exam_session", "sgpa", "cgpa", "result"]
	return lister(RESULT, filters=filters, fields=fields, order_by="name")


def outcome_rows(results):
	"""One row per course of `results`: {result, student, program, department, exam_session, course, outcome}."""
	by_name = {r.name: r for r in results}
	courses = frappe.get_all(
		"Student Result Course", {"parenttype": RESULT, "parent": ["in", list(by_name) or [""]]},
		["parent", "course", "result"], order_by="parent, idx",
	)  # fmt: skip
	programs = {r.program for r in results if r.program}
	departments = dict(
		frappe.get_all(
			"Program", {"name": ["in", list(programs) or [""]]}, ["name", "department"], as_list=True
		)
	)
	return [
		{"result": row.parent, "course": row.course, "outcome": row.result, "student": by_name[row.parent].student,
		"program": by_name[row.parent].program, "department": departments.get(by_name[row.parent].program),
		"exam_session": by_name[row.parent].exam_session}
		for row in courses
	]  # fmt: skip


def year_outcomes(
	company, academic_year, programs=None, lister=frappe.get_all, final_year=False, exam_session=None
):
	sessions = [s.name for s in year_sessions(company, academic_year, lister, final_year)]
	if exam_session:
		sessions = [s for s in sessions if s == exam_session]
	return outcome_rows(published_results(sessions, programs, lister))


def session_days(sessions):
	"""[{exam_session, exam_end, publish_at, days}] of `sessions` (dicts with name, exam_end, publish_at); the exam end
	falls back to the session's last scheduled exam."""
	open_ended = [s.name for s in sessions if not s.exam_end]
	last = {}
	for row in frappe.get_all(
		"Exam Schedule",
		{"parenttype": SESSION, "parent": ["in", open_ended or [""]]},
		["parent", "exam_date"],
	):
		if row.exam_date and (row.parent not in last or row.exam_date > last[row.parent]):
			last[row.parent] = row.exam_date
	out = []
	for session in sessions:
		exam_end = session.exam_end or last.get(session.name)
		days = rules.days_to_result(exam_end, session.publish_at)
		out.append(
			frappe._dict(
				exam_session=session.name, exam_end=exam_end, publish_at=session.publish_at, days=days
			)
		)
	return out


def year_session_days(company, academic_year, programs=None, lister=frappe.get_all):
	sessions = year_sessions(company, academic_year, lister, fields=("name", "exam_end", "publish_at"))
	if programs is not None:
		with_results = {r.exam_session for r in published_results([s.name for s in sessions], programs)}
		sessions = [s for s in sessions if s.name in with_results]
	return [row for row in session_days(sessions) if row.days is not None]


# ---- data points --------------------------------------------------------------------------------


def students_appeared(company, academic_year, programs=None):
	rows = year_outcomes(company, academic_year, programs)
	students = sorted({r["student"] for r in rows if r["outcome"] in rules.SAT})
	return {"value": len(students), "records": refs("Student", students)}


def pass_percentage(company, academic_year, programs=None):
	rows = year_outcomes(company, academic_year, programs, final_year=True)
	counts = rules.tally(rows, lambda r: None, lambda r: r["result"]).get(None, {"appeared": 0, "passed": 0})
	appeared = sorted({r["result"] for r in rows if r["outcome"] in rules.SAT})
	return {"value": rules.percent(counts["passed"], counts["appeared"]), "records": refs(RESULT, appeared)}


def days_exam_to_result(company, academic_year, programs=None):
	rows = year_session_days(company, academic_year, programs)
	return {
		"value": rules.average([r.days for r in rows]),
		"records": refs(SESSION, [r.exam_session for r in rows]),
	}
