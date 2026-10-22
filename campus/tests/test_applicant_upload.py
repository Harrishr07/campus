"""L-04 tests (M04-06, M04-07): bulk applicant upload with a validation preview, duplicate candidate detection and review."""

import csv
import io
from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from campus.admissions import allotment_import, applicant_upload, duplicates
from campus.campus_platform import bulk
from campus.tests.factories import make_company, make_user
from campus.tests.test_regulation import make_program, make_year, year_name
from campus.tests.utils import CampusTestCase

COLLEGE, OTHER_COLLEGE = "Upload Test College", "Upload Test Other College"
PROGRAM, OTHER_PROGRAM = "Upload Test BSc", "Upload Test Other BSc"
OFFICER, CLERK = "upload-officer@example.com", "upload-clerk@example.com"
HEADER = [
	"First Name", "Middle Name", "Last Name", "Date of Birth", "Gender", "Email", "Mobile", "Program",
	"Qualifying Exam", "Qualifying Register No",
]  # fmt: skip


def year():
	return year_name("2022")


def file_row(first, last, dob="2007-04-01", regno=None, program=PROGRAM, email=None, mobile="9876500001", exam="TN HSC"):
	email = email or f"{first.lower()}.{last.lower()}@upload-test.example.com"
	return [first, "", last, dob, "", email, mobile, program, exam, regno if regno is not None else f"R{first}{last}"]


def csv_bytes(rows):
	out = io.StringIO()
	csv.writer(out).writerows(rows)
	return out.getvalue().encode()


def make_applicant(first, last, dob="2007-04-01", company=COLLEGE, program=PROGRAM, **values):
	return frappe.get_doc(
		{
			"doctype": "Student Applicant", "first_name": first, "last_name": last, "date_of_birth": dob,
			"program": program, "academic_year": year(), "oc_company": company, **values,
		}
	).insert()  # fmt: skip


class UploadTestCase(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_company(COLLEGE, "UTC")
		make_company(OTHER_COLLEGE, "UTO")
		make_year("2022")
		make_program(PROGRAM, COLLEGE)
		make_program(OTHER_PROGRAM, OTHER_COLLEGE)
		make_user(OFFICER, [COLLEGE])
		make_user(CLERK, [COLLEGE])
		frappe.get_doc("User", OFFICER).add_roles("Admission Officer")

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("upload_test")
		self.addCleanup(frappe.db.rollback, save_point="upload_test")
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.db.delete("Student Applicant", {"oc_company": COLLEGE})
		frappe.db.delete("Student", {"oc_company": COLLEGE})

	def upload(self, rows):
		doc = frappe.get_doc(
			{"doctype": "Applicant Upload", "company": COLLEGE, "academic_year": year(), "upload_file": "applicants.csv"}
		).insert()
		self.content = csv_bytes([HEADER, *rows])
		return doc.name

	def preview(self, name):
		with self.file():
			return applicant_upload.validate_upload(name)

	def run_import(self, name):
		with self.file(), patch.object(bulk, "enqueue_run"), patch.object(frappe.db, "commit"):
			run = applicant_upload.start_import(name)
			if run:
				bulk.process_bulk_run(run)
		return frappe.get_doc("Applicant Upload", name)

	def file(self):
		stack = patch.multiple(allotment_import, read_file=lambda url: self.content, make_private=lambda *a, **k: None)
		return stack

	def rows(self, name):
		return {
			r.row_no: r
			for r in frappe.get_all("Applicant Upload Row", {"applicant_upload": name}, ["row_no", "status", "message", "applicant", "review"])
		}

	def applicant_count(self):
		return frappe.db.count("Student Applicant", {"oc_company": COLLEGE})


class TestUploadPreview(UploadTestCase):
	def test_preview_lists_valid_invalid_and_duplicate_rows_without_writing_applicants(self):
		existing = make_applicant("Asha", "Kumar")
		name = self.upload(
			[
				file_row("Ravi", "Menon"), file_row("", "Noname"), file_row("Bad", "Date", dob="31-31-2007"),
				file_row("Kumar", "Asha", regno="X1"), file_row("Wrong", "Program", program=OTHER_PROGRAM),
				file_row("Blank", "Regno", regno=""),
			]
		)  # fmt: skip
		summary = self.preview(name)
		rows = self.rows(name)
		self.assertEqual(self.applicant_count(), 1)  # nothing written but the existing applicant
		self.assertEqual(
			{n: r.status for n, r in rows.items()},
			{2: "Valid", 3: "Invalid", 4: "Invalid", 5: "Possible Duplicate", 6: "Invalid", 7: "Invalid"},
		)
		self.assertIn(existing.name, rows[5].message)
		self.assertIn("First Name", rows[3].message)
		self.assertIn("Qualifying Register No", rows[7].message)
		self.assertEqual((summary["Valid"], summary["Invalid"], summary["Possible Duplicate"]), (1, 4, 1))
		self.assertEqual(frappe.db.get_value("Applicant Upload", name, "status"), "Validated")

	def test_rows_repeated_in_the_file_are_flagged(self):
		name = self.upload([file_row("Ravi", "Menon"), file_row("Ravi", "Menon"), file_row("Menon", "Ravi", regno="OTHER")])
		self.preview(name)
		rows = self.rows(name)
		self.assertEqual([rows[n].status for n in (2, 3, 4)], ["Valid", "Invalid", "Possible Duplicate"])
		self.assertIn("2", rows[3].message)
		self.assertIn("2", rows[4].message)

	def test_missing_template_column_is_refused(self):
		name = self.upload([])
		self.content = csv_bytes([["First Name", "Program"], ["A", PROGRAM]])
		with self.file(), self.assertRaises(frappe.ValidationError):
			applicant_upload.validate_upload(name)

	def test_import_needs_a_validated_upload(self):
		name = self.upload([file_row("Ravi", "Menon")])
		with self.assertRaises(frappe.ValidationError):
			self.run_import(name)


class TestUploadImport(UploadTestCase):
	def test_import_creates_only_valid_rows_and_holds_duplicates_for_review(self):
		existing = make_applicant("Asha", "Kumar")
		name = self.upload([file_row("Ravi", "Menon"), file_row("", "Noname"), file_row("Asha", "Kumar", regno="X1")])
		self.preview(name)
		doc = self.run_import(name)
		rows = self.rows(name)
		self.assertEqual({n: r.status for n, r in rows.items()}, {2: "Created", 3: "Invalid", 4: "Held for Review"})
		self.assertEqual(self.applicant_count(), 2)
		created = frappe.get_doc("Student Applicant", rows[2].applicant)
		self.assertEqual(
			(created.first_name, created.oc_company, created.academic_year, created.oc_qualifying_register_no),
			("Ravi", COLLEGE, year(), "RRAVIMENON"),
		)
		review = frappe.get_doc("Candidate Duplicate Review", rows[4].review)
		self.assertEqual((review.status, review.existing_applicant, review.company, review.applicant_upload), ("Open", existing.name, COLLEGE, name))
		self.assertEqual(doc.status, "Awaiting Review")

	def test_retry_with_the_same_file_creates_nothing_new(self):
		rows = [file_row("Ravi", "Menon"), file_row("Meena", "Raj")]
		first = self.upload(rows)
		self.preview(first)
		self.run_import(first)
		before = sorted(frappe.get_all("Student Applicant", {"oc_company": COLLEGE}, pluck="name"))
		again = self.upload(rows)
		self.preview(again)
		self.assertEqual({r.status for r in self.rows(again).values()}, {"Already Imported"})
		doc = self.run_import(again)
		self.assertEqual(sorted(frappe.get_all("Student Applicant", {"oc_company": COLLEGE}, pluck="name")), before)
		self.assertEqual({r.applicant for r in self.rows(again).values()}, set(before))
		self.assertEqual(doc.status, "Completed")
		self.assertEqual(frappe.db.count("Candidate Duplicate Review", {"applicant_upload": again}), 0)

	def test_a_started_import_is_not_started_twice(self):
		name = self.upload([file_row("Ravi", "Menon")])
		self.preview(name)
		self.run_import(name)
		with self.assertRaises(frappe.ValidationError):
			self.run_import(name)
		self.assertEqual(self.applicant_count(), 1)

	def test_the_candidate_key_is_unique_in_the_database(self):
		applicant = make_applicant("Ravi", "Menon", oc_qualifying_exam="TN HSC", oc_qualifying_register_no="R1")
		key = frappe.db.get_value("Student Applicant", applicant.name, "oc_candidate_key")
		self.assertTrue(key)
		twin = frappe.get_doc(
			{"doctype": "Student Applicant", "first_name": "Bypass", "program": PROGRAM, "academic_year": year(),
				"oc_company": COLLEGE, "oc_candidate_key": key}
		)  # fmt: skip
		twin.flags.ignore_validate = True  # what a racing insert that skipped the check would write
		with self.assertRaises(frappe.UniqueValidationError):
			twin.insert()


class TestDuplicateRule(UploadTestCase):
	def test_manual_entry_of_the_same_name_and_birth_date_is_refused(self):
		existing = make_applicant("Asha", "Kumar")
		with self.assertRaises(duplicates.DuplicateCandidateError) as caught:
			make_applicant("kumar", "ASHA.")
		self.assertIn(existing.name, str(caught.exception))

	def test_manual_entry_with_the_same_qualifying_exam_register_number_is_refused(self):
		make_applicant("Asha", "Kumar", oc_qualifying_exam="TN HSC", oc_qualifying_register_no="hs 1234")
		with self.assertRaises(duplicates.DuplicateCandidateError):
			make_applicant("Different", "Name", dob="2006-02-02", oc_qualifying_exam="tn-hsc", oc_qualifying_register_no="HS1234")

	def test_shared_phone_or_email_alone_is_not_a_duplicate(self):
		# applicant e-mail is unique upstream, so the shared e-mail is the Student's and the phone the applicant's
		make_applicant("Asha", "Kumar", student_mobile_number="9876500001")
		frappe.get_doc(
			{"doctype": "Student", "first_name": "Chitra", "last_name": "Kumar", "date_of_birth": "2005-05-05",
				"student_email_id": "family@upload-test.example.com", "student_mobile_number": "9876500001", "oc_company": COLLEGE}
		).insert()  # fmt: skip
		sibling = make_applicant("Bala", "Kumar", dob="2009-09-09", student_email_id="family@upload-test.example.com", student_mobile_number="9876500001")
		self.assertEqual(frappe.db.get_value("Student Applicant", sibling.name, "student_mobile_number"), "9876500001")

	def test_another_college_and_another_exam_are_not_duplicates(self):
		make_applicant("Asha", "Kumar", oc_qualifying_exam="TN HSC", oc_qualifying_register_no="1234")
		self.assertTrue(make_applicant("Asha", "Kumar", company=OTHER_COLLEGE, program=OTHER_PROGRAM).name)
		self.assertTrue(make_applicant("Other", "Person", dob="2006-02-02", oc_qualifying_exam="CBSE", oc_qualifying_register_no="1234").name)

	def test_an_existing_student_is_a_duplicate_of_a_returning_candidate(self):
		student = frappe.get_doc(
			{"doctype": "Student", "first_name": "Asha", "last_name": "Kumar", "date_of_birth": "2007-04-01",
				"student_email_id": "asha.returning@upload-test.example.com", "oc_company": COLLEGE}
		).insert()  # fmt: skip
		with self.assertRaises(duplicates.DuplicateCandidateError) as caught:
			make_applicant("Asha", "Kumar")
		self.assertIn(student.name, str(caught.exception))

	def test_saving_an_applicant_again_does_not_match_itself(self):
		applicant = make_applicant("Asha", "Kumar", oc_qualifying_exam="TN HSC", oc_qualifying_register_no="1234")
		applicant.student_mobile_number = "9876500002"
		applicant.save()
		applicant.first_name = "Asha "
		applicant.save()


class TestDuplicateReview(UploadTestCase):
	def held_review(self):
		existing = make_applicant("Asha", "Kumar")
		name = self.upload([file_row("Asha", "Kumar", regno="X1")])
		self.preview(name)
		self.run_import(name)
		return existing, name, self.rows(name)[2].review

	def test_link_to_the_existing_record_creates_nothing_and_is_logged(self):
		existing, name, review = self.held_review()
		frappe.set_user(OFFICER)
		duplicates.decide(review, "Link", note="Same candidate, second counselling round")
		frappe.set_user("Administrator")
		doc = frappe.get_doc("Candidate Duplicate Review", review)
		self.assertEqual((doc.status, doc.decided_by, doc.linked_applicant), ("Linked", OFFICER, existing.name))
		self.assertTrue(doc.decided_on)
		self.assertEqual(self.applicant_count(), 1)
		row = self.rows(name)[2]
		self.assertEqual((row.status, row.applicant), ("Linked", existing.name))
		self.assertTrue(frappe.db.exists("Version", {"ref_doctype": "Candidate Duplicate Review", "docname": review}))

	def test_not_duplicate_creates_the_applicant_and_is_logged(self):
		existing, name, review = self.held_review()
		frappe.set_user(OFFICER)
		with self.assertRaises(frappe.ValidationError):
			duplicates.decide(review, "Not Duplicate")  # a reason is required
		created = duplicates.decide(review, "Not Duplicate", note="Different parents, checked marksheet")
		frappe.set_user("Administrator")
		doc = frappe.get_doc("Candidate Duplicate Review", review)
		self.assertEqual((doc.status, doc.decided_by, doc.new_applicant, doc.note), ("Not Duplicate", OFFICER, created, "Different parents, checked marksheet"))
		self.assertEqual(frappe.db.get_value("Student Applicant", created, "oc_duplicate_review"), review)
		self.assertEqual(self.applicant_count(), 2)
		self.assertEqual((self.rows(name)[2].status, self.rows(name)[2].applicant), ("Created", created))
		with self.assertRaises(frappe.ValidationError):
			duplicates.decide(review, "Link")  # decided once
		self.assertEqual(frappe.db.get_value("Applicant Upload", name, "status"), "Completed")

	def test_a_cleared_review_does_not_let_another_applicant_through(self):
		_existing, _name, review = self.held_review()
		with self.assertRaises(duplicates.DuplicateCandidateError):
			make_applicant("Asha", "Kumar", oc_duplicate_review=review)

	def test_only_an_admission_officer_decides(self):
		_existing, _name, review = self.held_review()
		frappe.set_user(CLERK)
		with self.assertRaises(frappe.PermissionError):
			duplicates.decide(review, "Link")


class TestNormalisation(UnitTestCase):
	def test_names_ignore_case_punctuation_spacing_and_order(self):
		self.assertEqual(duplicates.name_key("R.", "", "Asha  Kumar"), duplicates.name_key("asha", "kumar", "r"))
		self.assertNotEqual(duplicates.name_key("Asha", "", "Kumar"), duplicates.name_key("Asha", "", "Kumari"))
		self.assertEqual(duplicates.name_key("", None, ""), "")

	def test_identifiers_keep_letters_and_digits_only(self):
		self.assertEqual(duplicates.id_key(" hs-12 34 "), "HS1234")
		self.assertEqual(duplicates.id_key(None), "")

	def test_exam_match_needs_the_same_register_number_and_a_compatible_exam(self):
		self.assertTrue(duplicates.same_exam("TNHSC", "TNHSC"))
		self.assertTrue(duplicates.same_exam("", "TNHSC"))
		self.assertFalse(duplicates.same_exam("CBSE", "TNHSC"))
