"""M07-02 Course Allocation: the HOD-approved allocation of a department's course offerings to faculty for a term.

Rows give offering, faculty and weekly Lecture / Tutorial / Practical hours. Every offering of the department's
programs in the term needs at least one faculty before submit (AC2). A teacher over the cadre maximum is warned;
over maximum + the Faculty Norm's block margin needs a Dean Academics override (AC1). Submit adds the faculty
as instructors of the offerings (Student Group); cancel takes them off again. Approval goes through the engine.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.campus_platform.api import ApprovableDocument, resolve_position
from campus.faculty import workload

DEAN = "DEAN-ACADEMICS"


class CourseAllocation(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		self.check_term_and_department()
		self.check_rows()
		self.check_workload()
		self.warn_offerings_without_faculty()

	def before_submit(self):
		self.check_every_offering_has_faculty()
		super().before_submit()

	def on_submit(self):
		for offering, instructors in self.instructors_by_offering().items():
			group = frappe.get_doc("Student Group", offering, for_update=True)
			present = {row.instructor for row in group.instructors}
			for instructor in instructors - present:
				group.append("instructors", {"instructor": instructor})
			group.save(ignore_permissions=True)

	def on_cancel(self):
		for offering, instructors in self.instructors_by_offering().items():
			group = frappe.get_doc("Student Group", offering, for_update=True)
			for row in [r for r in group.instructors if r.instructor in instructors]:
				group.remove(row)
			group.save(ignore_permissions=True)

	def check_term_and_department(self):
		duplicate = frappe.db.exists(
			"Course Allocation",
			{"academic_term": self.academic_term, "department": self.department, "docstatus": ["<", 2], "name": ["!=", self.name]},
		)
		if duplicate:
			frappe.throw(_("{0} already allocates {1} for {2}.").format(duplicate, self.department, self.academic_term))

	def check_rows(self):
		offerings = set(workload.term_offerings(self.department, self.academic_term))
		seen = set()
		for row in self.allocations:
			if row.offering not in offerings:
				frappe.throw(_("Row {0}: {1} is not a course offering of {2} for {3}.").format(row.idx, row.offering, self.department, self.academic_term))
			if (row.offering, row.faculty) in seen:
				frappe.throw(_("Row {0}: {1} is already allocated to {2}.").format(row.idx, row.faculty, row.offering))
			seen.add((row.offering, row.faculty))
			row.total_hours = workload.row_hours(row)
			if not row.total_hours:
				frappe.throw(_("Row {0}: give the weekly Lecture, Tutorial or Practical hours.").format(row.idx))
			self.check_faculty(row)

	def check_faculty(self, row):
		status = frappe.db.get_value("Employee", row.faculty, "status")
		if status != "Active":
			frappe.throw(_("Row {0}: {1} is not an active employee.").format(row.idx, row.faculty))
		if not self.instructor_of(row.faculty):
			frappe.throw(_("Row {0}: {1} has no Instructor record, so cannot be set as an instructor.").format(row.idx, row.faculty))

	def instructor_of(self, employee):
		return frappe.db.get_value("Instructor", {"employee": employee}, "name")

	def instructors_by_offering(self):
		result = {}
		for row in self.allocations:
			result.setdefault(row.offering, set()).add(self.instructor_of(row.faculty))
		return result

	def check_workload(self):
		"""Warn for teachers over their cadre maximum; collect those past the block margin."""
		on_date = frappe.db.get_value("Academic Term", self.academic_term, "term_start_date")
		others = workload.submitted_hours(self.academic_term, exclude=self.name)
		blocked = []
		for employee, own in workload.hours_by_faculty(self.allocations).items():
			total = own + others.get(employee, 0)
			cadre = frappe.db.get_value("Employee", employee, "oc_cadre")
			rule = cadre and workload.limits(self.company, cadre, on_date)
			if not rule:
				continue
			_minimum, maximum, margin = rule
			message = _("{0} has {1} hours a week against the {2} maximum of {3}.").format(employee, total, _(cadre), maximum)
			level = workload.classify(total, maximum, margin)
			if level == workload.BLOCK:
				blocked.append(message)
			elif level == workload.WARN:
				frappe.msgprint(message, title=_("Over the Workload Norm"), indicator="orange")
		self.apply_dean_override(blocked)

	def apply_dean_override(self, blocked):
		before = self.get_doc_before_save()
		if not blocked:
			self.dean_override_reason = self.dean_override_by = None
		elif before and before.dean_override_by and self.same_override(before):
			self.dean_override_by = before.dean_override_by  # never set from the client
		else:
			self.require_dean_override(blocked)

	def same_override(self, before):
		"""The Dean's override still stands while the reason and the allocation are as the Dean saved them."""
		return before.dean_override_reason == self.dean_override_reason and self.signature() == before.signature()

	def signature(self):
		return sorted((r.offering, r.faculty, r.lecture_hours or 0, r.tutorial_hours or 0, r.practical_hours or 0) for r in self.allocations)

	def require_dean_override(self, blocked):
		if not self.dean_override_reason:
			frappe.throw(
				_("{0}<br>The Dean Academics must enter an override reason to allocate beyond the maximum plus the block margin.").format("<br>".join(blocked)),
				title=_("Workload Over the Limit"),
			)
		if frappe.session.user not in resolve_position(DEAN, self.company):
			frappe.throw(_("Only the Dean Academics of {0} can override the workload limit.").format(self.company), frappe.PermissionError)
		self.dean_override_by = frappe.session.user

	def offerings_without_faculty(self):
		covered = {row.offering for row in self.allocations}
		return [o for o in workload.term_offerings(self.department, self.academic_term) if o not in covered]

	def warn_offerings_without_faculty(self):
		"""Tell the drafter early: an approval that is later approved cannot submit while offerings lack faculty."""
		missing = self.offerings_without_faculty()
		if missing:
			frappe.msgprint(_("{0} offering(s) still have no faculty: {1}").format(len(missing), ", ".join(missing)), indicator="orange")

	def check_every_offering_has_faculty(self):
		missing = self.offerings_without_faculty()
		if missing:
			frappe.throw(
				_("Every offering needs at least one faculty. Missing: {0}").format(", ".join(missing)),
				title=_("Offerings Without Faculty"),
			)
