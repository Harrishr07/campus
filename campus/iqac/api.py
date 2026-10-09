"""M15-01 IQAC service API. Other modules call these, never the controllers (D7)."""

import frappe

from campus.iqac import compute
from campus.iqac import framework as framework_lifecycle


@frappe.whitelist(methods=["POST"])
def compute_cycle(cycle):
	"""Compute all formula metrics of an Accreditation Cycle (IQAC Coordinator / System Manager); returns Metric Value names."""
	frappe.only_for(compute.ROLES)
	return compute.compute_cycle(cycle)


@frappe.whitelist(methods=["POST"])
def clone_framework(framework, new_name, version):
	"""Clone to new version (M01-01): a Draft copy of `framework` with identical nodes; needs the create right on frameworks."""
	frappe.has_permission("Accreditation Framework", "create", throw=True)
	return framework_lifecycle.clone(framework, new_name, version)
