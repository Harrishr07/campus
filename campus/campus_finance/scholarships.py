"""M05-05 Scholarships: amount and renewal rules, and the disbursement that credits the student's receivable.

A Scholarship Scheme is Government (AQAR 5.1.1) or Institutional (AQAR 5.1.2) and belongs to one company. A
disbursement credits the student's receivable *in that company* by settling the student's open invoices of the
company, oldest first (any remainder stays on account): a Government scholarship is money received from the
awarding body, a Payment Entry (Receive) into the scheme's bank account; an Institutional one is the college
waiving the fee, a Journal Entry debiting the scheme's expense account. The voucher is linked from a row of the
application's disbursement table, so there is no separate disbursement record. Disbursing takes the application's
row lock and the invoices' row locks and re-reads what it needs under them.
"""

import frappe
from frappe import _
from frappe.utils import flt, today

from campus.campus_finance.ledger import student_invoices

GOVERNMENT, INSTITUTIONAL = "Government", "Institutional"
AQAR_CLAUSE = {GOVERNMENT: "5.1.1", INSTITUTIONAL: "5.1.2"}
DISBURSE_ROLES = ("System Manager", "Accounts Manager", "Accounts User")
PAYMENT_ENTRY, JOURNAL_ENTRY = "Payment Entry", "Journal Entry"
FIXED = "Fixed"
CENT = 0.005


# ---- Rules (no database) -------------------------------------------------------------------


def scheme_amount(amount_type, amount, percent, max_amount, base_fee):
	"""The most a scheme sanctions: its fixed amount, or `percent` of `base_fee`, never above a non-zero `max_amount`."""
	value = flt(amount) if amount_type == FIXED else flt(base_fee) * flt(percent) / 100
	if flt(max_amount):
		value = min(value, flt(max_amount))
	return flt(value, 2)


def eligibility_reasons(enabled, required_category, student_category):
	"""Why a student cannot take the scheme (empty when eligible)."""
	reasons = []
	if not enabled:
		reasons.append(_("The scheme is not open."))
	if required_category and student_category != required_category:
		reasons.append(_("The scheme is for student category {0}.").format(required_category))
	return reasons


def renewal_reasons(arrear_count, max_arrears, attendance_pct, min_attendance_pct):
	"""Why a scholarship cannot be renewed (empty when it can). A scheme with no attendance bar ignores attendance."""
	reasons = []
	if arrear_count > max_arrears:
		reasons.append(_("{0} arrear(s) pending; the scheme allows {1}.").format(arrear_count, max_arrears))
	if flt(min_attendance_pct):
		if attendance_pct is None:
			reasons.append(_("No attendance record to check against the required {0}%.").format(flt(min_attendance_pct)))
		elif flt(attendance_pct) < flt(min_attendance_pct):
			reasons.append(_("Attendance {0}% is below the required {1}%.").format(flt(attendance_pct), flt(min_attendance_pct)))
	return reasons


def allocate(amount, invoices):
	"""([(invoice, allocated)], unallocated): `amount` over `invoices` [(name, outstanding)] in the order given."""
	left, parts = flt(amount, 2), []
	for name, outstanding in invoices:
		part = min(left, flt(outstanding, 2))
		if part > 0:
			parts.append((name, part))
			left = flt(left - part, 2)
	return parts, left


# ---- Student facts ---------------------------------------------------------------------------


def renewal_check(student, scheme):
	"""Reasons (empty when allowed) a scholarship of `scheme` cannot be renewed for `student`, from published
	results (arrears) and the latest term's attendance."""
	from campus.examinations.api import arrear_courses
	from campus.student_services.api import latest_attendance

	_term, attendance = latest_attendance(student) if flt(scheme.renewal_min_attendance_pct) else (None, None)
	return renewal_reasons(
		len(arrear_courses(student)), scheme.renewal_max_arrears or 0, attendance, scheme.renewal_min_attendance_pct
	)


# ---- Disbursement --------------------------------------------------------------------------


def disbursed_total(application):
	"""Sum of the application's live disbursement vouchers, read with locking reads (call after locking the application)."""
	rows = frappe.db.sql(
		"select amount, voucher_type, voucher from `tabScholarship Disbursement` where parent = %s for update",
		application,
		as_dict=True,
	)
	live = [r.amount for r in rows if frappe.db.get_value(r.voucher_type, r.voucher, "docstatus", for_update=True) == 1]
	return flt(sum(live), 2)


def open_invoices(student, company):
	"""[(invoice, outstanding)] of the student's open invoices of `company`, oldest first, each read under its row lock."""
	candidates = sorted(
		(i for i in student_invoices(student, outstanding_only=True) if i.company == company and not i.is_return),
		key=lambda i: (i.posting_date, i.name),
	)
	locked = ((i.name, frappe.db.get_value("Sales Invoice", i.name, "outstanding_amount", for_update=True)) for i in candidates)
	return [(name, flt(outstanding, 2)) for name, outstanding in locked if flt(outstanding) > 0]


@frappe.whitelist(methods=["POST"])
def disburse(application, amount, reference_no=None):
	"""Disburse `amount` of a sanctioned application: make the voucher, link it, refresh the totals; returns the row.

	Accounts roles only. The amount may not take the live disbursements above the sanctioned amount."""
	frappe.only_for(DISBURSE_ROLES)
	doc = frappe.get_doc("Scholarship Application", application, for_update=True)
	doc.check_permission("write")
	amount = flt(amount, 2)
	if doc.docstatus != 1:
		frappe.throw(_("{0} is not sanctioned.").format(doc.name))
	if amount <= 0:
		frappe.throw(_("The disbursement amount must be positive."))
	paid = disbursed_total(doc.name)
	if amount > flt(doc.sanctioned_amount - paid, 2) + CENT:
		frappe.throw(_("Only {0} of the sanctioned {1} is left to disburse.").format(flt(doc.sanctioned_amount - paid, 2), doc.sanctioned_amount))
	scheme = frappe.get_doc("Scholarship Scheme", doc.scheme)
	allocations, left = allocate(amount, open_invoices(doc.student, doc.company))
	make = make_payment_entry if scheme.scheme_type == GOVERNMENT else make_journal_entry
	voucher_type, voucher = make(doc, scheme, amount, allocations, left, reference_no)
	row = frappe.get_doc(
		{
			"doctype": "Scholarship Disbursement", "parent": doc.name, "parenttype": doc.doctype, "parentfield": "disbursements",
			"idx": frappe.db.count("Scholarship Disbursement", {"parent": doc.name}) + 1, "disbursed_on": today(), "amount": amount,
			"voucher_type": voucher_type, "voucher": voucher, "reference_no": reference_no,
		}
	).insert(ignore_permissions=True)  # fmt: skip
	refresh_totals(doc.name)
	return row.as_dict()


def refresh_totals(application):
	"""Store the live disbursed total and the status on the application."""
	sanctioned = frappe.db.get_value("Scholarship Application", application, "sanctioned_amount", for_update=True)
	total = disbursed_total(application)
	frappe.db.set_value(
		"Scholarship Application", application,
		{"disbursed_amount": total, "status": "Disbursed" if total >= flt(sanctioned) - CENT else "Sanctioned"},
		update_modified=False,
	)  # fmt: skip


def receivable_of(company):
	account = frappe.db.get_value("Company", company, "default_receivable_account")
	if not account:
		frappe.throw(_("Company {0} has no default receivable account.").format(frappe.bold(company)))
	return account


def make_payment_entry(application, scheme, amount, allocations, left, reference_no):
	"""Receive `amount` from the awarding body against the student's invoices; returns ("Payment Entry", name)."""
	customer = student_customer(application.student)
	payment = frappe.get_doc(
		{
			"doctype": PAYMENT_ENTRY, "payment_type": "Receive", "company": application.company, "posting_date": today(),
			"party_type": "Customer", "party": customer, "paid_from": receivable_of(application.company), "paid_to": scheme.account,
			"paid_amount": amount, "received_amount": amount, "reference_no": reference_no or application.name,
			"reference_date": today(), "remarks": remarks(application, scheme),
			"references": [
				{"reference_doctype": "Sales Invoice", "reference_name": name, "allocated_amount": part} for name, part in allocations
			],
		}
	)  # fmt: skip
	payment.flags.ignore_permissions = True  # every input is server-resolved; the caller was checked in `disburse`
	payment.insert()
	return PAYMENT_ENTRY, payment.submit().name


def make_journal_entry(application, scheme, amount, allocations, left, reference_no):
	"""Waive `amount` of the student's dues: debit the scheme's expense account, credit the receivable; returns ("Journal Entry", name)."""
	customer, receivable = student_customer(application.student), receivable_of(application.company)
	credits = [{"reference_type": "Sales Invoice", "reference_name": name, "credit_in_account_currency": part} for name, part in allocations]
	if left > 0:
		credits.append({"credit_in_account_currency": left})  # no invoice left to settle: credit on account
	entry = frappe.get_doc(
		{
			"doctype": JOURNAL_ENTRY, "voucher_type": "Journal Entry", "company": application.company, "posting_date": today(),
			"cheque_no": reference_no, "cheque_date": today() if reference_no else None, "user_remark": remarks(application, scheme),
			"accounts": [
				{"account": scheme.account, "cost_center": scheme.cost_center or frappe.get_cached_value("Company", application.company, "cost_center"),
				 "debit_in_account_currency": amount},
				*({"account": receivable, "party_type": "Customer", "party": customer, **credit} for credit in credits),
			],
		}
	)  # fmt: skip
	entry.flags.ignore_permissions = True
	entry.insert()
	return JOURNAL_ENTRY, entry.submit().name


def student_customer(student):
	customer = frappe.db.get_value("Student", student, "customer")
	if not customer:
		frappe.throw(_("Student {0} has no Customer, so nothing can be credited.").format(frappe.bold(student)))
	return customer


def remarks(application, scheme):
	return _("Scholarship {0} ({1}) of {2}").format(scheme.name, application.name, application.academic_year)


def refresh_after_voucher_cancel(doc, method=None):
	"""Doc event (Payment Entry / Journal Entry on_cancel): a cancelled disbursement voucher stops counting."""
	for application in frappe.get_all(
		"Scholarship Disbursement", {"voucher_type": doc.doctype, "voucher": doc.name, "parenttype": "Scholarship Application"}, pluck="parent"
	):
		frappe.db.get_value("Scholarship Application", application, "name", for_update=True)
		refresh_totals(application)


# ---- Beneficiaries (reports, IQAC data points) ----------------------------------------------


def scholarship_beneficiaries(company, academic_year=None, scheme_type=None):
	"""Sanctioned applications of `company` (optionally of one year and scheme type), with the AQAR clause of each."""
	filters = {"docstatus": 1, "company": company}
	if academic_year:
		filters["academic_year"] = academic_year
	if scheme_type:
		filters["scheme_type"] = scheme_type
	rows = frappe.get_all(
		"Scholarship Application", filters,
		["name", "student", "student_name", "scheme", "scheme_type", "academic_year", "sanctioned_amount", "disbursed_amount"],
		order_by="scheme_type, student_name", limit=0,
	)  # fmt: skip
	for row in rows:
		row["aqar_clause"] = AQAR_CLAUSE[row.scheme_type]
	return rows
