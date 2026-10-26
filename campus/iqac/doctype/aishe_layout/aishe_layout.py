"""M01-09 AISHE Layout: where each section of the AISHE dataset goes in the Excel file, kept as data. The official AISHE
template is not available, so the seeded layout is a labelled placeholder to be replaced by the college."""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.iqac.export import parse_cell, sheet_problem


class AISHELayout(Document):
	def validate(self):
		sections, starts = set(), set()
		for row in self.sections:
			row.sheet = (row.sheet or "").strip()
			problem = sheet_problem(row.sheet)
			if problem:
				frappe.throw(
					_("Row {0}: sheet name {1}: {2}").format(row.idx, frappe.bold(row.sheet), problem)
				)
			if not parse_cell(row.first_cell):
				frappe.throw(
					_("Row {0}: {1} is not a cell like B7.").format(row.idx, frappe.bold(row.first_cell))
				)
			row.first_cell = row.first_cell.strip().upper()
			if row.section in sections:
				frappe.throw(_("Row {0}: {1} is already mapped.").format(row.idx, frappe.bold(row.section)))
			if (row.sheet.lower(), row.first_cell) in starts:
				frappe.throw(
					_("Row {0}: {1} on {2} is already the start of another section.").format(
						row.idx, row.first_cell, frappe.bold(row.sheet)
					)
				)
			sections.add(row.section)
			starts.add((row.sheet.lower(), row.first_cell))
