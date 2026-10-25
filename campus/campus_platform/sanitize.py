"""Universal data sanitization utilities and doc_events hooks for OneBook Campus."""

import re

try:
	import frappe
except ImportError:
	frappe = None


MOBILE_FIELDS = {
	"Student": ["student_mobile_number"],
	"Student Applicant": ["student_mobile_number"],
	"Guardian": ["mobile_number"],
	"Student Attendance": ["student_mobile_number"],
}


def clean_mobile_number(val):
	"""BUG-08: Normalizes a mobile number to a clean digits string without floating-point artifacts (.0).

	Handles:
	- None / empty string -> ''
	- float (e.g. 6380168782.0) -> '6380168782'
	- string with float suffix ('6380168782.0') -> '6380168782'
	- string with spaces / hyphens ('63801 68782') -> '6380168782'
	- international prefix ('+919876543210.0') -> '+919876543210'
	"""
	if val is None:
		return ""

	if isinstance(val, float):
		if val.is_integer():
			val = int(val)
		else:
			return ""

	val_str = str(val).strip()
	if not val_str:
		return ""

	# Strip Excel float suffix (.0, .00)
	if val_str.endswith(".0"):
		val_str = val_str[:-2].strip()
	val_str = re.sub(r"\.0+$", "", val_str)

	# Preserve leading + if international format
	has_plus = val_str.startswith("+")

	# Strip non-digits
	digits = re.sub(r"[^\d]", "", val_str)
	if not digits:
		return ""

	return f"+{digits}" if has_plus else digits


def validate_mobile(doc, method=None):
	"""Doc event hook on validate: ensures mobile number fields are clean before saving."""
	fields = MOBILE_FIELDS.get(doc.doctype) or []
	for fieldname in fields:
		if doc.meta.has_field(fieldname):
			val = doc.get(fieldname)
			if val:
				cleaned = clean_mobile_number(val)
				if cleaned != val:
					doc.set(fieldname, cleaned)
