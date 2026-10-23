"""M06-10 University Exam Format files: the code mappings, writing an export file and reading an import file.

A format lists its columns in file order (heading -> one of our sources) and its code mappings by type (Course,
Grade, Result, Registration Type). A code type with no rows passes codes through unchanged; once a type has a row,
every code of that type must be mapped (an unmapped one is refused, never guessed). Every exported cell goes through
graduation_rules.csv_cell, so no cell can run as a spreadsheet formula; dates follow the format's date format.
"""

import csv
import io

import frappe
from frappe import _
from frappe.utils import cstr, getdate
from openpyxl import Workbook

from campus.examinations.graduation_rules import csv_cell

EXPORT_SOURCES = (
	"University Register No", "Register No", "Student Name", "Date of Birth", "Program", "Course Code", "Course Name",
	"Registration Type", "CIA", "CIA Max", "Exam Session",
)  # fmt: skip
IMPORT_SOURCES = ("University Register No", "Course Code", "Grade", "Result", "CIA", "ESE", "Total")
REQUIRED = {"Export": ("University Register No", "Course Code"), "Import": ("University Register No", "Course Code", "Grade")}
SOURCES = {"Export": EXPORT_SOURCES, "Import": IMPORT_SOURCES}
DATE_FORMATS = {"dd-mm-yyyy": "%d-%m-%Y", "yyyy-mm-dd": "%Y-%m-%d", "dd/mm/yyyy": "%d/%m/%Y", "mm/dd/yyyy": "%m/%d/%Y"}
RESULT_CODES = ("Pass", "Fail", "AB", "SA", "WD")
CODE_TYPES = ("Course", "Grade", "Result", "Registration Type")


class CodeMap:
	"""The code mappings of one format: ours -> the university's (export) and back (import)."""

	def __init__(self, fmt):
		self.to_university, self.to_ours = {t: {} for t in CODE_TYPES}, {t: {} for t in CODE_TYPES}
		for row in fmt.codes:
			self.to_university[row.code_type][row.our_code] = row.university_code
			self.to_ours[row.code_type][row.university_code.strip().upper()] = row.our_code

	def university(self, code_type, ours):
		"""The university's code of `ours`; None when the type is mapped and `ours` is not."""
		mapped = self.to_university[code_type]
		return mapped.get(ours) if mapped else ours

	def ours(self, code_type, university):
		"""Our code of the university's `university`; None when the type is mapped and the code is not."""
		mapped = self.to_ours[code_type]
		return mapped.get(cstr(university).strip().upper()) if mapped else cstr(university).strip()


def format_for(name, direction, company):
	"""The University Exam Format `name` ({direction, university}); refused unless it is a `direction` format of
	`company` or a shared one."""
	fmt = frappe.db.get_value("University Exam Format", name, ["direction", "university", "company"], as_dict=True)
	if fmt.direction != direction:
		frappe.throw(_("{0} is not an {1} format.").format(frappe.bold(name), _(direction)))
	if fmt.company and fmt.company != company:
		frappe.throw(_("{0} is the format of {1}.").format(frappe.bold(name), frappe.bold(fmt.company)))
	return fmt


def validate_format(fmt):
	"""Refuse a format whose columns or code mappings cannot be used for its direction."""
	allowed = SOURCES[fmt.direction]
	sources = [row.source for row in fmt.columns]
	wrong = sorted({s for s in sources if s not in allowed})
	if wrong:
		frappe.throw(_("These columns cannot be used in an {0} format: {1}.").format(_(fmt.direction), ", ".join(wrong)))
	for label, values in ((_("column"), sources), (_("heading"), [cstr(row.heading).strip().lower() for row in fmt.columns])):
		repeated = sorted({v for v in values if values.count(v) > 1})
		if repeated:
			frappe.throw(_("Each {0} may appear once: {1}.").format(label, ", ".join(repeated)))
	missing = [s for s in REQUIRED[fmt.direction] if s not in sources]
	if missing:
		frappe.throw(_("An {0} format needs the columns {1}.").format(_(fmt.direction), ", ".join(missing)))
	seen = set()
	for row in fmt.codes:
		for key in ((row.code_type, "ours", row.our_code), (row.code_type, "university", row.university_code.strip().upper())):
			if key in seen:
				frappe.throw(_("Code mapping row {0}: {1} {2} is mapped twice.").format(row.idx, _(row.code_type), frappe.bold(key[2])))
			seen.add(key)
		if row.code_type == "Result" and row.our_code not in RESULT_CODES:
			frappe.throw(_("Code mapping row {0}: our result code is one of {1}.").format(row.idx, ", ".join(RESULT_CODES)))


def date_text(value, fmt):
	return getdate(value).strftime(DATE_FORMATS.get(fmt.date_format) or DATE_FORMATS["dd-mm-yyyy"]) if value else ""


def build_file(fmt, records):
	"""(extension, content bytes) of `records` ([{source: value}]) in the format's columns; cells formula-safe."""
	columns = [(row.heading, row.source) for row in fmt.columns]
	lines = [[csv_cell(heading) for heading, _source in columns]] if fmt.header_row else []
	lines += [[csv_cell(record.get(source)) for _heading, source in columns] for record in records]
	if fmt.file_type == "XLSX":
		book = Workbook()
		sheet = book.active
		for line in lines:
			sheet.append(line)
		out = io.BytesIO()
		book.save(out)
		return "xlsx", out.getvalue()
	out = io.StringIO()
	csv.writer(out).writerows(lines)
	return "csv", out.getvalue().encode("utf-8")


def parse_file(fmt, file_url, content):
	"""[(file row no, {source: text})] of the data rows of an import file in the format."""
	if cstr(file_url).lower().endswith(".xlsx"):
		from frappe.utils.xlsxutils import read_xlsx_file_from_attached_file

		rows = [[cstr(c).strip() for c in row] for row in read_xlsx_file_from_attached_file(fcontent=content)]
	else:
		text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
		rows = [[cstr(c).strip() for c in row] for row in csv.reader(io.StringIO(text))]
	if not rows:
		frappe.throw(_("The result file is empty."))
	columns = [(cstr(row.heading).strip().lower(), row.source) for row in fmt.columns]
	if fmt.header_row:
		header = [cell.lower() for cell in rows[0]]
		missing = [heading for heading, source in columns if source in REQUIRED["Import"] and heading not in header]
		if missing:
			frappe.throw(_("The result file is missing the columns: {0}.").format(", ".join(missing)))
		positions = {source: header.index(heading) for heading, source in columns if heading in header}
		data, first = rows[1:], 2
	else:
		positions = {source: index for index, (_heading, source) in enumerate(columns)}
		data, first = rows, 1
	records = []
	for row_no, cells in enumerate(data, start=first):
		if any(cells):
			records.append((row_no, {source: cells[i] for source, i in positions.items() if i < len(cells) and cells[i]}))
	return records
