"""M17-03 Approval Request: one document's approval, its approvers per level and its immutable trail."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cstr

TRAIL_FIELDS = ("cycle", "level", "action", "approver", "on_behalf_of", "comment", "timestamp")
APPROVER_FIELDS = ("cycle", "level", "user", "source")


class ApprovalRequest(Document):
	def validate(self):
		before = self.get_doc_before_save()
		if before:
			_append_only(before.actions, self.actions, TRAIL_FIELDS, _("Approval actions"))
			_append_only(before.approvers, self.approvers, APPROVER_FIELDS, _("Approvers"))

	def on_trash(self):
		if not self.flags.reference_deleted:
			frappe.throw(_("Approval requests cannot be deleted; they are the approval record."))


def _append_only(old_rows, new_rows, fields, label):
	"""Rows already saved may not be removed, reordered or changed; new rows may only be appended."""
	if len(new_rows) < len(old_rows):
		frappe.throw(_("{0} cannot be removed.").format(label))
	for old, new in zip(old_rows, new_rows, strict=False):
		if old.name != new.name or any(cstr(old.get(f)) != cstr(new.get(f)) for f in fields):
			frappe.throw(_("{0} are a permanent record and cannot be changed.").format(label))
