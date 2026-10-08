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
		self.apply_dean_override(self.workload_findings())
		self.warn_offerings_without_faculty()

	def before_approval_request(self):
		"""Called by the approval engine before a request is created: refuse what submit would refuse anyway."""
		self.check_every_offering_has_faculty()
		blocked = self.workload_findings(warn=False)
		if blocked and not self.dean_override_by:
			self.require_dean_override(blocked)

	def before_submit(self):
		self.check_every_offering_has_faculty()
		self.lock_faculty()  # serialises submits that share a teacher; the sums below then read the latest hours
		self.apply_dean_override(self.workload_findings(warn=False, lock=True))
		super().before_submit()

	def on_submit(self):
		for row in self.allocations:
			instructor = self.instructor_of(row.faculty)
			group = frappe.get_doc("Student Group", row.offering, for_update=True)
			if instructor in {r.instructor for r in group.instructors}:
				continue  # already on the group: not ours to remove on cancel
			group.append("instructors", {"instructor": instructor})
			group.save(ignore_permissions=True)
			frappe.db.set_value("Course Allocation Row", row.name, "added_instructor", instructor)

	def on_cancel(self):
		for row in self.allocations:
			if not row.added_instructor:
				continue
			group = frappe.get_doc("Student Group", row.offering, for_update=True)
			for existing in [r for r in group.instructors if r.instructor == row.added_instructor]:
				group.remove(existing)
			group.save(ignore_permissions=True)

	def lock_faculty(self):
		for employee in sorted({row.faculty for row in self.allocations}):
			frappe.db.get_value("Employee", employee, "name", for_update=True)

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
			self.check_offering_company(row)
			row.total_hours = workload.row_hours(row)
			if not row.total_hours:
				frappe.throw(_("Row {0}: give the weekly Lecture, Tutorial or Practical hours.").format(row.idx))
			self.check_faculty(row)

	def check_offering_company(self, row):
		company = frappe.db.get_value("Program", frappe.db.get_value("Student Group", row.offering, "program"), "oc_company")
		if company != self.company:
			frappe.throw(_("Row {0}: {1} belongs to {2}, not {3}.").format(row.idx, row.offering, company, self.company))

	def check_faculty(self, row):
		status, company = frappe.db.get_value("Employee", row.faculty, ["status", "company"])
		if status != "Active":
			frappe.throw(_("Row {0}: {1} is not an active employee.").format(row.idx, row.faculty))
		if company != self.company:
			frappe.throw(_("Row {0}: {1} belongs to {2}, not {3}.").format(row.idx, row.faculty, company, self.company))
		if not self.instructor_of(row.faculty):
			frappe.throw(_("Row {0}: {1} has no Instructor record, so cannot be set as an instructor.").format(row.idx, row.faculty))

	def instructor_of(self, employee):
		return frappe.db.get_value("Instructor", {"employee": employee}, "name")

	def workload_findings(self, warn=True, lock=False):
		"""Warn for teachers over their cadre maximum (or without a norm to check against); return the messages of
		those past the block margin."""
		on_date = frappe.db.get_value("Academic Term", self.academic_term, "term_start_date")
		others = workload.submitted_hours(self.academic_term, self.company, exclude=self.name, lock=lock)
		blocked = []
		for employee, own in workload.hours_by_faculty(self.allocations).items():
			total = own + others.get(employee, 0)
			cadre = frappe.db.get_value("Employee", employee, "oc_cadre")
			rule = cadre and workload.limits(self.company, cadre, on_date)
			if not rule or not rule[1]:
				self.warn_unchecked(employee, cadre, bool(rule), warn)
				continue
			_minimum, maximum, margin = rule
			message = _("{0} has {1} hours a week against the {2} maximum of {3}.").format(employee, total, cadre, maximum)
			level = workload.classify(total, maximum, margin)
			if level == workload.BLOCK:
				blocked.append(message)
			elif level == workload.WARN and warn:
				frappe.msgprint(message, title=_("Over the Workload Norm"), indicator="orange")
		return blocked

	def warn_unchecked(self, employee, cadre, has_norm, warn):
		"""A teacher with no cadre, or a cadre without a maximum in the Faculty Norm, cannot be checked: say so."""
		if not warn:
			return
		if not cadre:
			message = _("{0} has no cadre, so the workload norm cannot be checked.").format(employee)
		elif not has_norm:
			message = _("No Faculty Norm covers the {0} cadre of {1}, so the workload cannot be checked.").format(cadre, employee)
		else:
			message = _("The Faculty Norm sets no maximum hours for the {0} cadre of {1}, so the workload cannot be checked.").format(cadre, employee)
		frappe.msgprint(message, title=_("Workload Not Checked"), indicator="orange")

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
