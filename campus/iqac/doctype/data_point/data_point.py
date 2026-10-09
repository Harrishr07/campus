"""M01-02 Data Point: one registered `@campus_metric` function, synced from the code registry (campus.iqac.setup.sync_data_points).

The registry in campus.iqac.registry is the only source; this DocType makes it visible to users writing formulas.
"""

from frappe.model.document import Document


class DataPoint(Document):
	pass
