"""M08-07 PFMS Export Layout: the column mapping of a PFMS EAT export file, so the layout changes without code.

Each column has a header and a source (a field of the payment row or the batch, or a fixed value). The seeded layouts
are placeholders until the official EAT bulk-upload spec is supplied. The status section names the columns of the
status file PFMS returns. Every layout carries the Row Reference, which is how a status line finds its row."""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.research.pfms_adapter import FIXED_VALUE, ROW_REFERENCE, value_set


class PFMSExportLayout(Document):
	def validate(self):
		if not self.columns:
			frappe.throw(_("Add the columns of the export file."))
		headers = [(column.column_header or "").strip() for column in self.columns]
		repeated = sorted({header for header in headers if headers.count(header) > 1})
		if repeated:
			frappe.throw(_("Column headers {0} are used more than once.").format(", ".join(repeated)))
		if not any(column.source == ROW_REFERENCE for column in self.columns):
			frappe.throw(
				_("Add a {0} column: PFMS's status file is matched to the rows by it.").format(
					_(ROW_REFERENCE)
				)
			)
		both = value_set(self.success_values) & value_set(self.failure_values)
		if both:
			frappe.throw(
				_("Status values {0} are listed as both success and failure.").format(", ".join(sorted(both)))
			)
		for column in self.columns:
			if column.source == FIXED_VALUE and not (column.fixed_value or "").strip():
				frappe.throw(
					_("Row {0}: enter the fixed value of column {1}.").format(
						column.idx, column.column_header
					)
				)
