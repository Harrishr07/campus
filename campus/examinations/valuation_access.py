"""M06-04 Who reaches the valuation records.

Dummy Number Map (dummy number -> student) is Exam Confidential only: its DocPerm names no other role and the
hooks below refuse everyone without the role (System Manager and any Custom DocPerm included). It is never
shared and keeps no Version history (track_changes off).

Valuation Allocation and Valuation Entry carry dummy numbers only. Examiners reach their own (examiner = user);
COE, Exam Confidential and System Manager read all, as their role permissions allow.
"""

import frappe
from frappe import _

EXAM_CONFIDENTIAL = "Exam Confidential"  # the role of the QP workflow (P2-T17)
DUMMY_NUMBER_MAP = "Dummy Number Map"
VALUATION_STAFF = {"System Manager", "COE", EXAM_CONFIDENTIAL}


def is_confidential(user=None):
	return EXAM_CONFIDENTIAL in frappe.get_roles(user or frappe.session.user)


def require_confidential():
	if not is_confidential():
		raise frappe.PermissionError(_("Only Exam Confidential may work with dummy numbers."))


# ---- Dummy Number Map ------------------------------------------------------------------------


def map_has_permission(doc, ptype=None, user=None, debug=False):
	return ptype != "share" and is_confidential(user)


def map_query(user=None, doctype=None):
	user = user or frappe.session.user
	return "" if user == "Administrator" or is_confidential(user) else "1=0"


def block_map_share(doc, method=None):
	"""DocShare validate: a share would grant what the hooks refuse."""
	if doc.share_doctype == DUMMY_NUMBER_MAP:
		frappe.throw(_("Dummy numbers are confidential and cannot be shared."))


# ---- Valuation Allocation / Valuation Entry --------------------------------------------------


def examiner_has_permission(doc, ptype=None, user=None, debug=False):
	user = user or frappe.session.user
	if VALUATION_STAFF & set(frappe.get_roles(user)):
		return True  # their role permissions decide
	return bool(user) and examiner_of(doc) == user


def examiner_query(user=None, doctype=None):
	user = user or frappe.session.user
	if user == "Administrator" or VALUATION_STAFF & set(frappe.get_roles(user)):
		return ""
	return f"`tab{doctype}`.examiner = {frappe.db.escape(user)}"


def examiner_of(doc):
	"""A new Valuation Entry is the allocation's examiner's, whatever examiner it was posted with."""
	if doc.doctype == "Valuation Entry" and doc.is_new():
		return doc.allocation and frappe.db.get_value("Valuation Allocation", doc.allocation, "examiner")
	return doc.get("examiner")
