"""M06-10 integration tests: Affiliated mode - the mode switch, the university registration export and the result
import (row validation, results the transcripts and arrears read, idempotency, corrections, company scope)."""

import csv
import io
from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from campus.campus_platform import bulk
from campus.examinations import arrears, publication, registration, results, university_export, university_import
from campus.examinations.affiliation import AFFILIATED, examination_mode
from campus.tests.factories import make_company, make_user
from campus.tests.test_results import COE_USER, COLLEGE, PROGRAM, ExamFixture, enter_marks

OTHER_COLLEGE = "Affiliated Other College"
OTHER_COE = "affiliated-other-coe@example.com"
EXPORT_FORMAT, IMPORT_FORMAT = "Test Univ Export", "Test Univ Import"
COURSE_CODES = {"EXM TH": "U-TH", "EXM LB": "U-LB", "EXM TL": "U-TL"}  # EXM FA has no university code
INJECTION = "=cmd|' /C calc'!A0"


def make_format(name, direction, columns, header_row=1):
	if frappe.db.exists("University Exam Format", name):
		frappe.delete_doc("University Exam Format", name, force=True)
	return frappe.get_doc(
		{
			"doctype": "University Exam Format", "format_name": name, "university": "Test University", "direction": direction,
			"file_type": "CSV", "header_row": header_row, "columns": [{"heading": h, "source": s} for h, s in columns],
			"codes": [{"code_type": "Course", "our_code": ours, "university_code": theirs} for ours, theirs in COURSE_CODES.items()],
		}
	).insert()  # fmt: skip


def csv_bytes(rows):
	out = io.StringIO()
	csv.writer(out).writerows(rows)
	return out.getvalue().encode()


class AffiliatedFixture(ExamFixture):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		rule_set = frappe.db.get_value("Exam Rule Set", {"regulation": ["like", "R2022-EXM%"]})
		frappe.db.set_value("Exam Rule Set", rule_set, "examination_mode", AFFILIATED)  # the R2022 students: the university's
		cls.affiliated = frappe.get_doc(
			{"doctype": "Exam Session", "company": COLLEGE, "academic_term": cls.term, "status": "Marks Entry", "examination_mode": AFFILIATED}
		).insert()
		frappe.db.set_value("Student", cls.s22.name, "oc_university_register_no", "UNI-22")
		frappe.db.set_value("Student", cls.s26.name, "oc_university_register_no", "UNI-26")
		cls.export_format = make_format(
			EXPORT_FORMAT, "Export", [("REGNO", "University Register No"), ("SUB", "Course Code"), ("NAME", "Student Name"), ("INT", "CIA")]
		).name
		cls.import_format = make_format(
			IMPORT_FORMAT, "Import", [("REGNO", "University Register No"), ("SUB", "Course Code"), ("GRADE", "Grade"), ("ESE", "ESE")]
		).name
		for course in ("EXM TH", "EXM LB", "EXM FA"):  # EXM TL has no CIA sheet in the affiliated session
			enter_marks(cls.affiliated.name, cls.offerings22[course], {cls.s22.name: (30, 0), cls.s_ab.name: (25, 0)})
		with patch.object(registration, "attendance_snapshot", lambda *a: "Eligible"):
			for student in (cls.s22, cls.s_ab):
				name = registration.register(student.name, cls.affiliated.name)
				doc = frappe.get_doc("Exam Registration", name)
				doc.confirmed = 1
				doc.flags.server_fields = True
				doc.save()
		make_company(OTHER_COLLEGE, "AFOC")
		make_user(OTHER_COE, [OTHER_COLLEGE])
		frappe.get_doc("User", OTHER_COE).add_roles("COE")

	def as_coe(self):
		frappe.set_user(COE_USER)

	# ---- export helpers -------------------------------------------------------------------------

	def batch(self):
		return frappe.get_doc(
			{"doctype": "University Exam Registration Batch", "exam_session": self.affiliated.name, "export_format": self.export_format}
		).insert()

	def rows(self, name):
		return {(r.student, r.course): r for r in frappe.get_doc("University Exam Registration Batch", name).rows}

	def exported(self, url):
		content = frappe.get_doc("File", {"file_url": url}).get_content()
		return list(csv.reader(io.StringIO(content.decode() if isinstance(content, bytes) else content)))

	# ---- import helpers -------------------------------------------------------------------------

	def result_import(self, rows, **values):
		doc = frappe.get_doc(
			{
				"doctype": "University Result Import", "exam_session": self.affiliated.name, "import_format": self.import_format,
				"result_file": "/private/files/univ-results.csv", "result_date": add_days(today(), -1), **values,
			}
		).insert()  # fmt: skip
		self.content = csv_bytes([["REGNO", "SUB", "GRADE", "ESE"], *rows])
		return doc.name

	def preview(self, name):
		with patch.object(university_import, "read_private_file", lambda url: self.content):
			university_import.validate_import(name)
		return {r.row_no: r for r in frappe.get_all("University Result Import Row", {"university_result_import": name}, ["*"])}

	def run_import(self, name):
		with patch.object(bulk, "enqueue_run"), patch.object(frappe.db, "commit"):
			run = university_import.start_import(name)
			if run:
				bulk.process_bulk_run(run)
		return frappe.get_doc("University Result Import", name)

	def latest(self, student):
		name = frappe.db.get_value("Student Result", {"student": student, "exam_session": self.affiliated.name, "is_latest": 1})
		return name and frappe.get_doc("Student Result", name)


class TestMode(AffiliatedFixture):
	def test_the_regulation_decides_the_students_mode(self):
		self.assertEqual(examination_mode(self.s22.name), AFFILIATED)
		self.assertEqual(examination_mode(self.s26.name), "Autonomous")

	def test_the_college_mode_applies_when_the_rule_set_is_blank(self):
		rule_set = frappe.db.get_value("Exam Rule Set", {"regulation": ["like", "R2026-EXM%"]})
		self.assertEqual(frappe.db.get_value("Exam Rule Set", rule_set, "examination_mode") or "", "")
		frappe.get_doc({"doctype": "Institution Profile", "company": COLLEGE, "examination_mode": AFFILIATED}).insert()
		self.assertEqual(examination_mode(self.s26.name), AFFILIATED)

	def test_an_affiliated_session_refuses_the_result_run_and_publication(self):
		self.as_coe()
		with patch.object(bulk, "enqueue_run"), self.assertRaises(frappe.ValidationError) as refused:
			results.start_run(self.affiliated.name, PROGRAM)
		self.assertIn("Affiliated", str(refused.exception))
		with self.assertRaises(frappe.ValidationError):
			results.compute_student_result(self.s22.name, self.affiliated.name)
		with self.assertRaises(frappe.ValidationError) as refused:
			publication.publish_results(self.affiliated.name, today(), "x", "1")
		self.assertIn("Affiliated", str(refused.exception))

	def test_affiliated_students_are_left_out_of_an_autonomous_run(self):
		self.as_coe()
		with patch.object(bulk, "enqueue_run"):
			name = results.start_run(self.session.name, PROGRAM)
		self.assertEqual(frappe.parse_json(frappe.db.get_value("Bulk Run", name, "items")), [self.s26.name])
		with self.assertRaises(frappe.ValidationError) as refused:
			results.compute_student_result(self.s22.name, self.session.name)
		self.assertIn("university", str(refused.exception))

	def test_registration_puts_a_student_only_in_a_session_of_their_mode(self):
		with patch.object(registration, "attendance_snapshot", lambda *a: "Eligible"):
			self.assertIsNone(registration.register(self.s26.name, self.affiliated.name))
			self.assertIsNone(registration.register(self.s22.name, self.session.name))
			self.assertTrue(registration.register(self.s26.name, self.session.name))

	def test_an_affiliated_session_is_not_published_by_hand(self):
		self.affiliated.reload()
		self.affiliated.status, self.affiliated.publish_at = "Published", today()
		with self.assertRaises(frappe.ValidationError):
			self.affiliated.save()

	def test_one_session_per_term_and_mode(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "Exam Session", "company": COLLEGE, "academic_term": self.term, "examination_mode": AFFILIATED}).insert()


class TestRegistrationExport(AffiliatedFixture):
	def test_export_validation_lists_every_refused_row(self):
		name = self.batch().name
		university_export.build_rows(name)
		rows = self.rows(name)
		self.assertEqual(rows[(self.s22.name, "EXM TH")].status, "Ready")
		self.assertEqual(rows[(self.s22.name, "EXM TH")].cia, 30)
		self.assertIn("no university course code", rows[(self.s22.name, "EXM FA")].reason)
		self.assertIn("no CIA mark", rows[(self.s22.name, "EXM TL")].reason)
		self.assertIn("no university register number", rows[(self.s_ab.name, "EXM TH")].reason)
		self.assertEqual(rows[(self.s_ab.name, "EXM TH")].status, "Refused")

	def test_an_unlocked_cia_schedule_is_not_final(self):
		with patch.object(university_export, "schedule_of", lambda offering: "CIA-SCHED-X"):  # a schedule never locked
			row = university_export.RowBuilder(self.batch()).term_cia(self.s22.name, self.offerings22["EXM TH"])
		self.assertIn("not finalised", row[2])

	def test_the_file_follows_the_format_and_is_formula_safe(self):
		frappe.db.set_value("Student", self.s22.name, "student_name", INJECTION)
		name = self.batch().name
		university_export.build_rows(name)
		out = university_export.export(name)
		lines = self.exported(out["file_url"])
		self.assertEqual(lines[0], ["REGNO", "SUB", "NAME", "INT"])
		self.assertEqual(sorted(line[1] for line in lines[1:]), ["U-LB", "U-TH"])
		self.assertEqual({line[2] for line in lines[1:]}, {"'" + INJECTION})
		self.assertTrue(frappe.db.get_value("File", {"file_url": out["file_url"]}, "is_private"))
		self.assertEqual({r["student"] for r in out["refused"]}, {self.s22.name, self.s_ab.name})
		self.assertEqual(frappe.db.get_value("University Exam Registration Batch", name, "status"), "Exported")

	def test_reexport_sends_only_the_corrected_rows(self):
		name = self.batch().name
		university_export.build_rows(name)
		university_export.export(name)
		university_export.record_transmission(name, "TX-1", today())
		batch = frappe.get_doc("University Exam Registration Batch", name)
		next(r for r in batch.rows if r.course == "EXM LB" and r.student == self.s22.name).rejection_reason = "Subject code withdrawn"
		batch.save()
		university_export.record_acknowledgement(name, "ACK-1", today())
		rows = self.rows(name)
		self.assertEqual((rows[(self.s22.name, "EXM LB")].status, rows[(self.s22.name, "EXM TH")].status), ("Rejected", "Accepted"))
		self.assertEqual(frappe.db.get_value("University Exam Registration Batch", name, "status"), "Partly Rejected")
		frappe.db.set_value("Student", self.s_ab.name, "oc_university_register_no", "UNI-AB")  # a refused row fixed
		batch = frappe.get_doc("University Exam Registration Batch", name)
		next(r for r in batch.rows if r.course == "EXM LB" and r.student == self.s22.name).corrected = 1
		batch.save()
		out = university_export.reexport(name)
		sent = sorted((line[0], line[1]) for line in self.exported(out["file_url"])[1:])
		self.assertEqual(sent, [("UNI-22", "U-LB"), ("UNI-AB", "U-LB"), ("UNI-AB", "U-TH")])
		rows = self.rows(name)
		self.assertEqual(rows[(self.s22.name, "EXM TH")].export_no, 1)
		self.assertEqual(rows[(self.s22.name, "EXM LB")].export_no, 2)
		self.assertEqual(rows[(self.s22.name, "EXM FA")].status, "Refused")  # still no code mapping

	def test_rows_are_the_servers(self):
		name = self.batch().name
		university_export.build_rows(name)
		batch = frappe.get_doc("University Exam Registration Batch", name)
		batch.rows[0].cia = 99
		with self.assertRaises(frappe.ValidationError):
			batch.save()
		batch.reload()
		batch.rows[0].rejection_reason = "too early"  # not transmitted yet
		with self.assertRaises(frappe.ValidationError):
			batch.save()

	def test_an_autonomous_session_takes_no_batch(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{"doctype": "University Exam Registration Batch", "exam_session": self.session.name, "export_format": self.export_format}
			).insert()


class TestResultImport(AffiliatedFixture):
	GOOD = [["UNI-22", "U-TH", "A", "40"], ["UNI-22", "U-LB", "U", "10"]]

	def test_preview_rejects_each_bad_row_kind(self):
		name = self.result_import(
			[
				*self.GOOD, ["UNI-99", "U-TH", "A", "40"], ["UNI-22", "U-XX", "A", "40"], ["UNI-22", "U-TH", "A", "40"],
				["UNI-26", "U-TH", "A", "40"], ["UNI-22", "U-TL", "Z", "40"], ["", "U-TH", "A", ""],
			]
		)  # fmt: skip
		rows = self.preview(name)
		self.assertEqual((rows[2].status, rows[3].status), ("Valid", "Valid"))
		for row_no, text in (
			(4, "No student of this college"), (5, "not mapped"), (6, "Repeats row 2"), (7, "not registered"),
			(8, "not in the student's Grading Scheme"), (9, "Required"),
		):  # fmt: skip
			self.assertEqual(rows[row_no].status, "Rejected", row_no)
			self.assertIn(text, rows[row_no].message, row_no)
		self.assertFalse(frappe.db.exists("Student Result", {"exam_session": self.affiliated.name}))

	def test_import_writes_results_the_transcript_and_arrears_read(self):
		doc = self.run_import(self.preview_and_name(self.GOOD))
		self.assertEqual(doc.status, "Imported")
		result = self.latest(self.s22.name)
		self.assertEqual((result.source, result.university_result_import, result.version), ("University", doc.name, 1))
		grades = {c.course: (c.grade, c.grade_point, c.result) for c in result.courses}
		self.assertEqual(grades, {"EXM TH": ("A", 8, "Pass"), "EXM LB": ("U", 0, "Fail")})
		self.assertEqual((result.sgpa, result.arrear_count, result.result), (8.0, 1, "Reappear"))
		self.assertEqual(frappe.db.get_value("Exam Session", self.affiliated.name, "status"), "Published")
		self.assertEqual(arrears.arrear_courses(self.s22.name), ["EXM LB"])
		self.assertTrue(arrears.has_passed(self.s22.name, "EXM TH"))

	def test_the_same_file_again_changes_nothing(self):
		self.run_import(self.preview_and_name(self.GOOD))
		again = self.preview_and_name(self.GOOD)
		self.assertEqual({r.status for r in self.preview(again).values()}, {"Unchanged"})
		self.assertEqual(self.run_import(again).status, "Imported")
		self.assertEqual(frappe.db.count("Student Result", {"student": self.s22.name, "exam_session": self.affiliated.name}), 1)

	def test_a_correction_needs_a_reason_and_versions_the_old_result(self):
		first = self.latest_after(self.GOOD)
		name = self.preview_and_name([["UNI-22", "U-LB", "B", "35"]])
		self.assertEqual(self.preview(name)[2].status, "Correction")
		with self.assertRaises(frappe.ValidationError):
			university_import.start_import(name)
		frappe.db.set_value("University Result Import", name, "correction_reason", "University revaluation")
		self.run_import(name)
		new = self.latest(self.s22.name)
		self.assertEqual((new.version, new.previous_version), (2, first))
		self.assertFalse(frappe.db.get_value("Student Result", first, "is_latest"))
		self.assertIn("University revaluation", new.change_log)
		self.assertEqual({c.course: c.result for c in new.courses}, {"EXM TH": "Pass", "EXM LB": "Pass"})
		self.assertEqual(arrears.arrear_courses(self.s22.name), [])

	def test_a_public_file_is_refused(self):
		file = frappe.get_doc({"doctype": "File", "file_name": "univ-public.csv", "content": b"REGNO\n", "is_private": 0}).insert()
		self.addCleanup(lambda: frappe.db.exists("File", file.name) and frappe.delete_doc("File", file.name, force=True))
		with self.assertRaises(frappe.ValidationError) as refused:
			university_import.read_private_file(file.file_url)
		self.assertIn("private", str(refused.exception))

	def test_company_scope(self):
		name = self.result_import(self.GOOD)
		self.assertFalse(frappe.has_permission("University Result Import", "read", name, user=OTHER_COE))
		frappe.set_user(OTHER_COE)
		with self.assertRaises(frappe.PermissionError):
			university_import.validate_import(name)

	def preview_and_name(self, rows):
		name = self.result_import(rows)
		self.preview(name)
		return name

	def latest_after(self, rows):
		self.run_import(self.preview_and_name(rows))
		return self.latest(self.s22.name).name
