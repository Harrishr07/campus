"""M09-02 Challan and receipt numbers: a challan number on every student invoice, a receipt number on every fee receipt.

Both come from the college's Challan Format. A college without one gets neither (and no bank import).
"""

import frappe

from campus.campus_finance import numbering


def challan_format(company):
	return frappe.db.get_value("Challan Format", company, "*", as_dict=True) if company else None


def assign_challan_no(doc, method=None):
	"""Give a student's invoice its challan number on submit."""
	if not doc.get("student") or doc.get("oc_challan_no"):
		return
	fmt = challan_format(doc.company)
	if fmt:
		doc.oc_challan_no = numbering.next_number(fmt.challan_prefix, fmt.challan_digits, doc.company, doc.posting_date)


def set_payment_student(doc, method=None):
	"""Receipts name the student: from the invoices the payment settles, else the customer's student."""
	if doc.payment_type != "Receive" or doc.party_type != "Customer":
		return
	invoices = [r.reference_name for r in doc.references if r.reference_doctype == "Sales Invoice"]
	student = invoices and frappe.db.get_value("Sales Invoice", {"name": ("in", invoices), "student": ("is", "set")}, "student")
	doc.oc_student = student or frappe.db.get_value("Student", {"customer": doc.party}, "name") or doc.oc_student


def assign_receipt_no(doc, method=None):
	"""Number a student's fee receipt on submit and use the college's letter head from the Challan Format."""
	if not doc.oc_student or doc.oc_receipt_no:
		return
	fmt = challan_format(doc.company)
	if fmt:
		doc.oc_receipt_no = numbering.next_number(fmt.receipt_prefix, fmt.receipt_digits, doc.company, doc.posting_date)
		doc.letter_head = fmt.letter_head or doc.letter_head


def challan_details(doc):
	"""Template data for the bank challan and fee receipt print formats."""
	fmt = challan_format(doc.company) or frappe._dict()
	student = doc.get("student") or doc.get("oc_student")
	fmt.student = student and frappe.db.get_value("Student", student, ["name", "student_name"], as_dict=True)
	fmt.company_name = doc.company
	return fmt
