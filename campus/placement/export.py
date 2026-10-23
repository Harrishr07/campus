"""M14-02 Round result files: the registered-students template (CSV a spreadsheet will not run as a formula) and the
reader of an uploaded CSV / XLSX of results."""

import csv
import io
import re

import frappe
from frappe import _
from frappe.utils import cstr

FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
MAX_CELL = 32000
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000
HEADER = ["Student", "Student Name", "Result", "Remarks"]


def results():
	"""The result values a round row may hold: the options of Round Result Student.result."""
	return [o for o in frappe.get_meta("Round Result Student").get_field("result").options.split("\n") if o]


def safe_cell(value):
	"""`value` as cell text a spreadsheet will not run as a formula: control characters dropped, length capped, and text
	starting (after spaces) with = + - @ tab or CR gets a leading apostrophe."""
	text = CONTROL.sub("", "" if value is None else cstr(value))[:MAX_CELL]
	if text.lstrip(" ")[:1] in FORMULA_STARTS and text.lstrip(" "):
		return "'" + text
	return text


def template_rows(round_result):
	"""Header plus one row per registered student of the round's drive, with the round's current result if any."""
	drive = frappe.db.get_value("Round Result", round_result, "drive")
	current = {
		row.student: row
		for row in frappe.get_all("Round Result Student", {"parent": round_result}, ["student", "result", "remarks"], limit=0)
	}
	students = frappe.get_all("Drive Registration", {"drive": drive, "status": "Registered"}, ["student", "student_name"], order_by="student", limit=0)
	rows = [list(HEADER)]
	for student in students:
		now = current.get(student.student)
		rows.append([safe_cell(student.student), safe_cell(student.student_name), safe_cell(now.result if now else ""), safe_cell(now.remarks if now else "")])
	return rows


def read_rows(file_url):
	"""[(row number, student, result, remarks)] of the CSV or XLSX attached at `file_url`; the user must be able to read the File."""
	name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not name:
		frappe.throw(_("The results file {0} was not found.").format(file_url))
	file = frappe.get_doc("File", name)
	file.check_permission("read")
	content = file.get_content()
	content = content.encode() if isinstance(content, str) else content
	if len(content) > MAX_BYTES:
		frappe.throw(_("The results file is larger than {0} MB").format(MAX_BYTES // (1024 * 1024)))
	if file.file_name.lower().endswith(".xlsx"):
		from frappe.utils.xlsxutils import read_xlsx_file_from_attached_file

		table = [[cstr(c).strip() for c in row] for row in read_xlsx_file_from_attached_file(fcontent=content)]
	else:
		table = [[cstr(c).strip() for c in row] for row in csv.reader(io.StringIO(decode(content)))]
	return parse_table(table)


def decode(content):
	"""Text of a CSV: UTF-8 (with or without BOM), else Windows-1252 as Excel saves it."""
	try:
		return content.decode("utf-8-sig")
	except UnicodeDecodeError:
		return content.decode("cp1252", errors="replace")


def parse_table(table):
	"""Data rows of a results table (header first) as (row number, student, result, remarks)."""
	if not table:
		frappe.throw(_("The results file is empty."))
	header = [h.lower() for h in table[0]]
	for column in ("student", "result"):
		if column not in header:
			frappe.throw(_("The results file needs a {0} column.").format(column.title()))
	index = {column: header.index(column) for column in ("student", "result", "remarks") if column in header}
	if len(table) - 1 > MAX_ROWS:
		frappe.throw(_("A results file can hold at most {0} rows").format(MAX_ROWS))
	rows = []
	for number, cells in enumerate(table[1:], start=2):
		if not any(cells):
			continue
		cell = lambda key: cells[index[key]] if key in index and index[key] < len(cells) else ""  # noqa: E731
		rows.append((number, cell("student"), cell("result"), cell("remarks")))
	return rows
