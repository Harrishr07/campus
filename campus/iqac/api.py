"""M01-01 / M01-02 / M01-03 IQAC service API. Other modules call these, never the controllers (D7)."""

import frappe

from campus.campus_platform.api import request_approval
from campus.iqac import aishe, compute, evidence, feedback, feedback_invites, metric_values, validation
from campus.iqac import export as exporter
from campus.iqac.access import OWNER_ROLE, ROLES
from campus.iqac.feedback import MINIMUM_GROUP_DEFAULT, MINIMUM_GROUP_FLOOR  # noqa: F401  (public API: Campus Settings)
from campus.iqac import cycle as lifecycle
from campus.iqac import framework as framework_lifecycle


@frappe.whitelist(methods=["POST"])
def compute_cycle(cycle):
	"""Compute all formula metrics of an Accreditation Cycle (IQAC Coordinator / System Manager); returns Metric Value names."""
	frappe.only_for(ROLES)
	return compute.compute_cycle(cycle)


@frappe.whitelist(methods=["POST"])
def compute_all(cycle):
	"""Compute all formula metrics as a background bulk run; returns the Bulk Run name."""
	return compute.compute_all(cycle)


@frappe.whitelist(methods=["POST"])
def advance_cycle(cycle_name, comment=None):
	"""Collecting -> Validating -> IQAC Review, and Approved -> Submitted; the step out of Validating needs no blocking
	validation failure and, with warnings, a comment."""
	lifecycle.advance(cycle_name, comment)


@frappe.whitelist(methods=["POST"])
def run_validation(cycle):
	"""Check the cycle against its framework's Validation Rules and store a Validation Run; returns its name."""
	return validation.run(cycle)


@frappe.whitelist()
def validation_counts(cycle):
	"""{blocking, warnings} failures of the cycle now."""
	return validation.summary(cycle)


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


@frappe.whitelist(methods=["POST"])
def attach_as_evidence(doctype, name, title, evidence_type, academic_year, nodes=None, is_public=0, file=None, url=None):
	"""Make an Evidence from a record of a document type listed in Campus Settings > Evidence Sources; returns its name."""
	return evidence.attach_as_evidence(doctype, name, title, evidence_type, academic_year, nodes, is_public, file, url)


@frappe.whitelist()
def evidence_source_doctypes():
	"""{document type: file field} that get the Attach as Evidence action (IQAC roles)."""
	frappe.only_for((*ROLES, OWNER_ROLE))
	rows = frappe.get_all("Evidence Source Doctype", {"parent": "Campus Settings"}, ["document_type", "file_field"])
	return {row.document_type: row.file_field or "" for row in rows}


@frappe.whitelist()
def evidence_slot_status(cycle, node=None):
	"""Filled / missing evidence slots of a node (or the whole framework) for a cycle."""
	frappe.has_permission("Accreditation Cycle", "read", cycle, throw=True)
	return evidence.slot_status(cycle, node)


@frappe.whitelist(methods=["POST"])
def export_cycle(cycle, template):
	"""Download the cycle as the Excel / PDF of an Export Template (IQAC staff and the Principal, within their company)."""
	filename, content = exporter.export(cycle, template)
	frappe.response.update({"filename": filename, "filecontent": content, "type": "download"})


@frappe.whitelist(methods=["POST"])
def export_aishe(company, academic_year, layout=None):
	"""M01-09 Download the AISHE dataset of the company and year in an AISHE Layout (IQAC staff and the Principal, within their company)."""
	filename, content = aishe.export_dataset(company, academic_year, layout)
	frappe.response.update({"filename": filename, "filecontent": content, "type": "download"})


@frappe.whitelist(methods=["POST"])
def send_feedback_invitations(campaign):
	"""M01-05 Invite the campaign's audience through messaging (bulk run); IQAC Coordinator / System Manager."""
	frappe.only_for(ROLES)
	frappe.get_doc("Feedback Campaign", campaign).check_permission("write")
	return feedback_invites.send_invitations(campaign)


def indirect_co_scores(offering):
	"""M03-03 Indirect CO attainment of a course offering from its exit-survey ratings: {CO: {responses, average (1-5),
	percent (of 5), suppressed}}; a CO with fewer responses than the Campus Settings minimum group size is suppressed."""
	return feedback.indirect_co_scores(offering)


def campaign_outcome_scores(campaign):
	"""M03-03 Indirect PO / PSO attainment from a closed programme exit survey: {tag: {responses, average, percent,
	suppressed}} of its tagged Likert answers, small groups suppressed as in indirect_co_scores."""
	return feedback.campaign_outcome_scores(campaign)
