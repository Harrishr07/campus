"""M03-03 Question-wise marks of a course offering for CO attainment (read by campus.curriculum.attainment through
examinations.api.offering_assessment).

Students: those whose latest, ratified Student Result of a released Exam Session (coe_reports.released_sessions) has a
row for the offering, from their earliest such session (by publication time); a row that is SA (shortage), WD (withdrawn) or Pending was not
assessed and leaves the student out. AB (absent) students stay in; they simply have no ESE script.
- CIA: the Mark Sheet CIA Mark rows of the offering's mark sheet for that session (question, maximum, CO tag, absent).
- ESE: the student's finalised, not void script of the course in that session; each question's mark is the average of
  the two valuation rounds that decide the final mark (valuation_rules.deciding_rounds, the Exam Rule Set's method),
  with the maximum and CO tag of the Answer Script Bundle question pattern. A question with no mark in either deciding
  round was not answered (a choice question) and counts in neither marks nor maximum; a pattern whose maxima add up
  to more than the course's ESE maximum is reported as a choice paper. Moderation, grace and revaluation change the
  final ESE total, not the question marks, so they are not reflected here.
Dummy numbers never leave this module.
"""

import frappe
from frappe.utils import flt

from campus.campus_platform.api import get_rule
from campus.examinations import coe_reports, valuation_rules
from campus.examinations.courses import offering_course, student_limits
from campus.examinations.valuation_access import DUMMY_NUMBER_MAP

NOT_ASSESSED = ("SA", "WD", "Pending")


def offering_assessment(offering):
	"""{exam_sessions, students, cia: [rows], ese: [rows], choice_paper}; a row is {student, question, max_marks, marks,
	course_outcome, absent}."""
	group = frappe.db.get_value("Student Group", offering, ["course", "oc_company"], as_dict=True)
	sessions = [s.name for s in coe_reports.released_sessions(group.oc_company)] if group else []
	cohort = cohort_of(offering, sessions)
	ese, patterns = ese_marks(group.course, cohort) if group else ([], {})
	return frappe._dict(
		exam_sessions=sorted(set(cohort.values())), students=sorted(cohort), cia=cia_marks(offering, cohort), ese=ese,
		choice_paper=is_choice_paper(offering, cohort, patterns),
	)  # fmt: skip


def cohort_of(offering, sessions):
	"""{student: exam session} of the offering's assessed students (see the module docstring)."""
	result, row, session = frappe.qb.DocType("Student Result"), frappe.qb.DocType("Student Result Course"), frappe.qb.DocType("Exam Session")
	rows = (
		frappe.qb.from_(row)
		.join(result).on(result.name == row.parent)
		.join(session).on(session.name == result.exam_session)
		.select(result.student, result.exam_session, row.result)
		.where((row.parenttype == "Student Result") & (row.course_offering == offering))
		.where(result.exam_session.isin(sessions or [""]) & (result.is_latest == 1) & (result.pending_ratification == 0))
		.orderby(session.publish_at)
		.orderby(result.exam_session)
		.run(as_dict=True)
	)  # fmt: skip
	first = {}
	for item in rows:
		first.setdefault(item.student, item)
	return {student: item.exam_session for student, item in first.items() if item.result not in NOT_ASSESSED}


def cia_marks(offering, cohort):
	sheets = dict(
		frappe.get_all(
			"Mark Sheet Entry", {"course_offering": offering, "exam_session": ["in", list(set(cohort.values())) or [""]]},
			["name", "exam_session"], as_list=True,
		)
	)  # fmt: skip
	rows = frappe.get_all(
		"Mark Sheet CIA Mark",
		{"parenttype": "Mark Sheet Entry", "parent": ["in", list(sheets) or [""]], "student": ["in", list(cohort) or [""]]},
		["parent", "student", "component", "question", "max_marks", "marks", "course_outcome", "absent"],
		order_by="idx",
	)
	return [
		{"student": r.student, "question": " ".join(filter(None, (r.component, r.question))), "max_marks": flt(r.max_marks),
		"marks": flt(r.marks), "course_outcome": r.course_outcome, "absent": r.absent}
		for r in rows if cohort[r.student] == sheets[r.parent]
	]  # fmt: skip


def ese_marks(course, cohort):
	scripts = [
		s for s in frappe.get_all(
			DUMMY_NUMBER_MAP,
			{"course": course, "student": ["in", list(cohort) or [""]], "exam_session": ["in", list(set(cohort.values())) or [""]], "void": 0, "finalised": 1},
			["dummy_number", "student", "exam_session"],
		)
		if cohort[s.student] == s.exam_session
	]  # fmt: skip
	entries = frappe.get_all(
		"Valuation Entry", {"dummy_number": ["in", [s.dummy_number for s in scripts] or [""]], "docstatus": 1},
		["name", "dummy_number", "exam_session", "valuation_round", "total", "bundle"],
	)  # fmt: skip
	marks = {}
	for row in frappe.get_all("Valuation Entry Mark", {"parenttype": "Valuation Entry", "parent": ["in", [e.name for e in entries] or [""]]}, ["parent", "question", "marks"]):
		marks.setdefault(row.parent, {})[row.question] = flt(row.marks)
	patterns = bundle_patterns({e.bundle for e in entries})
	rounds = {}
	for entry in entries:
		rounds.setdefault((entry.dummy_number, entry.exam_session), {})[int(entry.valuation_round)] = entry
	methods = valuation_methods([s.student for s in scripts])
	rows = []
	for script in scripts:
		by_round = rounds.get((script.dummy_number, script.exam_session), {})
		if len(by_round) < 2:
			continue
		method = methods[script.student]
		deciding = [by_round[r] for r in valuation_rules.deciding_rounds({r: flt(e.total) for r, e in by_round.items()}, method)]
		for question in patterns.get(deciding[0].bundle, []):
			given = [marks[e.name][question.question] for e in deciding if question.question in marks.get(e.name, {})]
			rows.append({"student": script.student, "question": question.question, "max_marks": flt(question.max_marks),
				"marks": flt(sum(given) / len(given), 2) if given else 0, "course_outcome": question.course_outcome,
				"absent": int(not given)})  # fmt: skip
	return rows, patterns


def valuation_methods(students):
	"""{student: final valuation method} with one Exam Rule Set lookup per regulation."""
	regulations = dict(frappe.get_all("Student", {"name": ["in", students or [""]]}, ["name", "oc_regulation"], as_list=True))
	by_regulation, methods = {}, {}
	for student in students:
		regulation = regulations.get(student)
		if regulation not in by_regulation:
			by_regulation[regulation] = get_rule(student, "Exam Rule Set").final_valuation_method
		methods[student] = by_regulation[regulation]
	return methods


def is_choice_paper(offering, cohort, patterns):
	"""True when a question pattern's maxima add up to more than the course's ESE maximum (students choose questions);
	False when they don't or the maximum is not configured."""
	if not cohort or not patterns:
		return False
	try:
		ese_max = student_limits(next(iter(sorted(cohort))), offering_course(offering))["ese_max"]
	except frappe.ValidationError:
		frappe.clear_messages()
		return False
	return bool(ese_max) and any(sum(flt(q.max_marks) for q in pattern) > flt(ese_max) for pattern in patterns.values())


def bundle_patterns(bundles):
	patterns = {}
	for row in frappe.get_all(
		"Answer Script Bundle Question", {"parenttype": "Answer Script Bundle", "parent": ["in", list(bundles) or [""]]},
		["parent", "question", "max_marks", "course_outcome"], order_by="idx",
	):  # fmt: skip
		patterns.setdefault(row.parent, []).append(row)
	return patterns
