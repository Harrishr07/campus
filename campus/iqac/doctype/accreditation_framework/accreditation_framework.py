"""M01-01 Accreditation Framework: a versioned accreditation scheme (e.g. NAAC AQAR RAF 2017) whose nodes carry metric formulas.

Draft -> Published -> Retired. Once published the framework and its nodes are immutable (the only edit left is
Published -> Retired); a new version is made with Clone to new version (campus.iqac.api.clone_framework).
"""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.iqac.framework import status_of


class AccreditationFramework(Document):
	def validate(self):
		self.status = self.status or "Draft"
		self.validate_dates()
		if not self.is_new():
			self.validate_lock()
		if self.status == "Published" and not frappe.db.exists("Framework Node", {"framework": self.name}):
			frappe.throw(_("A framework needs at least one node before it is published."))

	def validate_dates(self):
		if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
			frappe.throw(_("Valid To cannot be before Valid From."))

	def validate_lock(self):
		before = status_of(self.name)
		if before == "Draft":
			return
		retiring = before == "Published" and self.status == "Retired"
		changed = [f.fieldname for f in self.meta.fields if f.fieldname != "status" and self.has_value_changed(f.fieldname)]
		if not retiring or changed:
			frappe.throw(
				_("{0} is {1} and cannot be changed. Clone it to a new version to make changes.").format(
					frappe.bold(self.name), before
				)
			)

	def on_trash(self):
		if status_of(self.name) != "Draft":
			frappe.throw(_("Only a Draft framework can be deleted."))
