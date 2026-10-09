"""M06-05 Relative grading cohorts of the Result Run: per course of an Exam Session and Grading Scheme, the
totals of the students who passed it, and the Box-Cox bands they give (campus.examinations.rules).

The cohort is the session's mark-sheet rows of the course whose student is graded by that scheme, after the
course's approved moderation: absent rows, students short of attendance and arrear writers (graded on carried
CIA) are left out, and a pass is judged on the total with the student's Exam Rule Set (first-attempt rule,
no grace). Every student of the course therefore gets the same bands, whichever programme is run first. One
Cohorts object serves a whole bulk run, so each cohort is read once.
"""

import frappe

from campus.examinations import rules
from campus.examinations.arrears import arrear_writers
from campus.examinations.courses import offering_course, rule_limits
from campus.examinations.doctype.mark_moderation.mark_moderation import approved_adjustments
from campus.examinations.result_rules import combined_ese


class Cohorts:
	def __init__(self, exam_session, is_shortage):
		self.exam_session = exam_session
		self.is_shortage = is_shortage  # student -> True when short of attendance in the session's term
		self.moderation = approved_adjustments(exam_session)
		self.totals_by_course = {}
		self.bands_by_course = {}
		self.shortage = {}
		self.rule_sets, self.schemes = {}, {}

	def totals(self, course, scheme):
		"""Totals (0-100) of the students graded by `scheme` (a Grading Scheme name) who passed `course`."""
		key = (course, scheme)
		if key not in self.totals_by_course:
			self.totals_by_course[key] = self.read_totals(course, scheme)
		return self.totals_by_course[key]

	def bands(self, course, scheme, grades):
		key = (course, scheme)
		if key not in self.bands_by_course:
			self.bands_by_course[key] = rules.relative_grade_bands(self.totals(course, scheme), grades)
		return self.bands_by_course[key]

	def read_totals(self, course, scheme):
		sheets = frappe.get_all("Mark Sheet Entry", {"exam_session": self.exam_session, "course": course}, ["name", "course_offering"])
		courses = {s.name: offering_course(s.course_offering) for s in sheets}
		rows = frappe.get_all(
			"Mark Sheet Entry Row",
			{"parenttype": "Mark Sheet Entry", "parent": ["in", list(courses) or [""]], "absent": 0},
			["parent", "student", "cia", "ese"],
		)
		regulations = dict(
			frappe.get_all("Student", {"name": ["in", [r.student for r in rows] or [""]]}, ["name", "oc_regulation"], as_list=True)
		)
		skipped = arrear_writers(self.exam_session, course)
		totals = []
		for row in rows:
			regulation = regulations.get(row.student)
			if row.student in skipped or not regulation or self.scheme_of(regulation) != scheme or self.short(row.student):
				continue
			limits = rule_limits(self.rule_set_of(regulation), courses[row.parent])
			cia, ese = row.cia or 0, combined_ese(row.ese or 0, self.moderation.get(course, 0), 0, limits["ese_max"])
			if rules.pass_status(cia, ese, limits["cia_max"], limits["ese_max"], limits["ese_min_pct"], limits["total_min_pct"]):
				totals.append(rules.total_pct(cia, ese, limits["cia_max"], limits["ese_max"]))
		return sorted(totals)

	def short(self, student):
		if student not in self.shortage:
			self.shortage[student] = self.is_shortage(student)
		return self.shortage[student]

	def scheme_of(self, regulation):
		if regulation not in self.schemes:
			self.schemes[regulation] = frappe.db.get_value("Grading Scheme", {"regulation": regulation})
		return self.schemes[regulation]

	def rule_set_of(self, regulation):
		if regulation not in self.rule_sets:
			self.rule_sets[regulation] = frappe.get_doc("Exam Rule Set", {"regulation": regulation})
		return self.rule_sets[regulation]

