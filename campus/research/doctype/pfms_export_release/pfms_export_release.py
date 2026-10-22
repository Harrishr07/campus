"""M08-07 PFMS Export Release: the log of a held PFMS export line an Accounts Manager released after review
(campus.research.pfms.release_after_review). The next batch exports the line for this amount, if it still fits the
payment."""

from frappe.model.document import Document


class PFMSExportRelease(Document):
	pass
