"""M02-01 Body: a committee or council of a company with its members and their terms. Saving checks the members
in office today against the Body Type's composition rule and refuses a body that breaks it."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today

from campus.academic_governance import composition


class Body(Document):
	def autoname(self):
		abbr = frappe.get_cached_value("Company", self.company, "abbr")
		self.name = f"{self.body_name} - {abbr}"

	def validate(self):
		for member in self.members:
			self.validate_member(member)
		self.validate_no_overlapping_terms()
		if self.enabled:
			self.validate_composition()

	def validate_member(self, member):
		if bool(member.employee) == bool(member.external_member):
			frappe.throw(_("Row {0}: set either an Employee or an External Member").format(member.idx))
		if member.from_date and member.to_date and getdate(member.to_date) < getdate(member.from_date):
			frappe.throw(_("Row {0}: To cannot be before From").format(member.idx))
		if member.employee:
			employee = frappe.db.get_value("Employee", member.employee, ["company", "employee_name", "status"], as_dict=True)
			if employee and employee.company != self.company:
				frappe.throw(_("Row {0}: Employee {1} belongs to {2}, not {3}").format(member.idx, member.employee, employee.company, self.company))
			if employee and employee.status == "Left" and (not member.to_date or getdate(member.to_date) >= getdate(today())):
				frappe.throw(_("Row {0}: Employee {1} has left; end the term before the leaving date").format(member.idx, member.employee))
			member.member_name = employee and employee.employee_name
		else:
			member.member_name = frappe.db.get_value("External Member", member.external_member, "member_name")

	def validate_no_overlapping_terms(self):
		dated = [m for m in self.members if m.from_date]
		for index, member in enumerate(dated):
			person = member.employee or member.external_member
			for other in dated[index + 1 :]:
				if person == (other.employee or other.external_member) and terms_overlap(member, other):
					frappe.throw(_("Rows {0} and {1}: {2} has overlapping terms in this body").format(member.idx, other.idx, member.member_name))

	def validate_composition(self):
		"""Refuse a save that introduces or worsens a breach of the Body Type's rule; warn about a breach it leaves as it was.

		Checked on the later of today and the latest term start, so a body drafted ahead of a new term is judged
		when that term begins. A new body with no members yet is a draft: it only warns."""
		rules = frappe.get_cached_doc("Body Type", self.body_type).composition
		on_date = max([getdate(today()), *(getdate(m.from_date) for m in self.members if m.from_date)])
		shortfalls = composition.composition_shortfalls(rules, self.members, on_date)
		if not shortfalls:
			return
		saved = self.get_doc_before_save()
		if saved:
			worse = composition.is_worse(shortfalls, composition.composition_shortfalls(rules, saved.members, on_date))
		else:
			worse = bool(self.members)
		lines = "".join(f"<li>{frappe.utils.escape_html(s.message)}</li>" for s in shortfalls)
		message = _("{0} does not meet the composition rule of {1}:").format(self.name or self.body_name, self.body_type) + f"<ul>{lines}</ul>"
		if worse:
			frappe.throw(message, title=_("Composition rule not met"))
		frappe.msgprint(message, title=_("Composition rule not met"), indicator="orange")


def terms_overlap(a, b):
	a_end = getdate(a.to_date) if a.to_date else getdate("9999-12-31")
	b_end = getdate(b.to_date) if b.to_date else getdate("9999-12-31")
	return getdate(a.from_date) <= b_end and getdate(b.from_date) <= a_end
