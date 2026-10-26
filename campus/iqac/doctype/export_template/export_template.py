"""M01-03 Export Template: where the nodes of a framework go in an exported file, kept as data.

Excel: each mapping row names the sheet and cell of a node's value (and optionally the cell of its label, and whether to
list the records behind it on a Data Template sheet). PDF: each row names the section the node is printed under. Moving a
cell is an edit of this record; the exporter (campus.iqac.export) has no layout of its own.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.iqac.export import parse_cell, sheet_problem


class ExportTemplate(Document):
	def validate(self):
		self.template_name = (self.template_name or "").strip()
		seen = set()
		for row in self.mappings:
			self.validate_node(row)
			if self.export_format == "Excel":
				self.validate_excel_row(row, seen)
			elif not (row.section or "").strip():
				frappe.throw(_("Row {0}: a PDF mapping needs a section.").format(row.idx))

	def validate_node(self, row):
		if frappe.db.get_value("Framework Node", row.node, "framework") != self.framework:
			frappe.throw(
				_("Row {0}: {1} is not a node of {2}.").format(
					row.idx, frappe.bold(row.node), frappe.bold(self.framework)
				)
			)

	def validate_excel_row(self, row, seen):
		sheet = (row.sheet or "").strip()
		if not sheet or not (row.cell or "").strip():
			frappe.throw(_("Row {0}: an Excel mapping needs a sheet and a cell.").format(row.idx))
		problem = sheet_problem(sheet)
		if problem:
			frappe.throw(_("Row {0}: sheet name {1}: {2}").format(row.idx, frappe.bold(sheet), problem))
		cells = [row.cell, row.label_cell] if row.label_cell else [row.cell]
		for cell in cells:
			if not parse_cell(cell):
				frappe.throw(_("Row {0}: {1} is not a cell like B7.").format(row.idx, frappe.bold(cell)))
			key = (sheet.lower(), cell.strip().upper())
			if key in seen:
				frappe.throw(
					_("Row {0}: {1} on {2} is already used by another mapping.").format(
						row.idx, frappe.bold(cell), frappe.bold(sheet)
					)
				)
			seen.add(key)
		row.sheet, row.cell = sheet, row.cell.strip().upper()
		row.label_cell = row.label_cell.strip().upper() if row.label_cell else None
