"""M01-08 Official Document: an approval, affiliation, accreditation or recognition document of a college with its authority,
reference, validity and file. The status follows the dates and the link to the document that replaced it; expiry alerts run
from campus.iqac.official_documents."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from campus.iqac import official_documents as register


class OfficialDocument(Document):
	def validate(self):
		if getdate(self.valid_to) < getdate(self.valid_from):
			frappe.throw(_("Valid To cannot be before Valid From."))
		self.check_program()
		self.check_file()
		register.check_successor(self)
		self.status = register.document_status(self.valid_to, self.superseded_by)

	def check_program(self):
		if self.program and frappe.db.get_value("Program", self.program, "oc_company") != self.company:
			frappe.throw(_("{0} is not a program of {1}.").format(frappe.bold(self.program), frappe.bold(self.company)))

	def check_file(self):
		if self.file and not self.file.startswith("/private/"):
			frappe.throw(_("The file must be private. Attach it as a private file."))
