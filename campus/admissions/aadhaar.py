"""M04-02 Aadhaar handling (decision D12).

The full number lives in a Password field (`oc_aadhaar`): Frappe keeps it encrypted in `__Auth` and the
document column holds only asterisks. Forms, lists and prints show `oc_aadhaar_masked`
("XXXX-XXXX-1234"). The only ways to read the number are `reveal_aadhaar` (role "Aadhaar Viewer",
always logged in Aadhaar Access Log) and `frappe.client.get_password`, which is routed through the same
checks here. Error messages never contain the number.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime

AADHAAR_DOCTYPES = ("Student Applicant", "Student")
AADHAAR_FIELD = "oc_aadhaar"
MASKED_FIELD = "oc_aadhaar_masked"
VIEWER_ROLE = "Aadhaar Viewer"
LOG_DOCTYPE = "Aadhaar Access Log"

_D = (
	(0, 1, 2, 3, 4, 5, 6, 7, 8, 9), (1, 2, 3, 4, 0, 6, 7, 8, 9, 5), (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
	(3, 4, 0, 1, 2, 8, 9, 5, 6, 7), (4, 0, 1, 2, 3, 9, 5, 6, 7, 8), (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
	(6, 5, 9, 8, 7, 1, 0, 4, 3, 2), (7, 6, 5, 9, 8, 2, 1, 0, 4, 3), (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
	(9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)  # fmt: skip
_P = (
	(0, 1, 2, 3, 4, 5, 6, 7, 8, 9), (1, 5, 7, 6, 2, 8, 3, 0, 9, 4), (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
	(8, 9, 1, 6, 0, 4, 3, 5, 2, 7), (9, 4, 5, 3, 1, 2, 6, 8, 7, 0), (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
	(2, 7, 9, 3, 8, 0, 6, 4, 1, 5), (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)  # fmt: skip


def verhoeff_valid(digits: str) -> bool:
	"""True when the Verhoeff checksum of `digits` (check digit included) is zero."""
	c = 0
	for i, ch in enumerate(reversed(digits)):
		c = _D[c][_P[i % 8][int(ch)]]
	return c == 0


def normalize(number: str) -> str:
	return "".join(ch for ch in str(number) if ch not in " -")


def is_valid_aadhaar(number: str) -> bool:
	digits = normalize(number)
	return len(digits) == 12 and digits.isdigit() and digits[0] not in "01" and verhoeff_valid(digits)


def mask(number: str) -> str:
	return "XXXX-XXXX-" + normalize(number)[-4:]


def validate_aadhaar(doc, method=None):
	"""doc_event (validate) on Student Applicant and Student: check, normalise and mask a new number."""
	number = doc.get(AADHAAR_FIELD)
	if not number:
		doc.set(MASKED_FIELD, None)
	elif doc.is_dummy_password(number):  # unchanged: the stored value is a run of asterisks
		before = doc.get_doc_before_save()
		doc.set(MASKED_FIELD, before.get(MASKED_FIELD) if before else None)
	else:
		if not is_valid_aadhaar(number):
			frappe.throw(_("Aadhaar number is not valid. Enter 12 digits, not starting with 0 or 1."))
		doc.set(AADHAAR_FIELD, normalize(number))
		doc.set(MASKED_FIELD, mask(number))


@frappe.whitelist()
def reveal_aadhaar(doctype: str, name: str):
	"""Return the full Aadhaar number to an "Aadhaar Viewer" and log the reveal."""
	if doctype not in AADHAAR_DOCTYPES:
		frappe.throw(_("Aadhaar is not held on {0}.").format(doctype))
	if VIEWER_ROLE not in frappe.get_roles():
		frappe.throw(_("Only users with the role {0} can view Aadhaar numbers.").format(VIEWER_ROLE), frappe.PermissionError)
	frappe.has_permission(doctype, "read", name, throw=True)
	number = frappe.get_doc(doctype, name).get_password(AADHAAR_FIELD, raise_exception=False)
	log_reveal(doctype, name)
	return number


def log_reveal(doctype, name):
	frappe.get_doc(
		{
			"doctype": LOG_DOCTYPE, "user": frappe.session.user, "reference_doctype": doctype,
			"reference_name": name, "accessed_on": now_datetime(),
		}
	).insert(ignore_permissions=True)  # fmt: skip


@frappe.whitelist()
def get_password(doctype: str, name: str, fieldname: str):
	"""Override of frappe.client.get_password: Aadhaar goes through reveal_aadhaar, the rest is unchanged."""
	if fieldname == AADHAAR_FIELD:
		return reveal_aadhaar(doctype, name)
	frappe.only_for("System Manager")
	return frappe.get_lazy_doc(doctype, name).get_password(fieldname)
