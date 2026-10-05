"""M09-02 Configurable number formats for bank challans and fee receipts.

A prefix may use {abbr} (company abbreviation), {yy} and {yyyy} (year of the document date); the running
counter is a Frappe naming series (row-locked), so numbers never repeat.
"""

import re

import frappe
from frappe import _
from frappe.model.naming import getseries
from frappe.utils import getdate

PLACEHOLDERS = {"abbr", "yy", "yyyy"}


def validate_prefix(prefix):
	unknown = set(re.findall(r"{(\w*)}", prefix or "")) - PLACEHOLDERS
	if unknown:
		frappe.throw(_("Unknown placeholder {0} in {1}.").format(", ".join(sorted(unknown)), prefix))


def render_prefix(prefix, company, date):
	year = getdate(date).year
	abbr = frappe.get_cached_value("Company", company, "abbr")
	return prefix.format(abbr=abbr, yy=str(year)[-2:], yyyy=year)


def next_number(prefix, digits, company, date):
	"""The next number of the series `prefix` renders to for `company` on `date`."""
	rendered = render_prefix(prefix, company, date)
	return rendered + getseries(rendered, digits)
