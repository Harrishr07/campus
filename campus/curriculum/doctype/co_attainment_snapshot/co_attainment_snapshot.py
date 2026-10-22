"""M03-03 CO Attainment Snapshot: the per-student CIA / ESE marks a CO Attainment Run was computed from (the input
snapshot), one per run. Read by System Manager, COE and Dean Academics only, never shared or versioned, and written
only by the computation (campus.curriculum.attainment, ignore_permissions), so the run itself never carries a student's
marks."""

from frappe.model.document import Document


class COAttainmentSnapshot(Document):
	pass
