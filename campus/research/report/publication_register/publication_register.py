"""M08-12 Publication Register (AQAR 3.4.3-3.4.5, NIRF publications): the college's publications dated in an academic year, one row
per publication however many authors it has, so the row count is the institution's count. Read with the user's permissions."""

from frappe import _

from campus.research import publications


def execute(filters=None):
	filters = filters or {}
	if not (filters.get("company") and filters.get("academic_year")):
		return columns(), []
	return columns(), publications.register_rows(
		filters["company"], filters["academic_year"], filters.get("department")
	)


def columns():
	def col(fieldname, label, fieldtype="Data", width=120, options=None):
		return {
			"fieldname": fieldname,
			"label": _(label),
			"fieldtype": fieldtype,
			"width": width,
			"options": options,
		}

	return [
		col("name", "Publication", "Link", 130, "Publication"),
		col("title", "Title", width=260),
		col("publication_type", "Type", width=120),
		col("publication_date", "Date", "Date", 100),
		col("doi", "DOI", width=170),
		col("journal", "Indexed Journal", "Link", 150, "Indexed Journal"),
		col("container_title", "Journal / Proceedings / Book", width=200),
		col("ugc_care", "UGC-CARE", "Check", 80),
		col("citations", "Citations", "Int", 90),
		col("authors", "Authors", "Int", 80),
		col("teacher_authors", "Teacher Authors", "Int", 110),
	]
