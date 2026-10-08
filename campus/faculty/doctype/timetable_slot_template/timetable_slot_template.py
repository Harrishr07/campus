"""M07-03 Timetable Slot Template: the teaching days and the numbered periods (clock times, breaks) of a college's week,
plus the two scheduling parameters the solver reads: practical block length and the soft daily maximum for a teacher."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, to_timedelta


class TimetableSlotTemplate(Document):
	def validate(self):
		self.check_days()
		self.check_periods()
		if cint(self.lab_block_periods) < 1:
			frappe.throw(_("A practical block is at least 1 period."))
		if cint(self.max_faculty_periods_per_day) < 0:
			frappe.throw(_("Max Periods per Teacher per Day cannot be negative."))

	def check_days(self):
		days = [d.day for d in self.days]
		if not days:
			frappe.throw(_("Give at least one teaching day."))
		if len(days) != len(set(days)):
			frappe.throw(_("A day is listed more than once."))

	def check_periods(self):
		numbers = [p.period for p in self.periods]
		if len(numbers) != len(set(numbers)):
			frappe.throw(_("A period number is listed more than once."))
		if numbers != sorted(numbers):
			frappe.throw(_("Periods must be listed in time order, with ascending period numbers."))
		if all(p.is_break for p in self.periods):
			frappe.throw(_("The template needs at least one teaching period."))
		previous = None
		for p in self.periods:
			if to_timedelta(p.from_time) >= to_timedelta(p.to_time):
				frappe.throw(_("Period {0}: From must be before To.").format(p.period))
			if previous and to_timedelta(p.from_time) < to_timedelta(previous.to_time):
				frappe.throw(_("Period {0} overlaps period {1}.").format(p.period, previous.period))
			previous = p
