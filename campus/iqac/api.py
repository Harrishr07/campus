"""M01-01 / M01-02 / M01-03 IQAC service API. Other modules call these, never the controllers (D7)."""

import frappe

from campus.campus_platform.api import request_approval
from campus.iqac import compute, metric_values
from campus.iqac import cycle as lifecycle
from campus.iqac import framework as framework_lifecycle


@frappe.whitelist(methods=["POST"])
def compute_cycle(cycle):
	"""Compute all formula metrics of an Accreditation Cycle (IQAC Coordinator / System Manager); returns Metric Value names."""
	frappe.only_for(compute.ROLES)
	return compute.compute_cycle(cycle)


@frappe.whitelist(methods=["POST"])
def compute_all(cycle):
	"""Compute all formula metrics as a background bulk run; returns the Bulk Run name."""
	return compute.compute_all(cycle)


@frappe.whitelist(methods=["POST"])
def advance_cycle(cycle_name):
	"""Collecting -> Validating -> IQAC Review, and Approved -> Submitted."""
	lifecycle.advance(cycle_name)


@frappe.whitelist(methods=["POST"])
def reopen_cycle(cycle_name):
	"""Back to Collecting before approval."""
	lifecycle.reopen(cycle_name)


@frappe.whitelist(methods=["POST"])
def prepare_values(cycle_name):
	"""Draft Metric Values for every node answered by hand; returns the new names."""
	return lifecycle.prepare_values(cycle_name)


@frappe.whitelist(methods=["POST"])
def verify_metric(metric_value):
	metric_values.verify(metric_value)


@frappe.whitelist(methods=["POST"])
def reopen_metric(metric_value):
	metric_values.reopen(metric_value)


@frappe.whitelist(methods=["POST"])
def request_override(metric_value, proposed_value, reason):
	"""Ask to replace the computed value by `proposed_value`: makes a Metric Override and sends it for approval; returns its name."""
	override = frappe.get_doc(
		{"doctype": "Metric Override", "metric_value": metric_value, "proposed_value": proposed_value, "reason": reason}
	).insert()
	request_approval(override.doctype, override.name)
	return override.name


@frappe.whitelist(methods=["POST"])
def clone_framework(framework, new_name, version):
	"""Clone to new version (M01-01): a Draft copy of `framework` with identical nodes; needs the create right on frameworks."""
	frappe.has_permission("Accreditation Framework", "create", throw=True)
	return framework_lifecycle.clone(framework, new_name, version)
