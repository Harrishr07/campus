"""M02-04 / M03-01 The Effective curriculum a batch follows.

A curriculum made Effective by an Academic Proposal lists the batches it applies to; one with no listed batch is the
default for every batch of its programme and regulation. A batch follows the highest version that lists it, else the
highest default version.
"""

import frappe


def pick_curriculum(candidates, batch):
	"""Name of the curriculum `batch` follows among `candidates` (name, version, batches), or None."""
	listed = [c for c in candidates if batch and batch in c.batches]
	defaults = [c for c in candidates if not c.batches]
	chosen = listed or defaults
	return max(chosen, key=lambda c: c.version).name if chosen else None


def effective_curriculum(program, regulation, batch=None):
	"""The Effective curriculum of `program` under `regulation` for students admitted in `batch` (an Academic Year)."""
	rows = frappe.get_all(
		"Curriculum", {"program": program, "regulation": regulation, "status": "Effective"}, ["name", "version"]
	)
	batches = frappe.get_all(
		"Curriculum Batch",
		{"parenttype": "Curriculum", "parent": ["in", [r.name for r in rows] or [""]]},
		["parent", "academic_year"],
	)
	listed = {}
	for row in batches:
		listed.setdefault(row.parent, set()).add(row.academic_year)
	return pick_curriculum([frappe._dict(r, batches=listed.get(r.name, set())) for r in rows], batch)
