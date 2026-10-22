"""M08-10 Consultancy Revenue (AQAR 3.5.1): per consultancy project of the college, the taxable value
invoiced in the academic year (all years when none) net of credit notes, its GST, the amount received to date on those
invoices by payments, the revenue shared to the institution, faculty and staff, and the invoices received in full but not
yet shared. Projects are read with the user's permissions."""

from frappe import _

from campus.research import consultancy


def execute(filters=None):
	filters = filters or {}
	if not filters.get("company"):
		return columns(), []
	return columns(), consultancy.revenue_by_project(filters["company"], filters.get("academic_year"), filters.get("department"))


def columns():
	def col(fieldname, label, fieldtype="Currency", width=120, options="currency"):
		return {"fieldname": fieldname, "label": _(label), "fieldtype": fieldtype, "width": width, "options": options}

	return [
		col("consultancy_project", "Project", "Link", 130, "Consultancy Project"),
		col("title", "Title", "Data", 220, None),
		col("client", "Client", "Link", 160, "Customer"),
		col("department", "Department", "Link", 140, "Department"),
		col("principal_consultant", "Principal Consultant", "Link", 130, "Employee"),
		col("status", "Status", "Data", 90, None),
		col("agreement_value", "Agreement Value"),
		col("invoices", "Invoices", "Int", 80, None),
		col("taxable_value", "Taxable Value"),
		col("gst", "GST"),
		col("invoice_total", "Invoice Total"),
		col("received", "Received to Date"),
		col("institution_share", "Institution Share"),
		col("faculty_share", "Faculty Share"),
		col("staff_share", "Staff Share"),
		col("paid_not_shared", "Paid, Not Shared", "Int", 110, None),
		col("currency", "Currency", "Link", 70, "Currency"),
	]
