"""M08-11 Patent counts for one company and academic year, shared by the Patent Register and the IPR data points.

A patent is counted once, in the academic year its filing / publication / grant date falls in; it is counted in every
stage it has reached on its own date. A department narrows to the patents of disclosures of that department. Read with the
session user's permissions."""

import frappe

from campus.research.ipr import STAGE_DATES
from campus.research.publications import year_bounds

FIELDS = ["name", "title", "company", "department", "ipr_type", "status", "application_number", "patent_number", "jurisdiction",
	"filed_date", "published_date", "examined_date", "granted_date", "total_cost", "total_revenue", "institution_revenue",
	"inventors_revenue", "currency"]  # fmt: skip


def patents_in_year(company, academic_year, stage, department=None):
	"""The company's patents whose `stage` (Filed, Published, Examined or Granted) date is in the academic year, by that date."""
	field = STAGE_DATES[stage]
	start, end = year_bounds(academic_year)
	filters = {"company": company, field: ["between", [start, end]]}
	if department:
		filters["department"] = department
	return frappe.get_list("Patent", filters, FIELDS, order_by=f"{field}, name", limit_page_length=0)


def patent_register(company, status=None, academic_year=None):
	"""The company's patents (all, or those filed in the academic year), newest filing first, with their costs and revenue."""
	filters = {"company": company}
	if status:
		filters["status"] = status
	if academic_year:
		filters["filed_date"] = ["between", list(year_bounds(academic_year))]
	return frappe.get_list("Patent", filters, FIELDS, order_by="filed_date desc, name", limit_page_length=0)


def employee_patents(employee):
	"""The Patents of disclosures that name `employee` as an inventor."""
	disclosures = frappe.get_all(
		"IPR Inventor", {"employee": employee, "parenttype": "Invention Disclosure"}, pluck="parent"
	)
	return frappe.get_list(
		"Patent",
		{"invention_disclosure": ["in", disclosures or [""]]},
		FIELDS,
		order_by="filed_date desc, name",
		limit_page_length=0,
	)
