"""M06-02 Hall Ticket: one student's admission to the exams of one Exam Session, or the record that it is withheld.

Made and refreshed only by the bulk generation (campus.examinations.hall_tickets). An Issued ticket lists the
eligible courses with their dates and carries a verifiable QR; a Withheld one lists why and has no valid QR.
"""

import frappe
from frappe import _
from frappe.model.document import Document


def ticket_name(exam_session, student):
	return f"HT-{exam_session}-{student}"


class HallTicket(Document):
	def autoname(self):
		self.name = ticket_name(self.exam_session, self.student)

	def verification_details(self):
		"""[(label, value)] for the public verification page: never the student id."""
		confirmed = frappe.db.get_value("Exam Registration", self.exam_registration, "confirmed")
		return [
			(_("Exam session"), self.exam_session),
			(_("Academic term"), self.academic_term),
			(_("Registration"), _("Confirmed") if confirmed else _("Not confirmed")),
			(_("Hall ticket"), _(self.status)),
		]
