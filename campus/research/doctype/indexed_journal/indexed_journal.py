"""M08-01 Indexed Journal: a journal with its ISSN / e-ISSN and indexing (Scopus, Web of Science, UGC-CARE)."""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.research.issn import normalise_issn


class IndexedJournal(Document):
	def validate(self):
		if not (self.issn or self.e_issn):
			frappe.throw(_("Enter the journal's ISSN or e-ISSN."))
		self.issn = (
			normalise_issn(self.issn) if self.issn else None
		)  # NULL, so the unique index allows many blanks
		self.e_issn = normalise_issn(self.e_issn) if self.e_issn else None
		if not self.ugc_care:
			self.ugc_care_group = None
