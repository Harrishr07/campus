"""M01-02 / M01-03 Metric Value rules: the effective value, word count, verify / reopen and the source-changed check.

Status: Draft (no engine value yet, or a hand answer awaiting verification), Computed (engine value), Verified (an owner
stands behind it), Locked (cycle approved). Verified and Locked values are never overwritten by a recompute: if the data
behind them moved, `source_changed` and the new value are shown beside them instead.
"""

import html
import json
import re

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

FROZEN = ("Verified", "Locked")
TAGS = re.compile(r"<[^>]*>")


def effective_value(has_formula, computed, manual, override_approved):
	"""The value the cycle stands behind: the computed one, replaced by the manual one only through an approved override;
	a node without a formula has only the manual one."""
	if not has_formula or override_approved:
		return manual
	return computed


def count_words(text):
	"""Words of a rich-text answer, markup and entities ignored."""
	return len(html.unescape(TAGS.sub(" ", text or "")).split())


def verify(name):
	"""Mark a Draft or Computed value that has an answer as Verified."""
	metric = frappe.get_doc("Metric Value", name, for_update=True)
	metric.check_permission("write")
	if metric.status in FROZEN:
		frappe.throw(_("{0} is already {1}.").format(frappe.bold(name), _(metric.status)))
	if not metric.answered:
		frappe.throw(_("{0} has no answer to verify.").format(frappe.bold(name)))
	set_status(metric, "Verified")
	metric.update({"verified_by": frappe.session.user, "verified_on": now_datetime()})
	metric.flags.engine_write = True
	metric.save()


def reopen(name):
	"""Take a Verified value back to Draft so it can change again (a Locked value cannot be reopened)."""
	metric = frappe.get_doc("Metric Value", name, for_update=True)
	metric.check_permission("write")
	if metric.status != "Verified":
		frappe.throw(_("{0} is {1}; only a Verified value can be reopened.").format(frappe.bold(name), _(metric.status)))
	set_status(metric, "Draft")
	metric.update({"verified_by": None, "verified_on": None})
	metric.flags.engine_write = True
	metric.save()


def set_status(metric, status):
	metric.flags.status_change = True
	metric.status = status


def note_source_change(metric, value, inputs):
	"""A recompute met a Verified or Locked value: leave it, and record whether its source moved."""
	changed = flt(value, 2) != flt(metric.computed_value, 2) or signature(inputs) != signature(
		json.loads(metric.snapshot or "{}").get("inputs", {})
	)
	frappe.db.set_value(
		"Metric Value", metric.name, {"source_changed": int(changed), "recomputed_value": value if changed else None}
	)


def signature(inputs):
	"""Values and record names of snapshot inputs, comparable after a JSON round trip."""
	inputs = json.loads(json.dumps(inputs))
	return {key: (point["value"], sorted(record["name"] for record in point["records"])) for key, point in inputs.items()}
