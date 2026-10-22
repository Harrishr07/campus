"""M08-01 ISSN check: format NNNN-NNNC with the ISO 3297 mod-11 check digit."""

import re

import frappe
from frappe import _

ISSN_PATTERN = re.compile(r"^(\d{7})([\dX])$")


def normalise_issn(value):
	"""Return the ISSN as NNNN-NNNC (upper-case X), or throw when its form or check digit is wrong."""
	compact = (value or "").strip().upper().replace("-", "")
	match = ISSN_PATTERN.match(compact)
	if not match or check_digit(match.group(1)) != match.group(2):
		frappe.throw(_("{0} is not a valid ISSN.").format(value))
	return f"{compact[:4]}-{compact[4:]}"


def check_digit(digits):
	remainder = -sum(int(d) * weight for d, weight in zip(digits, range(8, 1, -1), strict=True)) % 11
	return "X" if remainder == 10 else str(remainder)
