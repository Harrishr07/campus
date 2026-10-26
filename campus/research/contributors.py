"""M08-11 / M08-12 People on an IPR or a publication: each row is an Employee, a Student or an external person.
Inventors and authors share this check; the rows differ only in the names of their type and name fields."""

import frappe
from frappe import _

COMPANY_FIELD = {"Employee": "company", "Student": "oc_company"}
KINDS = {
	"Employee": ("employee", "Employee", "employee_name"),
	"Student": ("student", "Student", "student_name"),
}


def validate_contributors(rows, type_field, name_field, label, company):
	"""Throw unless there is at least one row, each row names its person (an external one by name), and nobody is listed twice.
	Employees and Students must belong to `company`. Fills the name of an Employee / Student row from the record and clears the link of the other kinds."""
	if not rows:
		frappe.throw(_("Add at least one {0}.").format(label))
	seen = set()
	for row in rows:
		kind = row.get(type_field)
		for link_field, _doctype, _name in KINDS.values():
			if KINDS.get(kind, (None,))[0] != link_field:
				row.set(link_field, None)
		if kind in KINDS:
			link_field, doctype, source = KINDS[kind]
			if not row.get(link_field):
				frappe.throw(_("Row {0}: choose the {1}.").format(row.idx, _(doctype)))
			person = frappe.db.get_value(
				doctype, row.get(link_field), [source, COMPANY_FIELD[doctype]], as_dict=True
			)
			if person[COMPANY_FIELD[doctype]] != company:
				frappe.throw(
					_("Row {0}: {1} does not belong to {2}.").format(row.idx, row.get(link_field), company)
				)
			row.set(name_field, person[source])
			key = (kind, row.get(link_field))
		else:
			if not (row.get(name_field) or "").strip():
				frappe.throw(_("Row {0}: enter the name of the {1}.").format(row.idx, label))
			key = (kind, row.get(name_field).strip().lower())
		if key in seen:
			frappe.throw(_("Row {0}: {1} is listed more than once.").format(row.idx, row.get(name_field)))
		seen.add(key)
