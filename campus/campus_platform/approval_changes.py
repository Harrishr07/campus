"""M17-03 Which data fields of a document differ from its saved version (for the approval edit lock)."""

from frappe.model import no_value_fields, table_fields
from frappe.utils import cstr, flt, get_datetime_str, getdate

NUMERIC = {"Int", "Float", "Currency", "Percent", "Check", "Rating"}
SKIP = set(no_value_fields) - set(table_fields)


def changed_fields(doc, before):
	"""Fieldnames whose values differ between `doc` and `before` (None means nothing to compare)."""
	if not before:
		return []
	return [df.fieldname for df in doc.meta.fields if df.fieldtype not in SKIP and _differs(df, doc, before)]


def _differs(df, doc, before):
	if df.fieldtype in table_fields:
		return _rows(doc.get(df.fieldname)) != _rows(before.get(df.fieldname))
	return _normal(df.fieldtype, doc.get(df.fieldname)) != _normal(df.fieldtype, before.get(df.fieldname))


def _rows(rows):
	return [
		tuple(
			_normal(df.fieldtype, row.get(df.fieldname)) for df in row.meta.fields if df.fieldtype not in SKIP
		)
		for row in rows or []
	]


def _normal(fieldtype, value):
	if fieldtype in NUMERIC:
		return flt(value)
	if value in (None, ""):
		return ""
	if fieldtype == "Date":
		return getdate(value)
	if fieldtype == "Datetime":
		return get_datetime_str(value)
	return cstr(value)
