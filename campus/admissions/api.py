"""M04 Admissions service API. Other modules call these, never the controllers (D7)."""

import frappe

from campus.admissions import admit as admission, documents, eligibility
from campus.admissions import seat_matrix as seats
from campus.admissions.aadhaar import copy_aadhaar, reveal_aadhaar  # noqa: F401  (public API; copy_aadhaar is internal, not whitelisted)


@frappe.whitelist()
def evaluate_eligibility(applicant: str):
	"""Apply the Eligibility Rule of the applicant's program: {eligible: bool, reasons: [...]}."""
	frappe.has_permission("Student Applicant", "write", applicant, throw=True)
	return eligibility.evaluate(applicant)


def check_seat_available(program, academic_year, quota, category, applicant=None):
	"""Block admission into a full quota/category row unless the user holds "Admission Override" (then log it).

	Call it in the same transaction that creates and submits the Program Enrollment: it locks the Seat Matrix
	row until commit, so two admissions into the last seat cannot both pass. Allowed without a check when the
	program and year have no Seat Matrix, the matrix has no row for the quota and category, or the quota is
	supernumerary / not counted in the matrix. Returns True when a seat is free, "override" when a full row was
	admitted by an override holder.
	"""
	return seats.check_seat_available(program, academic_year, quota, category, applicant)


def documents_complete(applicant):
	"""True when every mandatory document of the applicant (name) is complete (Verified, or Submitted when no verification is needed)."""
	return documents.documents_complete(applicant)


def pending_documents(applicant):
	"""Document types of the applicant's incomplete mandatory documents (empty when the applicant may be admitted)."""
	return documents.incomplete_mandatory(frappe.get_doc("Student Applicant", applicant))


@frappe.whitelist()
def set_document_status(applicant: str, document_type: str, status: str, remarks: str | None = None, original_retained: int | None = None):
	"""Verifier action on one checklist item; Verified/Rejected need the Admission Verifier role."""
	return documents.set_document_status(applicant, document_type, status, remarks, original_retained)


@frappe.whitelist(methods=["POST"])
def admit(applicant: str):
	"""Admit an Approved, Eligible applicant with complete documents and a free seat (role Admission Officer).

	One transaction: Student (+ Customer), submitted Program Enrollment, register/roll number, fee Sales Invoice,
	applicant status Admitted. Returns {student, program_enrollment, invoice, register_no}.
	"""
	return admission.admit(applicant)
