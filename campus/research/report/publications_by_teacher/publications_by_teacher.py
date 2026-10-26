"""M08-12 Publications by Teacher (AQAR 3.4.3-3.4.6, faculty profile): one row per Employee author with their own count of the
college's publications of an academic year, UGC-CARE papers, books and chapters, citations and h-index. A publication by
three teachers shows once in each of their rows (and once in the Publication Register). Read with the user's permissions."""

from frappe import _

from campus.research import publications


def execute(filters=None):
	filters = filters or {}
	if not (filters.get("company") and filters.get("academic_year")):
		return columns(), []
	return columns(), publications.teacher_rows(
		filters["company"], filters["academic_year"], filters.get("department")
	)


def columns():
	def col(fieldname, label, fieldtype="Data", width=110, options=None):
		return {
			"fieldname": fieldname,
			"label": _(label),
			"fieldtype": fieldtype,
			"width": width,
			"options": options,
		}

	return [
		col("employee", "Employee", "Link", 130, "Employee"),
		col("employee_name", "Name", width=170),
		col("department", "Department", "Link", 200, "Department"),
		col("publications", "Publications", "Int"),
		col("ugc_care_papers", "UGC-CARE Papers", "Int", 130),
		col("books_chapters", "Books, Chapters, Conference", "Int", 190),
		col("citations", "Citations", "Int"),
		col("h_index", "h-index", "Int", 90),
	]
