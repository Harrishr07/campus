"""M08-11 Patent Register (AQAR 3.3, NIRF IPR): the college's patents with stage dates, costs and licence revenue split between the
institution and the inventors. Optionally those filed in an academic year or at one status. Read with the user's permissions."""

from frappe import _

from campus.research import patents


def execute(filters=None):
	filters = filters or {}
	if not filters.get("company"):
		return columns(), []
	return columns(), patents.patent_register(filters["company"], filters.get("status"), filters.get("academic_year"))


def columns():
	def col(fieldname, label, fieldtype="Data", width=110, options=None):
		return {"fieldname": fieldname, "label": _(label), "fieldtype": fieldtype, "width": width, "options": options}

	return [
		col("name", "Patent", "Link", 120, "Patent"),
		col("title", "Title", width=240),
		col("ipr_type", "IPR Type", "Link", 110, "IPR Type"),
		col("status", "Status", width=90),
		col("application_number", "Application No.", width=130),
		col("patent_number", "Patent No.", width=120),
		col("filed_date", "Filed", "Date", 95),
		col("published_date", "Published", "Date", 95),
		col("examined_date", "Examined", "Date", 95),
		col("granted_date", "Granted", "Date", 95),
		col("total_cost", "Total Cost", "Currency", 110, "currency"),
		col("total_revenue", "Licence Revenue", "Currency", 120, "currency"),
		col("institution_revenue", "Institution Share", "Currency", 120, "currency"),
		col("inventors_revenue", "Inventors' Share", "Currency", 120, "currency"),
		col("currency", "Currency", "Link", 70, "Currency"),
	]
