"""M06-02 Invigilation Roster: one per Exam Session, the faculty pool and the invigilation duties per hall.

Duties are server-owned: only Generate Roster (campus.examinations.invigilation) writes them.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.examinations.invigilation import roster_name

DUTY_FIELDS = ("exam_date", "slot", "room", "employee")


class InvigilationRoster(Document):
	def autoname(self):
		self.name = roster_name(self.exam_session)

	def validate(self):
		self.company = frappe.db.get_value("Exam Session", self.exam_session, "company")
		if self.invigilators_per_hall < 1:
			frappe.throw(_("At least one invigilator per hall is needed."))
		self.validate_faculty()
		self.guard_duties()

	def validate_faculty(self):
		seen = set()
		for row in self.faculty:
			if row.employee in seen:
				frappe.throw(_("Row {0}: {1} is already in the pool.").format(row.idx, frappe.bold(row.employee)))
			seen.add(row.employee)
			if frappe.db.get_value("Employee", row.employee, "company") != self.company:
				frappe.throw(_("Row {0}: {1} does not belong to {2}.").format(row.idx, frappe.bold(row.employee), self.company))

	def guard_duties(self):
		if self.flags.generating:
			return
		before = self.get_doc_before_save()
		old = [duty_key(d) for d in before.duties] if before else []
		if [duty_key(d) for d in self.duties] != old:
			frappe.throw(_("Duties are set by Generate Roster only."))


def duty_key(duty):
	return tuple(str(duty.get(f) or "") for f in DUTY_FIELDS)
