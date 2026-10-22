"""M08-11 Invention Disclosure: an inventor's disclosure of an invention (or design, copyright and the like, by IPR Type) to the college.

Committee approval runs through the approval engine (default policy: the college's Principal): the disclosure submits only
once approved, and only an approved disclosure can be filed as a Patent. Inventors are Employees, Students or external
people; their shares of licence revenue total 100% (equal when none is given)."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, today

from campus.campus_platform.api import ApprovableDocument, is_approved
from campus.research.contributors import validate_contributors
from campus.research.ipr import default_shares


class InventionDisclosure(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		if getdate(self.disclosure_date) > getdate(today()):
			frappe.throw(_("The disclosure date can't be in the future."))
		validate_contributors(self.inventors, "inventor_type", "inventor_name", _("inventor"))
		self.set_shares()

	def before_submit(self):
		super().before_submit()
		if not is_approved(self):
			frappe.throw(
				_("{0} needs committee approval: set up an Approval Policy for Invention Disclosure and request approval.").format(
					self.name
				)
			)

	def approval_excluded_users(self):
		"""Inventors never approve their own disclosure."""
		employees = [row.employee for row in self.inventors if row.employee]
		return frappe.get_all("Employee", {"name": ["in", employees]}, pluck="user_id")

	def set_shares(self):
		if not any(flt(row.share_percent) for row in self.inventors):
			for row, share in zip(self.inventors, default_shares(len(self.inventors)), strict=True):
				row.share_percent = share
		elif abs(sum(flt(row.share_percent) for row in self.inventors) - 100) > 0.005:
			frappe.throw(_("The inventors' revenue shares must total 100%."))
