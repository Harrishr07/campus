"""M06-05 Relative grading cohorts of the Result Run: per course of an Exam Session and Grading Scheme, the
totals of the students who passed it, and the Box-Cox bands they give (campus.examinations.rules).

The cohort is the session's mark-sheet rows of the course whose student is graded by that scheme, after the
course's approved moderation: absent rows, students short of attendance and arrear writers (graded on carried
CIA) are left out, and a pass is judged on the total with the student's Exam Rule Set (first-attempt rule,
no grace). Every student of the course therefore gets the same bands, whichever programme is run first. One
Cohorts object serves a whole bulk run, so each cohort is read once.

Before publication each run records the decision it graded on in Exam Session frozen_bands (the bands of a
relative course; no entry for one graded absolutely), under the session row lock the Result Run holds. Publication
freezes that record (campus.examinations.publication): `relative_bands` then returns the stored bands, or None
(absolute) for a course that was not graded relatively, so a re-run after publication never moves another
student's grade.
"""

import json

import frappe

from campus.examinations import rules
from campus.examinations.arrears import arrear_writers
from campus.examinations.courses import offering_course, rule_limits
from campus.examinations.doctype.mark_moderation.mark_moderation import approved_adjustments
from campus.examinations.result_rules import combined_ese


class Cohorts:
	def __init__(self, exam_session, is_shortage, frozen=None, record=False):
		self.exam_session = exam_session
		self.frozen = frozen  # {band_key: bands} of a published session, else None
		self.record = record  # store the live decisions on the session (unpublished)
		self.recorded = set()
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

	def relative_bands(self, course, scheme, course_type, method_row, grades):
		"""The relative bands `course` is graded on under `scheme`, or None when it is graded absolutely."""
		if self.frozen is not None:
			return self.frozen.get(band_key(course, scheme))
		totals = self.totals(course, scheme)
		method = rules.grading_method(course_type, method_row.method, len(totals), method_row.min_cohort, totals)
		bands = self.bands(course, scheme, grades) if method == rules.RELATIVE else None
		self.remember(band_key(course, scheme), bands)
		return bands

	def remember(self, key, bands):
		"""Record the run's decision for `key` on the session (once per run and key)."""
		if not self.record or key in self.recorded:
			return
		self.recorded.add(key)
		stored = json.loads(frappe.db.get_value("Exam Session", self.exam_session, "frozen_bands") or "{}")
		if bands:
			stored[key] = bands
		else:
			stored.pop(key, None)
		frappe.db.set_value("Exam Session", self.exam_session, "frozen_bands", json.dumps(stored, sort_keys=True), update_modified=False)

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



def band_key(course, scheme):
	"""Key of a course's relative bands under a Grading Scheme in Exam Session frozen_bands."""
	return f"{course}::{scheme}"
