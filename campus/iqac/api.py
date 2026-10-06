"""M15-01 IQAC service API. Other modules call these, never the controllers (D7)."""

import frappe

from campus.iqac import compute


@frappe.whitelist(methods=["POST"])
def compute_cycle(cycle):
	"""Compute all formula metrics of an Accreditation Cycle (IQAC Coordinator / System Manager); returns Metric Value names."""
	frappe.only_for(compute.ROLES)
	return compute.compute_cycle(cycle)
