"""M04-02 Aadhaar handling (decision D12).

The full number lives in a Password field (`oc_aadhaar`): Frappe keeps it encrypted in `__Auth` and the
document column holds only asterisks. Forms, lists and prints show `oc_aadhaar_masked`
("XXXX-XXXX-1234"). The only ways to read the number are `reveal_aadhaar` (role "Aadhaar Viewer",
always logged in Aadhaar Access Log). Every other route to the cleartext goes through the same gate:
`AadhaarMixin.get_password` (extend_doctype_class) covers Jinja, print formats, notifications and server
scripts, and the `frappe.client.get_password` override covers the REST call. Both require the role, document
read permission and write a log row. Reveals are POST-only because Frappe rolls back GET requests, which
would lose the log row. Error messages never contain the number.

The only sanctioned internal path to the cleartext is `copy_aadhaar(source_doc, target_doc)` (not
whitelisted; P1-T16 Admit uses it to carry the number from applicant to student). It needs no viewer role
but writes an Access Log row with reason "admission copy". Installed app code can still call
`frappe.utils.password.get_decrypted_password` directly, which no hook can gate: review apps accordingly.

Log durability: `log_reveal` marks the request for commit (GET requests are rolled back otherwise) and
registers an `after_rollback` callback that re-inserts and commits the row if the caller rolls back the
whole transaction (e.g. a Server Script reveals then throws). A rollback to a savepoint does not fire that
callback and can still discard the row. Log rows are immutable, and a Student or Student Applicant with
reveal history cannot be deleted (Dynamic Link check): intended audit behaviour.

Residual paths this does not close (operational controls, not code): Error Log tracebacks may capture a
local variable holding a number being saved; Data Import files and Data Export of the form payload carry
what the uploader typed; database and `site_config` encryption_key backups together expose every number.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime
from frappe.utils.password import get_decrypted_password

AADHAAR_DOCTYPES = ("Student Applicant", "Student")
AADHAAR_FIELD = "oc_aadhaar"
MASKED_FIELD = "oc_aadhaar_masked"
VIEWER_ROLE = "Aadhaar Viewer"
LOG_DOCTYPE = "Aadhaar Access Log"
COPY_REASON = "admission copy"

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


class AadhaarMixin:
	"""Gate on `get_password("oc_aadhaar")` for Student and Student Applicant (extend_doctype_class)."""

	def get_password(self, fieldname="password", raise_exception=True):
		if fieldname == AADHAAR_FIELD:
			authorize_reveal(self)
			log_reveal(self.doctype, self.name)
		return super().get_password(fieldname, raise_exception)


def authorize_reveal(doc):
	if VIEWER_ROLE not in frappe.get_roles():
		frappe.throw(
			_("Only users with the role {0} can view Aadhaar numbers.").format(VIEWER_ROLE), frappe.PermissionError
		)
	doc.check_permission("read")  # company User Permissions apply


@frappe.whitelist(methods=["POST"])
def reveal_aadhaar(doctype: str, name: str):
	"""Return the full Aadhaar number to an "Aadhaar Viewer" and log the reveal (POST only, see module doc)."""
	if doctype not in AADHAAR_DOCTYPES:
		frappe.throw(_("Aadhaar is not held on {0}.").format(doctype))
	return frappe.get_doc(doctype, name).get_password(AADHAAR_FIELD, raise_exception=False)


def log_reveal(doctype, name, reason="reveal"):
	row = {
		"doctype": LOG_DOCTYPE, "user": frappe.session.user, "reference_doctype": doctype,
		"reference_name": name, "accessed_on": now_datetime(), "reason": reason,
		"ip_address": getattr(frappe.local, "request_ip", None),
	}  # fmt: skip
	frappe.get_doc(row).insert(ignore_permissions=True)
	frappe.local.flags.commit = True  # a reveal over a safe method must not lose its log row
	frappe.db.after_rollback.add(lambda: persist_after_rollback(row))


def persist_after_rollback(row):
	"""The caller rolled the transaction back: write the log row again, in its own transaction."""
	frappe.get_doc(row).insert(ignore_permissions=True, ignore_links=True)  # the document may be gone too
	frappe.db.commit()


def copy_aadhaar(source_doc, target_doc):
	"""Internal, non-whitelisted: carry the number of `source_doc` onto `target_doc` (saved by the caller).

	Logged as an "admission copy" under the session user. Does nothing when the source has no number.
	"""
	number = get_decrypted_password(source_doc.doctype, source_doc.name, AADHAAR_FIELD, raise_exception=False)
	if number:
		log_reveal(source_doc.doctype, source_doc.name, reason=COPY_REASON)
		target_doc.set(AADHAAR_FIELD, number)


@frappe.whitelist()
def get_password(doctype: str, name: str | int, fieldname: str):
	"""Override of frappe.client.get_password: Aadhaar needs the viewer role and POST, the rest is stock."""
	if fieldname == AADHAAR_FIELD:
		request = getattr(frappe.local, "request", None)
		if request and request.method != "POST":
			frappe.throw(_("Aadhaar can only be revealed with a POST request."), frappe.PermissionError)
		return reveal_aadhaar(doctype, name)
	frappe.only_for("System Manager")
	return frappe.get_lazy_doc(doctype, name).get_password(fieldname)
