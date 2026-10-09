"""M01-03 Validation Run: the results of checking one Accreditation Cycle against the Validation Rules at a moment.

Made only by campus.iqac.validation.run; the status gate of the cycle checks afresh and does not rely on a stored run.
"""

from frappe.model.document import Document


class ValidationRun(Document):
	pass
