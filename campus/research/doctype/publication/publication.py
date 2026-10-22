"""M08-12 Publication: a journal article, conference paper, book or book chapter of the college, with its authors (Employees,
Students or external people), journal (an Indexed Journal, which carries the indexing) and citations.

Entering a DOI fills the blank title, type, date, journal and authors from Crossref (campus.research.publications). A DOI
is stored lower case and is unique, so a work is entered once; a person is an author of a work once."""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.research import publications
from campus.research.crossref import normalise_doi
from campus.research.contributors import validate_contributors


class Publication(Document):
	def before_validate(self):
		if self.doi:
			self.doi = normalise_doi(self.doi)
			if not self.title:
				self.fill_from_crossref()

	def validate(self):
		self.doi = self.doi or None  # NULL, so the unique index allows many publications without a DOI
		self.check_unique_doi()
		self.check_source()
		validate_contributors(self.authors, "author_type", "author_name", _("author"), self.company)
		self.publication_year = frappe.utils.getdate(self.publication_date).year

	def db_insert(self, *args, **kwargs):
		self.refuse_duplicate_doi_race(super().db_insert, *args, **kwargs)

	def db_update(self, *args, **kwargs):
		self.refuse_duplicate_doi_race(super().db_update, *args, **kwargs)

	def refuse_duplicate_doi_race(self, write, *args, **kwargs):
		"""Two saves of one DOI at once pass check_unique_doi; the unique index stops the second, with the same message."""
		try:
			write(*args, **kwargs)
		except frappe.UniqueValidationError:
			if not self.doi:
				raise
			frappe.throw(_("The DOI {0} is already entered.").format(self.doi))

	def check_unique_doi(self):
		if not self.doi:
			return
		other = frappe.db.get_value("Publication", {"doi": self.doi, "name": ["!=", self.name]})
		if other:
			frappe.throw(_("The DOI {0} is already entered as {1}.").format(self.doi, other))

	def check_source(self):
		if self.publication_type != "Book" and not (self.journal or self.container_title):
			frappe.throw(_("Enter the journal, proceedings or book the publication appeared in."))

	@frappe.whitelist()
	def fill_from_crossref(self):
		"""Fill the blank fields (and the authors, when none are entered) from Crossref for this DOI."""
		publications.fill_from_crossref(self)
