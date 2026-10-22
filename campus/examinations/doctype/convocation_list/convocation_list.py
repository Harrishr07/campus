"""M06-07 Convocation List: the eligible graduates of a company (and programme) for the university's convocation,
filled by Get Graduates and exported in the column format set on the list (campus.examinations.convocation)."""

import frappe
from frappe import _
from frappe.model.document import Document


class ConvocationList(Document):
	def validate(self):
		from campus.examinations.convocation import DEFAULT_COLUMNS

		if self.program and frappe.db.get_value("Program", self.program, "oc_company") != self.company:
			frappe.throw(_("Program {0} does not belong to {1}.").format(frappe.bold(self.program), frappe.bold(self.company)))
		if not self.columns:
			for heading, source in DEFAULT_COLUMNS:
				self.append("columns", {"heading": heading, "source": source})

	def on_trash(self):
		"""Deletable only while it has written nothing: refused once a graduate's lifecycle transition came from it."""
		if frappe.db.exists("Lifecycle Transition", {"source_doctype": self.doctype, "source_name": self.name}):
			frappe.throw(_("{0} has moved students through the lifecycle: it is kept as their reference.").format(frappe.bold(self.name)))
