"""M08-12 Publications: Crossref fill and the counting rules behind the reports and data points.

Counting. A publication counts once for the institution (the college) however many authors it has, and once for each
Employee who is an author (a person is an author of a work once, so no one counts twice). A Student or external author
adds to neither teacher figure. The year of a publication is the academic year its publication date falls in. A
department narrows to the publications that have an author Employee of that department, and to those Employees.
Everything is read with the session user's permissions.

Citations and the h-index (AQAR 3.4.5, 3.4.6) cover a window of academic years (Research Settings, 5 by default) ending with the
reported one: an h-index can't be added up from yearly figures.

Indexing is read live from the Indexed Journal, so a change in the UGC-CARE list shows in the next report. The h-index
of a set is the largest h such that h publications have at least h citations each."""

import frappe
from frappe.utils import add_years

from campus.research import crossref

JOURNAL_ARTICLE = "Journal Article"
BOOK_TYPES = ("Book", "Book Chapter", "Conference Paper")  # AQAR 3.4.4: books, chapters and conference proceedings
DEFAULT_WINDOW_YEARS = 5
FIELDS = ["name", "title", "doi", "publication_type", "publication_date", "journal", "container_title", "citations"]


def fill_from_crossref(publication):
	"""Fill the blank fields of `publication` from Crossref for its DOI; an entered value is never replaced."""
	work = crossref.parse_work(crossref.fetch_work(publication.doi))
	for field in ("title", "container_title", "publisher", "publication_date", "publication_type", "citations"):
		if not publication.get(field) and work.get(field):
			publication.set(field, work[field])
	if work["citations"] is not None and not publication.citations_as_on:
		publication.citations_as_on = frappe.utils.today()
	if not publication.journal:
		publication.journal = journal_of(work["issns"])
	if not publication.authors:
		for author in work["authors"]:
			publication.append("authors", author)
	return work


def journal_of(issns):
	"""The Indexed Journal with one of `issns` as its ISSN or e-ISSN, or None."""
	if not issns:
		return None
	found = frappe.get_all("Indexed Journal", or_filters=[["issn", "in", issns], ["e_issn", "in", issns]], pluck="name", limit=1)
	return found[0] if found else None


def hindex(citations):
	"""The h-index of a list of citation counts."""
	ranked = sorted((c or 0 for c in citations), reverse=True)
	return sum(1 for rank, count in enumerate(ranked, 1) if count >= rank)


def year_bounds(academic_year):
	start, end = frappe.get_cached_value("Academic Year", academic_year, ["year_start_date", "year_end_date"])
	return start, end


def employee_authors(publication_names):
	"""[(publication, employee)] of Employee authors of the publications."""
	if not publication_names:
		return []
	return frappe.get_all(
		"Publication Author",
		{"parent": ["in", publication_names], "parenttype": "Publication", "author_type": "Employee"},
		["parent", "employee"],
		as_list=True,
		order_by="parent, idx",
	)


def employees(names, company, department=None):
	"""{employee: row} of the `company` Employees among `names`, in `department` when given. The caller has already been let
	into the company's publications, so names and departments are read without the Employee list permission."""
	if not names:
		return {}
	filters = {"name": ["in", list(names)], "company": company}
	if department:
		filters["department"] = department
	rows = frappe.get_all("Employee", filters, ["name", "employee_name", "department"], limit_page_length=0)
	return {row.name: row for row in rows}


def journal_flags(rows):
	"""Adds `ugc_care` (0 / 1) to each publication row from its Indexed Journal."""
	journals = {row.journal for row in rows if row.journal}
	flags = {
		j.name: j.ugc_care for j in frappe.get_all("Indexed Journal", {"name": ["in", list(journals) or [""]]}, ["name", "ugc_care"])
	}
	for row in rows:
		row.ugc_care = 1 if flags.get(row.journal) else 0
	return rows


def window_years(company):
	"""How many academic years the citation figures cover (Research Settings, 5 when not set)."""
	return frappe.db.get_value("Research Settings", company, "publication_window_years") or DEFAULT_WINDOW_YEARS


def publications_in_window(company, academic_year, department=None):
	"""The company's publications of the last `window_years` academic years ending with `academic_year`."""
	start, end = year_bounds(academic_year)
	return publications_between(company, add_years(start, 1 - window_years(company)), end, department)


def publications_in_year(company, academic_year, department=None):
	"""The company's publications dated in the academic year (with `ugc_care`), each once, newest first."""
	return publications_between(company, *year_bounds(academic_year), department)


def publications_between(company, start, end, department=None):
	rows = frappe.get_list(
		"Publication",
		{"company": company, "publication_date": ["between", [start, end]]},
		FIELDS,
		order_by="publication_date desc, name",
		limit_page_length=0,
	)
	if department:
		authored = employee_authors([r.name for r in rows])
		in_department = employees({e for _p, e in authored}, company, department)
		wanted = {p for p, e in authored if e in in_department}
		rows = [r for r in rows if r.name in wanted]
	return journal_flags(rows)


def is_ugc_care_paper(row):
	return row.publication_type == JOURNAL_ARTICLE and row.ugc_care


def teacher_rows(company, academic_year, department=None):
	"""One row per Employee author of the year's publications: employee, employee_name, department and the counts
	publications, ugc_care_papers, books_chapters, citations, h_index of their own publications."""
	pubs = {r.name: r for r in publications_in_year(company, academic_year, department)}
	authored = employee_authors(list(pubs))
	people = employees({e for _p, e in authored}, company, department)
	own = {}
	for publication, employee in authored:
		if employee in people:
			own.setdefault(employee, []).append(pubs[publication])
	return [
		{
			"employee": employee, "employee_name": people[employee].employee_name, "department": people[employee].department,
			"publications": len(rows),
			"ugc_care_papers": sum(1 for r in rows if is_ugc_care_paper(r)),
			"books_chapters": sum(1 for r in rows if r.publication_type in BOOK_TYPES),
			"citations": sum(r.citations or 0 for r in rows),
			"h_index": hindex(r.citations for r in rows),
		}
		for employee, rows in sorted(own.items(), key=lambda item: (people[item[0]].department or "", item[0]))
	]  # fmt: skip


def register_rows(company, academic_year, department=None):
	"""One row per publication with the number of its authors and of its Employee authors."""
	pubs = publications_in_year(company, academic_year, department)
	authors = frappe.get_all(
		"Publication Author",
		{"parent": ["in", [p.name for p in pubs] or [""]], "parenttype": "Publication"},
		["parent", "author_type"],
		as_list=True,
	)
	counts = {}
	for parent, kind in authors:
		total, staff = counts.get(parent, (0, 0))
		counts[parent] = (total + 1, staff + (kind == "Employee"))
	return [dict(p) | {"authors": counts.get(p.name, (0, 0))[0], "teacher_authors": counts.get(p.name, (0, 0))[1]} for p in pubs]


def employee_profile(employee):
	"""Publications of one Employee (newest first, with `ugc_care`), their citations and h-index, for the faculty profile."""
	names = frappe.get_all("Publication Author", {"employee": employee, "parenttype": "Publication"}, pluck="parent")
	rows = frappe.get_list(
		"Publication", {"name": ["in", names or [""]]}, FIELDS, order_by="publication_date desc, name", limit_page_length=0
	)
	journal_flags(rows)
	return {
		"publications": rows,
		"publication_count": len(rows),
		"citations": sum(r.citations or 0 for r in rows),
		"h_index": hindex(r.citations for r in rows),
	}
