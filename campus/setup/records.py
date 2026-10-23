"""PR-02 Idempotent record helpers for the pilot setup kit: find by natural key, create when missing, update when changed."""

from collections import Counter

import frappe
from frappe.utils import cstr, flt


class Outcome:
	"""What a run did: records created and updated per DocType, plus notes for anything left as it was on purpose."""

	def __init__(self):
		self.created = Counter()
		self.updated = Counter()
		self.notes = []

	def total_changes(self):
		return sum(self.created.values()) + sum(self.updated.values())

	def as_dict(self):
		return {"created": dict(self.created), "updated": dict(self.updated), "notes": self.notes}


def same_value(stored, wanted):
	if isinstance(wanted, (int, float)) and not isinstance(wanted, bool):
		return flt(stored) == flt(wanted)
	return cstr(stored or "") == cstr(wanted or "")


def upsert(outcome, doctype, key, values=None):
	"""Name of the `doctype` record matching `key`; created from `key` + `values` when missing, and when it exists
	the scalar `values` that differ are saved. Locked records (submitted, Effective) must not be passed here."""
	values = values or {}
	name = frappe.db.exists(doctype, key)
	if not name:
		doc = frappe.get_doc({"doctype": doctype, **key, **values}).insert(ignore_permissions=True)
		outcome.created[doctype] += 1
		return doc.name
	stored = frappe.db.get_value(doctype, name, list(values), as_dict=True) if values else {}
	changed = {field: value for field, value in values.items() if not same_value(stored.get(field), value)}
	if changed:
		doc = frappe.get_doc(doctype, name)
		doc.update(changed)
		doc.save(ignore_permissions=True)
		outcome.updated[doctype] += 1
	return name
