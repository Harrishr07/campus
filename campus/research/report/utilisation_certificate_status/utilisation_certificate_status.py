"""M08-06 Utilisation Certificate Status: for each submitted sanction of a college, one row per fiscal year of its
period (cut to the sanction's dates) with the date its UC falls due (period end + the college's UC Due Days) and where
it stands: Submitted (an approved UC covers the period end), Source Changed (that UC's ledger moved since), Not Yet Due
(the period has not ended), Due or Overdue. Read through get_list, so User Permissions apply."""

import frappe
from frappe import _
from frappe.utils import add_days, cint, getdate, today

SANCTION_FIELDS = ["name", "title", "funding_agency", "pi_name", "start_date", "end_date"]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		return columns(), []
	due_days = cint(frappe.db.get_value("Research Settings", filters.company, "uc_due_days"))
	query = {"company": filters.company, "docstatus": 1}
	if filters.sanction:
		query["name"] = filters.sanction
	rows = []
	for sanction in frappe.get_list("Sanction", query, SANCTION_FIELDS, order_by="start_date asc, name asc"):
		rows.extend(sanction_rows(sanction, filters.company, due_days))
	if filters.status:
		rows = [row for row in rows if row["status"] == _(filters.status)]
	return columns(), rows


def sanction_rows(sanction, company, due_days):
	rows = []
	for start, end in periods(sanction, company):
		certificate = covering_certificate(sanction.name, end)
		due_date = add_days(end, due_days)
		rows.append(
			{
				"sanction": sanction.name, "title": sanction.title, "funding_agency": sanction.funding_agency,
				"pi_name": sanction.pi_name, "from_date": start, "to_date": end, "due_date": due_date,
				"status": _(status(certificate, end, due_date)), "certificate": certificate and certificate.name,
			}  # fmt: skip
		)
	return rows


def periods(sanction, company):
	"""[(start, end)] of the fiscal years overlapping the sanction (those of the college), cut to its dates."""
	start, end = getdate(sanction.start_date), getdate(sanction.end_date)
	years = frappe.get_all(
		"Fiscal Year",
		{"year_start_date": ["<=", end], "year_end_date": [">=", start], "disabled": 0},
		["name", "year_start_date", "year_end_date"],
		order_by="year_start_date asc",
	)
	result = []
	for year in years:
		companies = frappe.get_all("Fiscal Year Company", {"parent": year.name}, pluck="company")
		if companies and company not in companies:
			continue
		result.append((max(start, getdate(year.year_start_date)), min(end, getdate(year.year_end_date))))
	return result


def covering_certificate(sanction, period_end):
	found = frappe.get_list(
		"Utilisation Certificate",
		{"sanction": sanction, "docstatus": 1, "from_date": ["<=", period_end], "to_date": [">=", period_end]},
		["name", "source_changed"],
		limit=1,
	)
	return found[0] if found else None


def status(certificate, period_end, due_date):
	if certificate:
		return "Source Changed" if certificate.source_changed else "Submitted"
	if getdate(period_end) >= getdate(today()):
		return "Not Yet Due"
	return "Due" if getdate(due_date) >= getdate(today()) else "Overdue"


def columns():
	def col(fieldname, label, fieldtype="Data", width=120, options=None):
		return {"fieldname": fieldname, "label": _(label), "fieldtype": fieldtype, "width": width, "options": options}

	return [
		col("sanction", "Sanction", "Link", 150, "Sanction"),
		col("title", "Title", width=200),
		col("funding_agency", "Funding Agency", "Link", 150, "Funding Agency"),
		col("pi_name", "PI", width=150),
		col("from_date", "From Date", "Date", 100),
		col("to_date", "To Date", "Date", 100),
		col("due_date", "Due Date", "Date", 100),
		col("status", "Status", width=120),
		col("certificate", "Certificate", "Link", 150, "Utilisation Certificate"),
	]
