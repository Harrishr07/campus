"""M05-03 Rejoin Application: a student returns from an approved Break of Study.

The student moves to the regulation in force for the programme in the rejoin year (the latest Effective one
whose effective-from year is not after it, campus_platform resolve_regulation), through the P1-T05 regulation
history. The bridge courses listed here are added, kind Bridge, to the student's next exam registrations until
sat (student_services.api.pending_bridge_courses). One rejoin per break. Approval runs through the approval
engine (seeded policy: HOD recommendation, then Principal approval); final approval submits it, which changes
the regulation (when it differs) and sets the academic status back to Active. A rejoin is not cancelled: the
Dean Academics corrects a regulation with Change Regulation.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.permissions import has_user_permission
from frappe.utils import getdate

from campus.campus_platform.api import ApprovableDocument, apply_regulation_change, get_regulation, resolve_regulation
from campus.student_services import student_records

DOCTYPE, BREAK = "Rejoin Application", "Break of Study"


class RejoinApplication(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		study_break = frappe.get_doc(BREAK, self.break_of_study)
		if study_break.docstatus != 1:
			frappe.throw(_("Break of Study {0} is not approved.").format(frappe.bold(study_break.name)))
		if getdate(self.rejoin_date) < getdate(study_break.from_date):
			frappe.throw(_("The rejoin date cannot be before the break starts ({0}).").format(frappe.format(study_break.from_date, "Date")))
		self.set_context(study_break)
		if self.other_rejoins():
			frappe.throw(_("Break of Study {0} already has a rejoin.").format(frappe.bold(self.break_of_study)))
		self.check_bridge_courses()

	def before_submit(self):
		super().before_submit()
		frappe.db.get_value(BREAK, self.break_of_study, "name", for_update=True)  # one rejoin submit per break
		if self.other_rejoins(lock=True):
			frappe.throw(_("Break of Study {0} already has a rejoin.").format(frappe.bold(self.break_of_study)))

	def on_submit(self):
		if self.to_regulation != self.from_regulation:
			apply_regulation_change(
				self.student,
				self.to_regulation,
				_("Rejoin {0} after break of study {1}").format(self.name, self.break_of_study),
				", ".join(row.course for row in self.bridge_courses) or None,
			)
		frappe.db.set_value("Student", self.student, "oc_academic_status", "Active")

	def before_cancel(self):
		frappe.throw(_("A rejoin cannot be cancelled; the Dean Academics corrects the regulation with Change Regulation."))

	def set_context(self, study_break):
		student = frappe.get_doc("Student", study_break.student)
		if not has_user_permission(student):  # Company User Permissions
			frappe.throw(_("You are not permitted to act for {0}.").format(frappe.bold(student.name)), frappe.PermissionError)
		self.student, self.student_name = student.name, student.student_name
		self.company, self.program, self.department = study_break.company, study_break.program, study_break.department
		if self.docstatus != 0:
			return  # the approved values stand
		self.from_regulation = get_regulation(self.student)
		self.to_regulation = resolve_regulation(self.company, self.program, self.academic_year)
		if not self.to_regulation:
			frappe.throw(
				_("No Effective regulation covers {0} in {1}.").format(frappe.bold(self.program), frappe.bold(self.academic_year))
			)

	def check_bridge_courses(self):
		seen = set()
		for row in self.bridge_courses:
			if row.course in seen:
				frappe.throw(_("Row {0}: {1} is listed twice.").format(row.idx, frappe.bold(row.course)))
			seen.add(row.course)

	def other_rejoins(self, lock=False):
		"""Other live (draft or submitted) rejoins of the break (a locking read of submitted ones when `lock`)."""
		other = frappe.qb.DocType(DOCTYPE)
		query = (
			frappe.qb.from_(other)
			.select(other.name)
			.where((other.break_of_study == self.break_of_study) & (other.name != (self.name or "")))
		)
		query = query.where(other.docstatus == 1).for_update() if lock else query.where(other.docstatus < 2)
		return query.run()
