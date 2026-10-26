"""M05-13 Parent Interaction (L-09): a contact with one of the student's own guardians (Student Guardian), its mode
and outcome, and a follow-up with an owner and due date. Read rules: campus.student_services.mentoring_access.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.student_services import mentoring_access
from campus.student_services.mentoring import student_department

FIXED_FIELDS = ("student", "recorded_by", "company", "department")


class ParentInteraction(Document):
	def before_insert(self):
		self.recorded_by = frappe.session.user
		mentoring_access.check_may_record_interaction(self.recorded_by, self.student)
		self.company = frappe.db.get_value("Student", self.student, "oc_company")
		self.department = student_department(self.student)

	def validate(self):
		self.keep_fixed_fields()
		self.check_guardian()
		self.check_follow_up()

	def keep_fixed_fields(self):
		if before := self.get_doc_before_save():
			for field in FIXED_FIELDS:
				self.set(field, before.get(field))

	def check_guardian(self):
		linked = {"parent": self.student, "parenttype": "Student", "guardian": self.guardian}
		if not frappe.db.exists("Student Guardian", linked):
			frappe.throw(
				_("Guardian {0} is not a guardian of student {1}.").format(self.guardian, self.student)
			)

	def check_follow_up(self):
		if bool(self.follow_up_owner) != bool(self.follow_up_due):
			frappe.throw(_("Set both the follow-up owner and the due date, or neither."))
		if self.follow_up_owner and not mentoring_access.reads_interaction(self, self.follow_up_owner):
			frappe.throw(
				_("The follow-up owner {0} cannot read this interaction.").format(self.follow_up_owner)
			)
