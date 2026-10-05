"""M04 Admissions service API. Other modules call these, never the controllers (D7)."""

import frappe

from campus.admissions import eligibility
from campus.admissions.aadhaar import copy_aadhaar, reveal_aadhaar  # noqa: F401  (public API; copy_aadhaar is internal, not whitelisted)


@frappe.whitelist()
def evaluate_eligibility(applicant: str):
	"""Apply the Eligibility Rule of the applicant's program: {eligible: bool, reasons: [...]}."""
	frappe.has_permission("Student Applicant", "write", applicant, throw=True)
	return eligibility.evaluate(applicant)
