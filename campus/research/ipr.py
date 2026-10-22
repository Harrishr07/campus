"""M08-11 IPR rules: the patent lifecycle (Filed, Published, Examined, Granted, Licensed) and how licence revenue is shared.
Pure functions; the Patent controller applies them."""

import frappe
from frappe import _
from frappe.utils import flt, getdate

STAGES = ("Filed", "Published", "Examined", "Granted", "Licensed")
STAGE_DATES = {"Filed": "filed_date", "Published": "published_date", "Examined": "examined_date", "Granted": "granted_date"}
LICENSABLE = ("Granted", "Licensed")


def check_lifecycle(status, dates, before_status=None, today=None):
	"""Throw unless `status` is not a step back from `before_status`, has the date of its stage (Licensed: the grant date),
	no date belongs to a stage not yet reached, dates are not in the future and the dates run in stage order.
	`dates` maps a date field to its value."""
	if before_status and STAGES.index(status) < STAGES.index(before_status):
		frappe.throw(_("A patent can't go back from {0} to {1}.").format(_(before_status), _(status)))
	stage = "Granted" if status == "Licensed" else status
	reached = STAGES.index(stage)
	previous = None
	for name in STAGES[: STAGES.index("Licensed")]:
		field, value = STAGE_DATES[name], dates.get(STAGE_DATES[name])
		if STAGES.index(name) == reached and not value:
			frappe.throw(_("Enter the {0} date for a patent that is {1}.").format(_(name).lower(), _(status).lower()))
		if value and STAGES.index(name) > reached:
			frappe.throw(_("The {0} date can't be set while the patent is {1}.").format(_(name).lower(), _(status).lower()))
		if not value:
			continue
		if today and getdate(value) > getdate(today):
			frappe.throw(_("The {0} date can't be in the future.").format(_(name).lower()))
		if previous and getdate(value) < getdate(previous):
			frappe.throw(_("The {0} date can't be before an earlier stage's date.").format(_(name).lower()))
		previous = value


def split_revenue(amount, institution_percent):
	"""(institution amount, inventors' amount) of licence revenue `amount`; rounding goes to the institution."""
	inventors = flt(flt(amount) * (100 - flt(institution_percent)) / 100, 2)
	return flt(flt(amount) - inventors, 2), inventors


def split_among(total, percents):
	"""`total` divided by `percents` (summing to 100); the last person takes the rounding remainder."""
	shares = [flt(total * flt(p) / 100, 2) for p in percents]
	if shares:
		shares[-1] = flt(total - sum(shares[:-1]), 2)
	return shares


def default_shares(count):
	"""Equal percentages for `count` people that sum to 100 exactly."""
	each = flt(100 / count, 2)
	return [each] * (count - 1) + [flt(100 - each * (count - 1), 2)]
