"""M08-10 Consultancy Revenue (AQAR 3.5.1, NIRF consultancy): per consultancy project of the college, the taxable value
invoiced in the academic year (all years when none) net of credit notes, its GST, the amount received by payments and
the revenue shared to the institution, faculty and staff. Projects are read with the user's permissions."""

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
		col("received", "Received"),
		col("institution_share", "Institution Share"),
		col("faculty_share", "Faculty Share"),
		col("staff_share", "Staff Share"),
		col("currency", "Currency", "Link", 70, "Currency"),
	]
