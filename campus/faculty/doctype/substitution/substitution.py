"""M07-03 Substitution: one period of an absent teacher covered by another teacher. Proposed automatically when a
Leave Application is approved (campus.faculty.substitution); a Confirmed one notifies the substitute and lets them
mark attendance for that period only (campus.faculty.substitute_attendance)."""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.faculty import substitution

EVENT = "substitution.assigned"
SAVEPOINT = "substitution_notify"


class Substitution(Document):
	def validate(self):
		self.fill_from_schedule()
		self.check_status()
		self.check_one_live_per_period()
		self.fill_substitute()

	def fill_from_schedule(self):
		if not frappe.db.exists("Course Schedule", self.course_schedule):
			frappe.throw(_("Course Schedule {0} does not exist.").format(self.course_schedule))
		schedule = frappe.db.get_value(
			"Course Schedule", self.course_schedule, ["instructor", "schedule_date", "from_time", "to_time", "student_group", "course", "room"], as_dict=True
		)
		absent = substitution.employee_of_instructor(schedule.instructor)
		if not absent:
			frappe.throw(_("{0} has no teacher with an Employee record to substitute.").format(self.course_schedule))
		self.update({k: v for k, v in schedule.items() if k != "instructor"})
		self.absent_faculty = absent
		employee = frappe.db.get_value("Employee", absent, ["employee_name", "company", "department"], as_dict=True)
		self.absent_faculty_name, self.company = employee.employee_name, employee.company
		self.department = employee.department or frappe.db.get_value("Instructor", schedule.instructor, "department")

	def check_status(self):
		before = self.get_doc_before_save()
		if before and before.status == "Cancelled" and self.status != "Cancelled":
			frappe.throw(_("A cancelled substitution cannot be revived; propose a new one."))
		if self.status == "Confirmed" and not self.substitute:
			frappe.throw(_("Choose a substitute before confirming."))

	def check_one_live_per_period(self):
		if self.status == "Cancelled":
			return
		frappe.db.get_value("Course Schedule", self.course_schedule, "name", for_update=True)  # serialise proposals per period
		others = frappe.db.sql_list(
			"select name from `tabSubstitution` where course_schedule = %s and status in ('Proposed', 'Confirmed') and name != %s for update",
			(self.course_schedule, self.name or ""),
		)  # locking read: a plain select would see this transaction's older snapshot
		if others:
			frappe.throw(_("{0} is already covered by {1}.").format(self.course_schedule, others[0]))

	def fill_substitute(self):
		if not self.substitute:
			self.substitute_name = self.substitute_user = None
			return
		if self.substitute == self.absent_faculty:
			frappe.throw(_("The substitute cannot be the absent teacher."))
		if self.status != "Cancelled":
			self.check_substitute_is_free()
		person = frappe.db.get_value("Employee", self.substitute, ["employee_name", "user_id"], as_dict=True)
		self.substitute_name, self.substitute_user = person.employee_name, person.user_id

	def check_substitute_is_free(self):
		if not substitution.instructor_of(self.substitute):
			frappe.throw(_("{0} is not a teacher (no Instructor record).").format(self.substitute))
		if substitution.on_leave(self.substitute, self.schedule_date):
			frappe.throw(_("{0} is on approved leave on {1}.").format(self.substitute, self.schedule_date))
		if substitution.clashes_with(self.substitute, self, ignore=self.name):
			frappe.throw(_("Clash: {0} already has a class between {1} and {2} on {3}.").format(self.substitute, self.from_time, self.to_time, self.schedule_date))

	def on_update(self):
		before = self.get_doc_before_save()
		if self.status == "Confirmed" and (not before or before.status != "Confirmed" or before.substitute != self.substitute):
			self.notify_substitute()

	def notify_substitute(self, event=EVENT, token=None):
		"""Best effort: a messaging problem must not stop the confirmation."""
		if not frappe.db.exists("Message Template", {"event_key": event, "enabled": 1}):
			return
		from campus.campus_messaging.api import send

		frappe.db.savepoint(SAVEPOINT)
		try:
			send(event, self, [f"Employee:{self.substitute}"], context={"dedupe_token": token or self.substitute})
		except Exception:
			frappe.db.rollback(save_point=SAVEPOINT)
			frappe.log_error(title=f"Substitution notice failed for {self.name}")
