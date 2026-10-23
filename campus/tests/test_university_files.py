"""M06-10 unit tests: University Exam Format code mappings, validation, export cells and import parsing."""

import csv
import io

import frappe
from frappe.tests import UnitTestCase
from frappe.utils import cstr
from frappe.utils.xlsxutils import make_xlsx, read_xlsx_file_from_attached_file

from campus.examinations.university_files import CodeMap, build_file, parse_file, validate_format


def fmt(direction="Import", columns=None, codes=(), header_row=1):
	columns = columns or [("Reg", "University Register No"), ("Code", "Course Code"), ("Grade", "Grade")]
	return frappe._dict(
		direction=direction, file_type="CSV", header_row=header_row, date_format="dd-mm-yyyy",
		columns=[frappe._dict(idx=i, heading=h, source=s) for i, (h, s) in enumerate(columns, 1)],
		codes=[frappe._dict(idx=i, code_type=t, our_code=o, university_code=u) for i, (t, o, u) in enumerate(codes, 1)],
	)  # fmt: skip


class TestCodeMap(UnitTestCase):
	def test_an_unmapped_type_passes_codes_through(self):
		codes = CodeMap(fmt())
		self.assertEqual((codes.university("Course", "C1"), codes.ours("Grade", " A ")), ("C1", "A"))

	def test_a_mapped_type_refuses_an_unmapped_code(self):
		codes = CodeMap(fmt(codes=[("Course", "C1", "u-1")]))
		self.assertEqual((codes.university("Course", "C1"), codes.ours("Course", "U-1")), ("u-1", "C1"))
		self.assertIsNone(codes.university("Course", "C2"))
		self.assertIsNone(codes.ours("Course", "U-2"))


class TestValidateFormat(UnitTestCase):
	def test_required_columns(self):
		with self.assertRaises(frappe.ValidationError):
			validate_format(fmt(columns=[("Reg", "University Register No"), ("Code", "Course Code")]))
		validate_format(fmt())

	def test_a_column_of_the_other_direction_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			validate_format(fmt("Export", [("Reg", "University Register No"), ("Code", "Course Code"), ("G", "Grade")]))

	def test_repeated_columns_and_codes_are_refused(self):
		with self.assertRaises(frappe.ValidationError):
			validate_format(fmt(columns=[("Reg", "University Register No"), ("Code", "Course Code"), ("Grade", "Grade"), ("reg", "ESE")]))
		with self.assertRaises(frappe.ValidationError):
			validate_format(fmt(codes=[("Grade", "A", "1"), ("Grade", "B", "1")]))

	def test_a_result_code_must_be_ours(self):
		with self.assertRaises(frappe.ValidationError):
			validate_format(fmt(codes=[("Result", "Passed", "P")]))
		validate_format(fmt(codes=[("Result", "Pass", "P")]))


class TestFiles(UnitTestCase):
	def test_export_cells_cannot_run_as_formulas(self):
		export = fmt("Export", [("Reg", "University Register No"), ("Code", "Course Code"), ("Name", "Student Name"), ("CIA", "CIA")])
		_extension, content = build_file(export, [{"University Register No": "@SUM(1)", "Course Code": "-1+2", "Student Name": "=1", "CIA": 30.5}])
		lines = list(csv.reader(io.StringIO(content.decode())))
		self.assertEqual(lines, [["Reg", "Code", "Name", "CIA"], ["'@SUM(1)", "'-1+2", "'=1", "30.5"]])

	def test_import_by_heading_and_by_position(self):
		content = "grade,reg,code,extra\nA,R1,C1,x\n,,,\n".encode()
		self.assertEqual(parse_file(fmt(), "f.csv", content), [(2, {"Grade": "A", "University Register No": "R1", "Course Code": "C1"})])
		self.assertEqual(
			parse_file(fmt(header_row=0), "f.csv", b"R1,C1,A\n"), [(1, {"University Register No": "R1", "Course Code": "C1", "Grade": "A"})]
		)

	def test_an_xlsx_export_reads_back_formula_safe(self):
		export = fmt("Export", [("Reg", "University Register No"), ("Code", "Course Code"), ("Name", "Student Name")])
		export.file_type = "XLSX"
		extension, content = build_file(export, [{"University Register No": "U1", "Course Code": "C1", "Student Name": "=1+1"}])
		self.assertEqual(extension, "xlsx")
		rows = [[cstr(c) for c in row] for row in read_xlsx_file_from_attached_file(fcontent=content)]
		self.assertEqual(rows, [["Reg", "Code", "Name"], ["U1", "C1", "'=1+1"]])

	def test_import_reads_an_xlsx_file(self):
		content = make_xlsx([["Reg", "Code", "Grade"], ["R1", "C1", "A"], [None, None, None]], "Results").getvalue()
		self.assertEqual(parse_file(fmt(), "results.XLSX", content), [(2, {"University Register No": "R1", "Course Code": "C1", "Grade": "A"})])

	def test_a_missing_required_heading_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			parse_file(fmt(), "f.csv", b"reg,code\nR1,C1\n")
