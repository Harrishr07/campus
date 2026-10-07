"""M05-04 Certificate rules: numbering, the transfer certificate's dues gate and its effect on the Student.

Numbers run per Certificate Type prefix, so per type, company and year: the prefix renders to
e.g. `BON/GEC/2026/`, whose Frappe naming series counter is row-locked, so concurrent issues never repeat
a number. A Transfer Certificate is blocked while the student owes anything to any company of the group
(college or trust): the gate is `has_dues(...).blocking`, the sum of positive balances per company and
head, which a credit held with one company cannot offset. (A submitted No Dues Clearance is the office
sign-off route; the TC itself needs the plain dues to be nil.)
"""

import frappe
from frappe import _
from frappe.utils import fmt_money, getdate, nowdate

from campus.campus_finance.api import has_dues, next_number, validate_number_prefix

DISCONTINUED = "Discontinued"
ACTIVE = "Active"


def next_certificate_number(certificate_type, company):
	prefix = frappe.db.get_value("Certificate Type", certificate_type, "number_prefix")
	return next_number(prefix, 4, company, nowdate())


def validate_prefix(prefix):
	validate_number_prefix(prefix)
	if "{abbr}" not in prefix or "{yyyy}" not in prefix and "{yy}" not in prefix:
		frappe.throw(_("The number prefix must contain {abbr} and {yyyy} (or {yy}) so that numbers run per company and year."))


def lock_student(student):
	"""Serialise transfer certificates of one student (and read the leaving fields with a locking read)."""
	return frappe.db.get_value(
		"Student", student, ["leaving_certificate_number", "date_of_leaving", "oc_academic_status"],
		as_dict=True, for_update=True,
	)  # fmt: skip


def check_transfer_allowed(student):
	"""Throw unless `student` has no earlier TC and owes nothing to any company."""
	current = lock_student(student)
	if current.leaving_certificate_number:
		frappe.throw(
			_("{0} already has transfer certificate {1}.").format(frappe.bold(student), current.leaving_certificate_number)
		)
	dues = has_dues(student)
	if dues.blocking > 0:
		owed = ", ".join(f"{company}: {fmt_money(amount, currency='INR')}" for company, amount in dues.by_company.items() if amount > 0)
		frappe.throw(
			_("A transfer certificate cannot be issued while dues are outstanding ({0}).").format(owed),
			title=_("Dues Outstanding"),
		)


def apply_leaving(request):
	"""Write the TC onto the Student: leaving date, certificate number, reason and academic status."""
	frappe.db.set_value(
		"Student", request.student,
		{
			"date_of_leaving": getdate(request.leaving_date or nowdate()),
			"leaving_certificate_number": request.certificate_number,
			"reason_for_leaving": request.reason_for_leaving,
			"oc_academic_status": DISCONTINUED,
		},
	)  # fmt: skip


def undo_leaving(request):
	"""A cancelled TC takes back what it wrote (only if it is still the student's current TC)."""
	if frappe.db.get_value("Student", request.student, "leaving_certificate_number") == request.certificate_number:
		frappe.db.set_value(
			"Student", request.student,
			{"date_of_leaving": None, "leaving_certificate_number": None, "reason_for_leaving": None, "oc_academic_status": ACTIVE},
		)  # fmt: skip
