"""M17-07 (partial) Initial data import: Data Import templates and a pre-import validator.

No new DocType: the load itself is Frappe's Data Import. `TEMPLATES` is the documented column map of each
sheet; `download_import_template` hands out the stock Data Import template for it (CSV or Excel), so the
header labels are exactly what the importer matches. A multi-row sheet follows the stock convention: a
child-table row (a second guardian, a second curriculum course) sits on the following line with the parent
cells blank.

Sheets and the order to load them
1. Programs, Courses, Employees, Instructors, then Curriculum Rows (Curriculum plus its courses).
2. Students: Register No, name, e-mail, Company, Batch, Regulation, Aadhaar and the Guardians rows. The
   Guardian masters must exist (Guardian is imported on its own or created at enquiry).
3. Student Enrolments: Program Enrollment rows carrying the Category and the Admission Quota. The Student
   column holds the Student ID that step 2 created (export the Students list to look it up).
4. Opening Fee Balances: Sales Invoices flagged Is Opening = Yes, one line per balance, income account the
   Temporary Opening account. A Data Import of Sales Invoice is thinner than the Opening Invoice Creation
   Tool, which cannot carry the student link (`student`).

`validate_import` (and the Import Check report over it) reads the file of a Data Import without importing
anything and lists, per sheet row: masters (Link values) that do not exist, required cells that are empty
(guardian, quota, category, regulation...), Aadhaar numbers failing the Verhoeff checksum, register numbers
repeated in the file or already on a Student, and rows of another company. Aadhaar values are never
echoed: messages carry only the masked number (last four digits).

Data Import itself refuses a whole file whose Link cells name a missing master, so fix those first; a row
failing on its own (bad Aadhaar, repeated register number) fails alone and the rest go in. Curriculum is the
one campus DocType here and allows import for System Manager and Dean Academics.

Idempotency: `Student.oc_register_no` is unique. Importing a sheet again cannot create a second Student: a
row whose register number is already stored fails alone, and the validator lists it as "already imported" so
it can be taken out of the file; the fixed rows go in.

The 500-row run: validate the legacy sheet, fix the flagged rows, import (Insert New Records), and import the
fixed rows again; the Student count equals the number of distinct register numbers.
"""

import frappe
from frappe import _
from frappe.core.doctype.data_import.data_import import download_template
from frappe.core.doctype.data_import.exporter import Exporter
from frappe.utils import cstr
from frappe.utils.csvutils import read_csv_content
from frappe.utils.xlsxutils import read_xlsx_file_from_attached_file

from campus.admissions.aadhaar import AADHAAR_FIELD, is_valid_aadhaar, mask
from campus.campus_platform.company_scope import permitted_companies

REGISTER_FIELD = "oc_register_no"
COMPANY_FIELDS = ("oc_company", "company")

TEMPLATES = {
	"Programs": {
		"doctype": "Program",
		"fields": {
			"Program": [
				"program_name",
				"program_abbreviation",
				"department",
				"oc_company",
				"oc_level",
				"oc_degree",
				"oc_discipline",
				"oc_duration_years",
				"oc_total_semesters",
				"oc_sanctioned_intake",
			]
		},
		"required": ["program_name", "oc_company"],
	},
	"Courses": {
		"doctype": "Course",
		"fields": {
			"Course": [
				"course_name",
				"department",
				"oc_company",
				"oc_course_code",
				"oc_course_type",
				"oc_lecture_hours",
				"oc_tutorial_hours",
				"oc_practical_hours",
				"oc_credits",
			]
		},
		"required": ["course_name", "oc_company"],
	},
	"Curriculum Rows": {
		"doctype": "Curriculum",
		"fields": {
			"Curriculum": ["program", "regulation", "version", "status", "company"],
			"courses": [
				"semester",
				"course",
				"category",
				"credits",
				"is_elective",
				"exam_type",
				"cia_max",
				"ese_max",
			],
		},
		"required": ["program", "regulation", "status", "company", "course", "semester", "category"],
	},
	"Students": {
		"doctype": "Student",
		"fields": {
			"Student": [
				REGISTER_FIELD,
				"first_name",
				"middle_name",
				"last_name",
				"student_email_id",
				"student_mobile_number",
				"date_of_birth",
				"gender",
				"joining_date",
				"oc_company",
				"oc_batch",
				"oc_regulation",
				AADHAAR_FIELD,
				"address_line_1",
				"city",
				"state",
				"pincode",
			],
			"guardians": ["guardian", "guardian_name", "relation"],
		},
		"required": [
			REGISTER_FIELD,
			"first_name",
			"student_email_id",
			"oc_company",
			"oc_regulation",
			"guardian",
		],
	},
	"Student Enrolments": {
		"doctype": "Program Enrollment",
		"fields": {
			"Program Enrollment": [
				"student",
				"program",
				"academic_year",
				"enrollment_date",
				"student_category",
				"oc_admission_quota",
				"oc_company",
			]
		},
		"required": [
			"student",
			"program",
			"academic_year",
			"student_category",
			"oc_admission_quota",
			"oc_company",
		],
	},
	"Employees": {
		"doctype": "Employee",
		"fields": {
			"Employee": [
				"employee_number",
				"first_name",
				"last_name",
				"gender",
				"date_of_birth",
				"date_of_joining",
				"company",
				"department",
				"designation",
				"status",
				"cell_number",
				"personal_email",
			]
		},
		"required": ["first_name", "gender", "date_of_birth", "date_of_joining", "company", "status"],
	},
	"Instructors": {
		"doctype": "Instructor",
		"fields": {"Instructor": ["instructor_name", "employee", "department", "status", "gender"]},
		"required": ["instructor_name", "employee"],
	},
	"Opening Fee Balances": {
		"doctype": "Sales Invoice",
		"fields": {
			"Sales Invoice": [
				"customer",
				"student",
				"company",
				"posting_date",
				"due_date",
				"is_opening",
				"debit_to",
				"set_posting_time",
			],
			"items": ["item_code", "qty", "rate", "income_account", "cost_center"],
		},
		"required": [
			"customer",
			"student",
			"company",
			"posting_date",
			"is_opening",
			"item_code",
			"rate",
			"income_account",
		],
	},
}


@frappe.whitelist()
def download_import_template(template: str, file_type: str = "CSV"):
	"""Respond with the blank Data Import template of one sheet."""
	spec = template_spec(template)
	return download_template(spec["doctype"], spec["fields"], "blank_template", file_type)


@frappe.whitelist()
def validate_import(data_import: str, template: str, company: str):
	"""Issues of the file attached to a Data Import, without importing it: [{row, column, check, message}]."""
	permitted = permitted_companies(frappe.session.user)
	if permitted is not None and company not in permitted:
		frappe.throw(
			_("You are not permitted to check imports for company {0}.").format(company),
			frappe.PermissionError,
		)
	frappe.has_permission("Data Import", "read", data_import, throw=True)
	spec = template_spec(template)
	doc = frappe.get_doc("Data Import", data_import)
	if doc.reference_doctype != spec["doctype"]:
		frappe.throw(
			_("Data Import {0} is for {1}, not {2}.").format(
				data_import, doc.reference_doctype, spec["doctype"]
			)
		)
	return validate_rows(template, read_rows(doc.import_file), company)


def template_spec(template):
	if template not in TEMPLATES:
		frappe.throw(_("Unknown import template {0}.").format(template))
	return TEMPLATES[template]


def read_rows(file_url):
	content = frappe.get_doc("File", {"file_url": file_url}).get_content()
	if file_url.lower().endswith(".xlsx"):
		return read_xlsx_file_from_attached_file(fcontent=content, read_only=True)
	return read_csv_content(content)


def template_columns(template):
	"""[{label, fieldname, link, child}] in template order, as the stock exporter labels them."""
	spec = template_spec(template)
	exporter = Exporter(spec["doctype"], export_fields=spec["fields"], export_data=False)
	return [
		{"label": label, "fieldname": df.fieldname, "link": df.options if df.fieldtype == "Link" else None,
			"child": bool(df.is_child_table_field)}
		for label, df in zip(exporter.csv_array[0], exporter.fields, strict=True)
	]  # fmt: skip


def validate_rows(template, rows, company):
	"""Issues of `rows` (header first, sheet rows numbered from 1) against the template, sorted by row."""
	columns = template_columns(template)
	by_label = {c["label"].strip().lower(): c for c in columns}
	issues = []
	header = [by_label.get(cstr(cell).strip().lower()) for cell in rows[0]] if rows else []
	for index, cell in enumerate(rows[0] if rows else []):
		if header[index] is None and cstr(cell).strip():
			issues.append(
				issue(1, cell, "unknown_column", _("Column is not in the {0} template.").format(template))
			)
	present = {c["fieldname"] for c in header if c}
	for fieldname in template_spec(template)["required"]:
		if fieldname not in present:
			issues.append(
				issue(1, fieldname, "missing_column", _("Required column {0} is absent.").format(fieldname))
			)
	records = group_records(rows[1:], header)
	checks = RowChecks(template, company, records)
	for record in records:
		issues += checks.run(record)
	return sorted(issues + checks.masters(), key=lambda i: (i["row"], i["column"]))


def group_records(body, header):
	"""[{row, values: {fieldname: [cell...]}}]: a row starts a record when any parent cell is filled."""
	records = []
	for offset, cells in enumerate(body, start=2):
		starts = any(
			cstr(c).strip() for c, col in zip(cells, header, strict=False) if col and not col["child"]
		)
		if starts or not records:
			records.append({"row": offset, "values": {}, "link_cells": []})
		record = records[-1]
		for cell, col in zip(cells, header, strict=False):
			text = cell_text(cell)
			if col and text:
				record["values"].setdefault(col["fieldname"], []).append(text)
				if col["link"]:
					record["link_cells"].append((offset, col, text))
	return records


def cell_text(cell):
	"""Cell as text: spreadsheets hand numbers back as floats (an Aadhaar or register number as 1.23e11)."""
	if isinstance(cell, float) and cell.is_integer():
		cell = int(cell)
	return cstr(cell).strip()


def issue(row, column, check, message):
	return {"row": row, "column": cstr(column), "check": check, "message": message}


class RowChecks:
	def __init__(self, template, company, records):
		self.spec = template_spec(template)
		self.company = company
		self.columns = {c["fieldname"]: c for c in template_columns(template)}
		self.link_cells = [cell for record in records for cell in record["link_cells"]]
		self.register_rows = {}
		self.stored_registers = self.stored_register_numbers(records)

	def stored_register_numbers(self, records):
		numbers = {v for r in records for v in r["values"].get(REGISTER_FIELD, [])}
		if not numbers or self.spec["doctype"] != "Student":
			return set()
		return set(frappe.get_all("Student", {REGISTER_FIELD: ["in", list(numbers)]}, pluck=REGISTER_FIELD))

	def run(self, record):
		found = (
			self.required(record) + self.aadhaar(record) + self.register(record) + self.other_company(record)
		)
		return found

	def required(self, record):
		return [
			issue(record["row"], self.columns[f]["label"], "missing_value", _("{0} is required.").format(self.columns[f]["label"]))
			for f in self.spec["required"]
			if f in self.columns and f not in record["values"]
		]  # fmt: skip

	def aadhaar(self, record):
		return [
			issue(record["row"], self.columns[AADHAAR_FIELD]["label"], "bad_aadhaar",
				_("Aadhaar {0} fails the checksum or format.").format(mask(number)))
			for number in record["values"].get(AADHAAR_FIELD, [])
			if not is_valid_aadhaar(number)
		]  # fmt: skip

	def register(self, record):
		found = []
		for number in record["values"].get(REGISTER_FIELD, []):
			label = self.columns[REGISTER_FIELD]["label"]
			if number in self.register_rows:
				found.append(issue(record["row"], label, "duplicate_in_file",
					_("Register No {0} is also on row {1}.").format(number, self.register_rows[number])))  # fmt: skip
			else:
				self.register_rows[number] = record["row"]
			if number in self.stored_registers:
				found.append(issue(record["row"], label, "already_imported",
					_("Register No {0} already belongs to a Student; this row would fail and create no duplicate.").format(number)))  # fmt: skip
		return found

	def other_company(self, record):
		found = []
		for fieldname in COMPANY_FIELDS:
			for value in record["values"].get(fieldname, []):
				if value != self.company and fieldname in self.columns:
					found.append(issue(record["row"], self.columns[fieldname]["label"], "other_company",
						_("Row belongs to company {0}, not {1}.").format(value, self.company)))  # fmt: skip
		return found

	def masters(self):
		"""One lookup per linked doctype for all values, then an issue per cell whose value is missing."""
		values = {}
		for _row, col, text in self.link_cells:
			values.setdefault(col["link"], set()).add(text)
		known = {
			doctype: set(frappe.get_all(doctype, {"name": ["in", list(names)]}, pluck="name"))
			for doctype, names in values.items()
		}
		return [
			issue(row, col["label"], "missing_master", _("{0} {1} does not exist.").format(_(col["link"]), text))
			for row, col, text in self.link_cells
			if text not in known[col["link"]]
		]  # fmt: skip
