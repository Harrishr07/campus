"""M04-07 Candidate Duplicate Review: a possible duplicate candidate awaiting a Link / Not Duplicate decision.

The decision is taken only through campus.admissions.duplicates.decide (Admission Officer), which stamps who
decided, when and why; the form fields are read-only.
"""

from frappe.model.document import Document


class CandidateDuplicateReview(Document):
	pass
