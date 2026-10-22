"""M08-10 Consultancy: GST invoicing of a Consultancy Project and the revenue share of its paid invoices.

Invoicing. A project is invoiced once its agreement is signed (Agreed, until Completed) by an ERPNext Sales Invoice for the
client with the project's service Item, tagged `oc_consultancy_project`. The draft takes its place of supply and GST
template from india_compliance (company GSTIN against the client's GSTIN or address state: CGST + SGST within the state,
IGST across states); Accounts reviews and submits it. A consultancy invoice is submitted only for the project's client
and college, while the project is Agreed or Completed, and the project's invoices (net of credit notes, before GST) never
exceed the agreement value.

Revenue share. A submitted invoice is shared once, and only when it is fully paid by Payment Entry or Journal Entry
(outstanding nil, no credit note against it): a Consultancy Revenue Share splits its taxable value by the project's
rule and pays each team member through an HRMS Additional Salary on the Campus-owned "Consultancy Share" component. A
shared invoice can't be cancelled or credited and its payments can't be cancelled until the share is cancelled.

Revenue for AQAR 3.5.1 / NIRF is the taxable value of the college's consultancy invoices posted in the academic year,
net of credit notes; amounts received are payment ledger allocations from Payment Entries and Journal Entries."""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import add_days, flt, fmt_money, getdate, today

from campus.research.publications import year_bounds

PROJECT = "Consultancy Project"
SHARE = "Consultancy Revenue Share"
SALARY_COMPONENT = "Consultancy Share"
INVOICEABLE = ("Agreed", "Completed")
PAYMENT_VOUCHERS = ("Payment Entry", "Journal Entry")
INVOICE_FIELDS = ["name", "oc_consultancy_project", "customer", "posting_date", "is_return", "base_net_total",
	"base_total_taxes_and_charges", "base_grand_total"]  # fmt: skip


# ---- invoicing ----------------------------------------------------------------------------------------------------


@frappe.whitelist()
def make_sales_invoice(project, amount, description=None):
	"""A draft Sales Invoice for `amount` (before GST) of the project; the caller needs write access to the project."""
	doc = frappe.get_doc(PROJECT, project)
	doc.check_permission("write")
	return draft_sales_invoice(doc, flt(amount), description).name


def draft_sales_invoice(project, amount, description=None):
	"""Runs with ignore_permissions: client, college, item and amount come from the project and the checked amount."""
	if project.status not in INVOICEABLE:
		frappe.throw(_("Consultancy Project {0} is {1}: invoice it once the agreement is signed.").format(project.name, _(project.status)))
	remaining = flt(project.agreement_value) - invoiced_value(project.name)
	if amount <= 0 or flt(amount, 2) > flt(remaining, 2):
		frappe.throw(
			_("Enter an amount above zero and within the agreement value still to invoice ({0}).").format(
				fmt_money(remaining, currency=project.currency)
			)
		)
	invoice = frappe.new_doc("Sales Invoice")
	invoice.update(
		{
			"company": project.company, "customer": project.client, "customer_address": project.client_address,
			"posting_date": today(), "oc_consultancy_project": project.name,
			"remarks": _("Consultancy Project {0}: {1}").format(project.name, project.title),
			"items": [{"item_code": project.service_item, "qty": 1, "rate": amount, "description": description or project.title}],
		}
	)  # fmt: skip
	invoice.flags.ignore_permissions = True
	invoice.set_missing_values()  # party details: india_compliance's place of supply and GST template, with its taxes
	invoice.insert()
	return invoice


def invoiced_value(project, exclude=None, for_update=False):
	"""Taxable value of the project's submitted invoices, net of credit notes."""
	filters = {"oc_consultancy_project": project, "docstatus": 1}
	if exclude:
		filters["name"] = ["!=", exclude]
	values = frappe.db.get_values("Sales Invoice", filters, "base_net_total", for_update=for_update, pluck=True)
	return flt(sum(flt(v) for v in values), 2)


def check_invoice(invoice, method=None):
	"""Sales Invoice before_submit: a consultancy invoice bills the project's client for its college within the agreement
	value (the project row is locked so concurrent invoices queue); a credit note never reverses a shared invoice."""
	if not invoice.oc_consultancy_project:
		return
	project = frappe.db.get_value(
		PROJECT, invoice.oc_consultancy_project, ["name", "status", "company", "client", "agreement_value"], as_dict=True, for_update=True
	)
	if not project or (invoice.company, invoice.customer) != (project.company, project.client):
		frappe.throw(_("Sales Invoice {0} must bill Consultancy Project {1}'s client for its college.").format(invoice.name, invoice.oc_consultancy_project))
	if invoice.is_return:
		share = submitted_share(invoice.return_against, for_update=True)
		if share:
			frappe.throw(_("Sales Invoice {0} is shared by {1}: cancel the revenue share before crediting it.").format(invoice.return_against, share))
		return
	if project.status not in INVOICEABLE:
		frappe.throw(_("Consultancy Project {0} is {1}: it can't be invoiced.").format(project.name, _(project.status)))
	total = invoiced_value(project.name, exclude=invoice.name, for_update=True) + flt(invoice.base_net_total)
	if flt(total, 2) > flt(project.agreement_value, 2):
		frappe.throw(
			_("Consultancy Project {0} would be invoiced {1}, above its agreement value of {2}.").format(
				project.name, fmt_money(total, currency=invoice.currency), fmt_money(project.agreement_value, currency=invoice.currency)
			)
		)


def refuse_invoice_cancel(invoice, method=None):
	"""Sales Invoice before_cancel: a shared invoice stays until its revenue share is cancelled."""
	share = invoice.oc_consultancy_project and submitted_share(invoice.name, for_update=True)
	if share:
		frappe.throw(_("Sales Invoice {0} is shared by {1}: cancel the revenue share first.").format(invoice.name, share))


def refuse_payment_cancel(voucher, method=None):
	"""Payment Entry / Journal Entry before_cancel: a payment of a shared consultancy invoice stays (the share was paid
	out because it was received)."""
	if voucher.doctype == "Payment Entry":
		invoices = {r.reference_name for r in voucher.references if r.reference_doctype == "Sales Invoice"}
	else:
		invoices = {r.reference_name for r in voucher.accounts if r.reference_type == "Sales Invoice"}
	if not invoices:
		return
	shared = frappe.get_all(SHARE, {"sales_invoice": ["in", sorted(invoices)], "docstatus": 1}, ["name", "sales_invoice"])
	if shared:
		frappe.throw(
			_("{0} {1} pays a shared consultancy invoice ({2}): cancel the revenue share first.").format(
				_(voucher.doctype), voucher.name, ", ".join(f"{r.sales_invoice} / {r.name}" for r in shared)
			)
		)


# ---- revenue share ------------------------------------------------------------------------------------------------


def submitted_share(invoice, exclude=None, for_update=False):
	filters = {"sales_invoice": invoice, "docstatus": 1}
	if exclude:
		filters["name"] = ["!=", exclude]
	rows = frappe.db.get_values(SHARE, filters, "name", order_by="name", for_update=for_update, pluck=True)
	return rows[0] if rows else None


def shareable_invoice(invoice, project, share=None, for_update=False):
	"""The invoice's figures; throws unless it is a submitted invoice of `project` (not a credit note), fully paid, not
	credited and not shared by another submitted share. `for_update` locks the invoice row first and reads with locks."""
	row = frappe.db.get_value(
		"Sales Invoice", invoice, ["name", "docstatus", "is_return", "outstanding_amount", "oc_consultancy_project", "base_net_total",
		"company", "customer", "currency"], as_dict=True, for_update=for_update,
	)  # fmt: skip
	if not row or row.oc_consultancy_project != project or row.docstatus != 1 or row.is_return:
		frappe.throw(_("Sales Invoice {0} is not a submitted invoice of Consultancy Project {1}.").format(invoice, project))
	credit_notes = frappe.db.get_values(
		"Sales Invoice", {"return_against": invoice, "docstatus": 1}, "name", order_by="name", for_update=for_update, pluck=True
	)
	if credit_notes:
		frappe.throw(_("Sales Invoice {0} has credit notes ({1}): it can't be shared.").format(invoice, ", ".join(credit_notes)))
	if flt(row.outstanding_amount) > 0:
		frappe.throw(
			_("Sales Invoice {0} is not fully paid ({1} outstanding): revenue is shared only once it is received.").format(
				invoice, fmt_money(row.outstanding_amount, currency=row.currency)
			)
		)
	other = submitted_share(invoice, exclude=share, for_update=for_update)
	if other:
		frappe.throw(_("Sales Invoice {0} is already shared by {1}.").format(invoice, other))
	return row


def post_additional_salaries(share):
	"""A submitted Additional Salary per member with an amount, on the member's next payroll. Runs as the Accounts user
	submitting the share: every input comes from the server-computed share."""
	for member in share.members:
		if flt(member.amount) <= 0:
			continue
		additional = frappe.get_doc(
			{
				"doctype": "Additional Salary", "employee": member.employee, "company": share.company, "currency": share.currency,
				"salary_component": SALARY_COMPONENT, "amount": member.amount,
				"payroll_date": next_payroll_date(member.employee, share.company, share.posting_date),
				"overwrite_salary_structure_amount": 0, "ref_doctype": SHARE, "ref_docname": share.name,
			}
		)  # fmt: skip
		additional.flags.ignore_permissions = True
		additional.insert()
		additional.submit()
		member.db_set("additional_salary", additional.name)


def cancel_additional_salaries(share):
	"""HRMS refuses while a submitted Salary Slip has paid one."""
	for member in share.members:
		if member.additional_salary and frappe.db.get_value("Additional Salary", member.additional_salary, "docstatus") == 1:
			additional = frappe.get_doc("Additional Salary", member.additional_salary)
			additional.flags.ignore_permissions = True
			additional.cancel()


def next_payroll_date(employee, company, posting_date):
	"""The share's date, or the day after the employee's last processed slip if that is later."""
	last_end = frappe.db.get_value("Salary Slip", {"employee": employee, "company": company, "docstatus": 1}, "end_date", order_by="end_date desc")
	if last_end and getdate(add_days(last_end, 1)) > getdate(posting_date):
		return getdate(add_days(last_end, 1))
	return getdate(posting_date)


# ---- revenue figures (Consultancy Revenue report, AQAR 3.5.1 / NIRF data points) ----------------------------------


def invoices_in_year(company, academic_year=None, department=None):
	"""The submitted consultancy invoices (and credit notes) of the college's projects the user can read, posted in the
	academic year (all years when none)."""
	filters = {"company": company}
	if department:
		filters["department"] = department
	projects = frappe.get_list(PROJECT, filters, pluck="name", limit_page_length=0)
	if not projects:
		return []
	invoice_filters = {"oc_consultancy_project": ["in", projects], "docstatus": 1, "company": company}
	if academic_year:
		invoice_filters["posting_date"] = ["between", list(year_bounds(academic_year))]
	return frappe.get_all("Sales Invoice", invoice_filters, INVOICE_FIELDS, order_by="posting_date, name")


def received_by_invoice(invoices):
	"""{invoice: amount received by Payment Entry / Journal Entry allocations}."""
	if not invoices:
		return {}
	ledger = frappe.qb.DocType("Payment Ledger Entry")
	rows = (
		frappe.qb.from_(ledger)
		.select(ledger.against_voucher_no, frappe.query_builder.functions.Sum(ledger.amount))
		.where(
			(ledger.against_voucher_type == "Sales Invoice") & ledger.against_voucher_no.isin(list(invoices))
			& ledger.voucher_type.isin(PAYMENT_VOUCHERS) & (ledger.delinked == 0)
		)
		.groupby(ledger.against_voucher_no)
	).run()  # fmt: skip
	return {invoice: -flt(amount) for invoice, amount in rows}


def shares_by_invoice(invoices):
	"""{invoice: submitted share figures}."""
	if not invoices:
		return {}
	rows = frappe.get_all(
		SHARE, {"sales_invoice": ["in", list(invoices)], "docstatus": 1},
		["sales_invoice", "institution_amount", "faculty_amount", "staff_amount"],
	)  # fmt: skip
	return {row.sales_invoice: row for row in rows}


def consultancy_revenue(company, academic_year, department=None):
	"""(taxable value net of credit notes, invoices) of the year."""
	rows = invoices_in_year(company, academic_year, department)
	return flt(sum(flt(r.base_net_total) for r in rows), 2), rows


def revenue_by_project(company, academic_year=None, department=None):
	"""Consultancy Revenue report rows: per project, the year's taxable value, GST, total, received and shares."""
	invoices = invoices_in_year(company, academic_year, department)
	names = [r.name for r in invoices]
	received, shares = received_by_invoice(names), shares_by_invoice(names)
	projects = {}
	for inv in invoices:
		row = projects.setdefault(inv.oc_consultancy_project, frappe._dict(consultancy_project=inv.oc_consultancy_project, invoices=0,
			taxable_value=0, gst=0, invoice_total=0, received=0, institution_share=0, faculty_share=0, staff_share=0))  # fmt: skip
		row.invoices += 0 if inv.is_return else 1
		row.taxable_value += flt(inv.base_net_total)
		row.gst += flt(inv.base_total_taxes_and_charges)
		row.invoice_total += flt(inv.base_grand_total)
		row.received += received.get(inv.name, 0)
		share = shares.get(inv.name)
		if share:
			row.institution_share += flt(share.institution_amount)
			row.faculty_share += flt(share.faculty_amount)
			row.staff_share += flt(share.staff_amount)
	details = {
		p.name: p
		for p in frappe.get_all(
			PROJECT, {"name": ["in", list(projects) or [""]]},
			["name", "title", "client", "department", "principal_consultant", "status", "agreement_value", "currency"],
		)
	}  # fmt: skip
	result = []
	for name, row in projects.items():
		project = details[name]
		row.update({key: project[key] for key in ("title", "client", "department", "principal_consultant", "status", "agreement_value", "currency")})
		result.append(row)
	return result


# ---- setup --------------------------------------------------------------------------------------------------------


def setup_consultancy_fields():
	create_custom_fields(
		{
			"Sales Invoice": [
				{
					"fieldname": "oc_consultancy_project", "label": "Consultancy Project", "fieldtype": "Link", "options": PROJECT,
					"insert_after": "customer_name", "read_only": 1, "search_index": 1, "in_standard_filter": 1,
				}
			]
		},
		update=True,
	)  # fmt: skip


def seed_salary_component():
	"""Campus's own earning component, created once and never changed afterwards."""
	if frappe.db.exists("Salary Component", SALARY_COMPONENT):
		return
	frappe.get_doc(
		{
			"doctype": "Salary Component", "salary_component": SALARY_COMPONENT, "salary_component_abbr": "CONS", "type": "Earning",
			"description": "Consultancy revenue share (OneBook Campus)", "is_tax_applicable": 1, "depends_on_payment_days": 0,
		}
	).insert(ignore_permissions=True)  # fmt: skip
