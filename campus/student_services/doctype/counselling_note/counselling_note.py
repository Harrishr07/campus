"""M05-13 Counselling Note (L-09): what a mentor or student counsellor discussed with a student, the agreed actions
with owners and due dates, and a follow-up date. Read rules: campus.student_services.mentoring_access. The author is
the user who wrote it, the mentor the student's mentor at that time; neither changes later. Version history is off
so the note text is never copied into Version rows.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.student_services import mentoring_access
from campus.student_services.mentoring import COUNSELLOR_ROLE, student_department


class CounsellingNote(Document):
	def before_insert(self):
		self.author = frappe.session.user
		mentoring_access.check_may_write_note(self.author, self.student)
		self.mentor = frappe.db.get_value("Student", self.student, "oc_mentor")
		self.company = frappe.db.get_value("Student", self.student, "oc_company")
		self.department = student_department(self.student)

	def validate(self):
		self.check_counsellor()
		self.check_action_owners()

	def check_counsellor(self):
		if self.counsellor and COUNSELLOR_ROLE not in frappe.get_roles(self.counsellor):
			frappe.throw(_("The designated counsellor {0} does not hold the {1} role.").format(self.counsellor, _(COUNSELLOR_ROLE)))

	def check_action_owners(self):
		"""An action owner must be able to read the note, or the reminder would point to a note they cannot open."""
		for row in self.actions:
			if not mentoring_access.reads_note(self, row.action_owner):
				frappe.throw(
					_("Row {0}: {1} cannot read this note, so cannot own its action.").format(row.idx, row.action_owner)
				)
