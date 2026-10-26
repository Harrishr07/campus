"""M17-02 Position Holder: who holds a Position, for which scope, and between which dates."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from campus.campus_platform.positions import (
	SCOPE_DOCTYPES,
	find_overlapping_holding,
	release_reassigned_holding,
	sync_user_roles,
)


class PositionHolder(Document):
	def validate(self):
		self.keep_role_mark()
		self.set_scope_doctype()
		self.validate_scope_value()
		self.set_user()
		self.validate_dates()
		self.validate_no_overlap()

	def on_update(self):
		before = self.get_doc_before_save()
		if before and before.user != self.user:
			release_reassigned_holding(before.user, self)
		sync_user_roles(self.user)

	def on_trash(self):
		sync_user_roles(self.user, ignore_holding=self.name)

	def keep_role_mark(self):
		"""The mark is set by role sync, not by forms; a stale in-memory copy must not overwrite it."""
		self.role_granted = (
			0 if self.is_new() else frappe.db.get_value(self.doctype, self.name, "role_granted")
		)

	def set_scope_doctype(self):
		scope_type = frappe.db.get_value("Position", self.position, "scope_type")
		if not scope_type:
			frappe.throw(_("Position {0} does not exist").format(self.position))
		self.scope_doctype = SCOPE_DOCTYPES[scope_type]

	def validate_scope_value(self):
		if self.scope_doctype and not self.scope_value:
			frappe.throw(_("Scope is required: choose the {0}").format(_(self.scope_doctype)))
		if self.scope_doctype and not frappe.db.exists(self.scope_doctype, self.scope_value):
			frappe.throw(_("{0} {1} does not exist").format(_(self.scope_doctype), self.scope_value))

	def set_user(self):
		if self.employee:
			self.user = frappe.db.get_value("Employee", self.employee, "user_id")
		if not self.user:
			frappe.throw(_("Choose a user, or an employee who has a user account"))

	def validate_dates(self):
		if self.to_date and getdate(self.to_date) < getdate(self.from_date):
			frappe.throw(_("To Date cannot be before From Date"))

	def validate_no_overlap(self):
		if not frappe.db.get_value("Position", self.position, "single_holder"):
			return
		other = find_overlapping_holding(self)
		if other:
			frappe.throw(
				_("{0} already has a holder ({1}) for these dates and this scope").format(
					self.position, other
				)
			)
