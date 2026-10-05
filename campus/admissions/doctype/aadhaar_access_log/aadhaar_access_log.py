"""M04-02 Aadhaar Access Log: one immutable row per reveal of a full Aadhaar number (decision D12).

Frappe's own Access Log is purged after 30 days and written through a deferred queue, so reveals are
logged here instead: inserted in the same transaction as the reveal and never purged.
"""

from frappe.model.document import Document


class AadhaarAccessLog(Document):
	pass
