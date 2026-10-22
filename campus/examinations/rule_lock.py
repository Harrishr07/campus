"""M06-05 (D6) Rule records (Exam Rule Set, Grading Scheme, Classification Rule, CIA Component Template, Progression
Rule) are immutable once their regulation is Effective: they can be created for it but not edited, moved or deleted.
A change is made on a new regulation version (Regulation "Amend as New Version") with its own rule records."""

import frappe
from frappe import _

LOCKED = ("Effective", "Retired")


def is_locked(regulation):
	return bool(regulation) and frappe.db.get_value("Regulation", regulation, "status") in LOCKED


def validate_rule_lock(doc):
	"""Refuse an edit of a saved rule record whose regulation (before or after the edit) is locked."""
	before = None if doc.is_new() else doc.get_doc_before_save()
	if before and (is_locked(before.regulation) or is_locked(doc.regulation)):
		frappe.throw(
			_(
				"{0} {1} belongs to an Effective regulation and cannot be edited. Amend the regulation as a new version."
			).format(_(doc.doctype), frappe.bold(doc.name)),
			title=_("Rule Locked"),
		)


def validate_rule_delete(doc):
	if is_locked(doc.regulation):
		frappe.throw(
			_("{0} {1} belongs to an Effective regulation and cannot be deleted.").format(
				_(doc.doctype), frappe.bold(doc.name)
			),
			title=_("Rule Locked"),
		)
