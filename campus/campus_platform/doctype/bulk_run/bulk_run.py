"""NFR-PERF Bulk Run: one resumable background run of a handler over many items (P1-T09).

Created and driven only by `campus.campus_platform.bulk`; the form is read-only.
"""

import json

from frappe.model.document import Document


class BulkRun(Document):
	def get_parameters(self):
		"""Parameters given to `run_bulk`, as a dict."""
		return json.loads(self.parameters) if self.parameters else {}
