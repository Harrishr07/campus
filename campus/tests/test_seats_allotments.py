"""P1-T15 tests (M04-01, M04-02, M04-03): seat matrix, allotment import, document verification, reminders, reports."""

import csv
import io
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.utils import today

from campus.admissions import allotment_import, documents, seat_matrix
from campus.admissions.api import check_seat_available, documents_complete, pending_documents, set_document_status
from campus.admissions.report.live_seat_matrix import live_seat_matrix
from campus.admissions.report.pending_documents import pending_documents as pending_report
from campus.campus_messaging import channels
from campus.campus_platform import bulk
from campus.tests.factories import make_company, make_user
from campus.tests.test_regulation import make_program, make_year, year_name
from campus.tests.utils import CampusTestCase

SERIAL = [0]
COLLEGE, OTHER_COLLEGE = "Seat Test College", "Seat Test Other College"
PROGRAM, OTHER_PROGRAM = "Seat Test BE CSE", "Seat Test Other BE"
AUTHORITY = "Seat Test TNEA"
OVERRIDER, PLAIN, VERIFIER, OUTSIDER = (f"seat-{r}@example.com" for r in ("override", "plain", "verifier", "outsider"))
GOVT, MGMT, SUPER = "STGQ", "STMQ", "STSUP"
OC, BC, MBC = "OC", "BC", "MBC"


def year():
	return year_name("2022")


class SeatTestCase(CampusTestCase):
	"""One college with a program, quotas, categories, three users and test-wide cleanup by rollback."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_company(COLLEGE, "STC")
		make_company(OTHER_COLLEGE, "STO")
		make_year("2022")
		make_program(PROGRAM, COLLEGE)
		make_program(OTHER_PROGRAM, OTHER_COLLEGE)
		for category in (OC, BC, MBC):
			if not frappe.db.exists("Student Category", category):
				frappe.get_doc({"doctype": "Student Category", "category": category}).insert()
		cls.make_quotas()
		cls.make_users()

	@classmethod
	def make_quotas(cls):
		for code, extra in ((GOVT, {}), (MGMT, {}), (SUPER, {"is_supernumerary": 1})):
			if not frappe.db.exists("Admission Quota", code):
				frappe.get_doc({"doctype": "Admission Quota", "code": code, "title": code, **extra}).insert()

	@classmethod
	def make_users(cls):
		for user in (OVERRIDER, PLAIN, VERIFIER):
			make_user(user, [COLLEGE])
		make_user(OUTSIDER, [OTHER_COLLEGE])
		frappe.get_doc("User", OVERRIDER).add_roles("Admission Override")
		frappe.get_doc("User", VERIFIER).add_roles("Admission Verifier")

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("seat_test")
		self.addCleanup(frappe.db.rollback, save_point="seat_test")
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.db.delete("Seat Matrix")
		frappe.db.delete("Admission Document Rule")

	def matrix(self, rows, program=PROGRAM, company=COLLEGE):
		return frappe.get_doc(
			{
				"doctype": "Seat Matrix", "company": company, "program": program, "academic_year": year(),
				"rows": [{"quota": q, "category": c, "sanctioned": n} for q, c, n in rows],
			}
		).insert()

	def row(self, matrix, quota, category):
		return frappe.db.get_value(
			"Seat Matrix Row", {"parent": matrix.name, "quota": quota, "category": category},
			["sanctioned", "allotted", "filled", "vacant"], as_dict=True,
		)  # fmt: skip

	def student(self):
		SERIAL[0] += 1
		was_importing, frappe.flags.in_import = frappe.flags.in_import, True  # skip the user-creation throttle
		self.addCleanup(setattr, frappe.flags, "in_import", was_importing)
		return frappe.get_doc(
			{"doctype": "Student", "first_name": f"Seat{SERIAL[0]}", "student_email_id": f"seat{SERIAL[0]}-{frappe.generate_hash(length=6)}@seat.example.com", "oc_company": COLLEGE}
		).insert().name  # fmt: skip

	def enrollment(self, quota, category, submit=True, program=PROGRAM):
		doc = frappe.get_doc(
			{
				"doctype": "Program Enrollment", "student": self.student(), "program": program, "academic_year": year(),
				"enrollment_date": today(), "student_category": category, "oc_admission_quota": quota,
			}
		).insert()  # fmt: skip
		return doc.submit() if submit else doc


class TestSeatMatrix(SeatTestCase):
	def test_rows_start_with_sanctioned_and_zero_filled(self):
		matrix = self.matrix([(GOVT, OC, 10), (GOVT, BC, 5)])
		self.assertEqual(dict(self.row(matrix, GOVT, OC)), {"sanctioned": 10, "allotted": 0, "filled": 0, "vacant": 10})
		self.assertEqual(self.row(matrix, GOVT, BC).vacant, 5)

	def test_filled_counts_submitted_enrollments_only_and_cancel_frees_the_seat(self):
		matrix = self.matrix([(GOVT, OC, 3), (GOVT, BC, 3)])
		self.enrollment(GOVT, OC, submit=False)  # a draft is not a seat
		self.assertEqual(self.row(matrix, GOVT, OC).filled, 0)
		first = self.enrollment(GOVT, OC)
		self.enrollment(GOVT, OC)
		self.enrollment(GOVT, BC)
		self.assertEqual(dict(self.row(matrix, GOVT, OC)), {"sanctioned": 3, "allotted": 0, "filled": 2, "vacant": 1})
		self.assertEqual(self.row(matrix, GOVT, BC).filled, 1)
		first.cancel()
		self.assertEqual(dict(self.row(matrix, GOVT, OC)), {"sanctioned": 3, "allotted": 0, "filled": 1, "vacant": 2})

	def test_enrollment_without_a_matching_row_or_matrix_changes_nothing(self):
		matrix = self.matrix([(GOVT, OC, 3)])
		self.enrollment(MGMT, OC)  # no row for this quota
		self.enrollment(GOVT, MBC)  # no row for this category
		self.assertEqual(self.row(matrix, GOVT, OC).filled, 0)
		frappe.db.delete("Seat Matrix")
		self.enrollment(GOVT, OC)  # no matrix at all: no error

	def test_recount_matches_the_incremental_counts(self):
		matrix = self.matrix([(GOVT, OC, 4)])
		self.enrollment(GOVT, OC)
		self.enrollment(GOVT, OC).cancel()
		frappe.db.set_value("Seat Matrix Row", {"parent": matrix.name}, {"filled": 7, "vacant": -3})  # simulate drift
		seat_matrix.recount_seat_matrix(matrix.name)
		self.assertEqual(dict(self.row(matrix, GOVT, OC)), {"sanctioned": 4, "allotted": 0, "filled": 1, "vacant": 3})

	def test_saving_the_matrix_keeps_filled_and_a_new_row_is_counted_from_enrollments(self):
		matrix = self.matrix([(GOVT, OC, 4)])
		self.enrollment(GOVT, OC)
		self.enrollment(MGMT, BC)
		doc = frappe.get_doc("Seat Matrix", matrix.name)
		doc.rows[0].filled = 99  # a forged form value is ignored
		doc.rows[0].sanctioned = 6
		doc.append("rows", {"quota": MGMT, "category": BC, "sanctioned": 2})
		doc.save()
		self.assertEqual(dict(self.row(matrix, GOVT, OC)), {"sanctioned": 6, "allotted": 0, "filled": 1, "vacant": 5})
		self.assertEqual(self.row(matrix, MGMT, BC).filled, 1)  # counted from the existing enrollment

	def test_allotted_counts_applicants_with_an_allotment_number(self):
		matrix = self.matrix([(GOVT, OC, 4)])
		self.applicant(oc_allotment_no="A1", oc_counselling_authority=self.authority())
		self.applicant(oc_allotment_no="A2", oc_counselling_authority=self.authority(), application_status="Rejected")
		self.applicant()  # no allotment number
		seat_matrix.refresh_allotted(COLLEGE, PROGRAM, year())
		self.assertEqual(self.row(matrix, GOVT, OC).allotted, 1)

	def test_validation(self):
		self.matrix([(GOVT, OC, 1)])
		with self.assertRaises(frappe.ValidationError):
			self.matrix([(GOVT, OC, 1)])  # one matrix per company, program and year
		for bad in ([(GOVT, BC, 1), (GOVT, BC, 2)], [(GOVT, BC, -1)]):
			with self.assertRaises(frappe.ValidationError):
				self.matrix(bad, program=OTHER_PROGRAM, company=OTHER_COLLEGE)
		with self.assertRaises(frappe.ValidationError):
			self.matrix([(GOVT, BC, 1)], program=OTHER_PROGRAM)  # program of another company
		frappe.db.set_value("Admission Quota", MGMT, "counts_in_seat_matrix", 0)
		self.addCleanup(frappe.db.set_value, "Admission Quota", MGMT, "counts_in_seat_matrix", 1)
		with self.assertRaises(frappe.ValidationError):
			self.matrix([(MGMT, BC, 1)], program=OTHER_PROGRAM, company=OTHER_COLLEGE)

	# helpers shared with the other classes of this module
	def authority(self):
		return make_authority()

	def applicant(self, **values):
		return make_applicant(**values)


def make_authority(mapping=None):
	if not frappe.db.exists("Counselling Authority", AUTHORITY):
		frappe.get_doc(
			{
				"doctype": "Counselling Authority", "authority_name": AUTHORITY,
				"column_mapping": [
					{"source_column": s, "target_field": t}
					for s, t in (mapping or MAPPING).items()
				],
			}
		).insert()
	return AUTHORITY


MAPPING = {
	"Allotment No": "oc_allotment_no", "Name": "first_name", "Branch": "program", "Community": "student_category",
	"Quota": "oc_admission_quota", "Rank": "oc_rank", "Cutoff": "oc_cutoff", "Mobile": "student_mobile_number",
}


def make_applicant(**values):
	values.setdefault("oc_allotment_no", None)
	return frappe.get_doc(
		{
			"doctype": "Student Applicant", "first_name": "Seat", "program": PROGRAM, "academic_year": year(), "oc_company": COLLEGE,
			"student_category": OC, "oc_admission_quota": GOVT, "oc_admission_type": "Regular", **values,
		}
	).insert()  # fmt: skip


class TestSeatOverride(SeatTestCase):
	def full_matrix(self):
		matrix = self.matrix([(GOVT, OC, 1), (SUPER, OC, 0)])
		self.enrollment(GOVT, OC)
		return matrix

	def test_a_free_seat_is_allowed(self):
		self.matrix([(GOVT, OC, 2)])
		self.assertIs(check_seat_available(PROGRAM, year(), GOVT, OC), True)

	def test_a_full_row_is_blocked_for_everyone_without_the_override_role(self):
		self.full_matrix()
		for user in (PLAIN, VERIFIER):
			frappe.set_user(user)
			with self.assertRaises(frappe.ValidationError) as ctx:
				check_seat_available(PROGRAM, year(), GOVT, OC)
			self.assertIn("sanctioned 1, filled 1", str(ctx.exception))
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.count("Seat Override Log"), 0)

	def test_override_holder_is_allowed_and_logged(self):
		self.full_matrix()
		applicant = make_applicant()
		frappe.set_user(OVERRIDER)
		self.assertEqual(check_seat_available(PROGRAM, year(), GOVT, OC, applicant.name), "override")
		frappe.set_user("Administrator")
		log = frappe.get_all("Seat Override Log", fields=["*"])
		self.assertEqual(len(log), 1)
		self.assertEqual(
			(log[0].user, log[0].company, log[0].program, log[0].quota, log[0].category, log[0].applicant, log[0].sanctioned, log[0].filled),
			(OVERRIDER, COLLEGE, PROGRAM, GOVT, OC, applicant.name, 1, 1),
		)

	def test_over_admission_by_override_shows_negative_vacancy(self):
		matrix = self.full_matrix()
		self.enrollment(GOVT, OC)
		self.assertEqual(self.row(matrix, GOVT, OC).vacant, -1)

	def test_cancellation_frees_the_seat(self):
		matrix = self.matrix([(GOVT, OC, 1)])
		enrollment = self.enrollment(GOVT, OC)
		frappe.set_user(PLAIN)
		with self.assertRaises(frappe.ValidationError):
			check_seat_available(PROGRAM, year(), GOVT, OC)
		frappe.set_user("Administrator")
		enrollment.cancel()
		frappe.set_user(PLAIN)
		self.assertIs(check_seat_available(PROGRAM, year(), GOVT, OC), True)

	def test_supernumerary_quota_and_unconfigured_rows_are_not_enforced(self):
		self.full_matrix()
		frappe.set_user(PLAIN)
		self.assertIs(check_seat_available(PROGRAM, year(), SUPER, OC), True)  # supernumerary
		self.assertIs(check_seat_available(PROGRAM, year(), GOVT, MBC), True)  # no row for the category
		self.assertIs(check_seat_available(OTHER_PROGRAM, year(), GOVT, OC), True)  # no matrix

	def test_check_locks_the_matrix_and_rereads_the_row_with_a_locking_read(self):
		self.full_matrix()
		real = frappe.db.get_value
		calls = []

		def spy(doctype, *args, **kwargs):
			calls.append((doctype, bool(kwargs.get("for_update"))))
			return real(doctype, *args, **kwargs)

		with patch.object(frappe.db, "get_value", side_effect=spy), self.assertRaises(frappe.ValidationError):
			frappe.set_user(PLAIN)
			check_seat_available(PROGRAM, year(), GOVT, OC)
		self.assertIn(("Seat Matrix", True), calls)
		self.assertIn(("Seat Matrix Row", True), calls)
		self.assertNotIn(("Seat Matrix Row", False), calls)


def csv_bytes(rows):
	out = io.StringIO()
	csv.writer(out).writerows(rows)
	return out.getvalue().encode()


HEADER = ["Allotment No", "Name", "Branch", "Community", "Quota", "Rank", "Cutoff", "Mobile", "Aadhaar", "Remark"]


def file_row(no, rank=100, cutoff="190.5", branch="CS", community=OC, name="default", quota=GOVT):
	return [no, f"Student {no}" if name == "default" else name, branch, community, quota, rank, cutoff, "9876500000", "234123412346", "x"]


class TestAllotmentImport(SeatTestCase):
	def setUp(self):
		super().setUp()
		make_authority()
		frappe.db.delete("Student Applicant", {"oc_counselling_authority": AUTHORITY})

	def run_import(self, rows, mapping=None, company=COLLEGE):
		doc = frappe.get_doc(
			{
				"doctype": "Allotment Import", "company": company, "counselling_authority": AUTHORITY, "academic_year": year(),
				"import_file": "/files/tnea.csv", "program_mapping": [{"source_code": "cs", "program": PROGRAM}],
			}
		).insert()  # fmt: skip
		with (
			patch.object(allotment_import, "read_file", return_value=csv_bytes([HEADER, *rows])),
			patch.object(bulk, "enqueue_run"),
			patch.object(frappe.db, "commit"),  # keep the test transaction; the runner's chunk commit is a no-op
		):
			run = allotment_import.start_import(doc.name)
			bulk.process_bulk_run(run)
		return frappe.get_doc("Allotment Import", doc.name)

	def applicants(self):
		return frappe.get_all("Student Applicant", {"oc_counselling_authority": AUTHORITY}, ["name", "oc_rank", "oc_cutoff", "oc_allotment_key", "oc_company", "program", "student_category", "oc_admission_quota"], order_by="oc_allotment_no")

	def counts(self, doc):
		return (doc.total_rows, doc.created_rows, doc.updated_rows, doc.unchanged_rows, doc.error_rows)

	def test_import_creates_applicants_with_mapped_fields(self):
		doc = self.run_import([file_row("TN001", rank=7, community=BC), file_row("TN002", rank=9)])
		self.assertEqual((doc.status, self.counts(doc)), ("Completed", (2, 2, 0, 0, 0)))
		first = self.applicants()[0]
		self.assertEqual(
			(first.oc_rank, first.oc_cutoff, first.oc_allotment_key, first.oc_company, first.program, first.student_category, first.oc_admission_quota),
			(7, 190.5, f"{AUTHORITY}:TN001", COLLEGE, PROGRAM, BC, GOVT),
		)

	def test_importing_the_same_file_twice_creates_no_duplicates_and_updates_changed_ranks(self):
		rows = [file_row("TN001", rank=7), file_row("TN002", rank=9), file_row("TN003", rank=11)]
		first = self.run_import(rows)
		before = {a.name: a.oc_rank for a in self.applicants()}
		again = self.run_import(rows)
		self.assertEqual(self.counts(again), (3, 0, 0, 3, 0))
		self.assertEqual({a.name: a.oc_rank for a in self.applicants()}, before)  # same applicants, nothing duplicated
		changed = self.run_import([file_row("TN001", rank=7), file_row("TN002", rank=4, cutoff="195"), file_row("TN003", rank=11)])
		self.assertEqual(self.counts(changed), (3, 0, 1, 2, 0))
		updated = next(a for a in self.applicants() if a.oc_allotment_key.endswith("TN002"))
		self.assertEqual((updated.oc_rank, updated.oc_cutoff, updated.name), (4, 195, next(n for n, r in before.items() if r == 9)))
		message = frappe.db.get_value("Allotment Import Row", {"allotment_import": changed.name, "status": "Updated"}, "message")
		self.assertIn("oc_cutoff", message)
		self.assertEqual(first.status, "Completed")

	def test_row_errors_are_listed_and_do_not_stop_the_import(self):
		doc = self.run_import(
			[
				file_row("TN001"), file_row(""), file_row("TN003", branch="XX"), file_row("TN004", name=""),
				file_row("TN005", community="NOPE"), file_row("TN006"),
			]
		)
		self.assertEqual((doc.status, self.counts(doc)), ("Completed with errors", (6, 2, 0, 0, 4)))
		errors = {r.row_no: r.message for r in frappe.get_all("Allotment Import Row", {"allotment_import": doc.name, "status": "Error"}, ["row_no", "message"])}
		self.assertEqual(sorted(errors), [3, 4, 5, 6])  # file rows: header is row 1
		self.assertIn("blank", errors[3])
		self.assertIn("XX", errors[4])
		self.assertEqual(len(self.applicants()), 2)

	def test_duplicate_allotment_number_in_one_file_is_one_applicant(self):
		doc = self.run_import([file_row("TN001", rank=5), file_row("TN001", rank=6)])
		self.assertEqual(len(self.applicants()), 1)
		self.assertEqual(self.counts(doc), (2, 1, 1, 0, 0))

	def test_admitted_applicant_is_not_changed_and_other_company_is_refused(self):
		self.run_import([file_row("TN001", rank=5)])
		name = self.applicants()[0].name
		frappe.db.set_value("Student Applicant", name, "application_status", "Admitted")
		doc = self.run_import([file_row("TN001", rank=1)])
		self.assertEqual(self.counts(doc), (1, 0, 0, 0, 1))
		self.assertEqual(frappe.db.get_value("Student Applicant", name, "oc_rank"), 5)
		frappe.db.set_value("Student Applicant", name, "oc_company", OTHER_COLLEGE)
		doc = self.run_import([file_row("TN001", rank=5)])
		self.assertIn("another company", frappe.db.get_value("Allotment Import Row", {"allotment_import": doc.name}, "message"))

	def test_blank_cells_do_not_overwrite_stored_values(self):
		self.run_import([file_row("TN001", rank=5, cutoff="180")])
		doc = self.run_import([file_row("TN001", rank=5, cutoff="")])
		self.assertEqual(self.counts(doc), (1, 0, 0, 1, 0))
		self.assertEqual(self.applicants()[0].oc_cutoff, 180)

	def test_the_allotment_key_is_unique_in_the_database(self):
		self.run_import([file_row("TN001")])
		with self.assertRaises(frappe.UniqueValidationError):
			make_applicant(oc_counselling_authority=AUTHORITY, oc_allotment_no="TN001")
		manual = make_applicant(oc_counselling_authority=AUTHORITY, oc_allotment_no="TN777")  # validate fills the key
		self.assertEqual(manual.oc_allotment_key, f"{AUTHORITY}:TN777")
		self.assertIsNone(make_applicant().oc_allotment_key)

	def test_aadhaar_column_is_never_imported(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{"doctype": "Counselling Authority", "authority_name": "Seat Aadhaar Auth",
				 "column_mapping": [{"source_column": "Aadhaar", "target_field": "oc_aadhaar"}]}
			).insert()  # fmt: skip
		doc = frappe.get_doc(
			{"doctype": "Allotment Import", "company": COLLEGE, "counselling_authority": AUTHORITY, "academic_year": year(), "import_file": "/f.csv", "program_mapping": [{"source_code": "CS", "program": PROGRAM}]}
		).insert()  # fmt: skip
		mapped = {**allotment_import.column_mapping(AUTHORITY), "aadhaar": "oc_aadhaar"}  # a mapping that slipped in directly
		items = allotment_import.build_items(doc, mapped, [HEADER, file_row("TN001")])
		self.assertNotIn("234123412346", frappe.as_json(items))
		self.run_import([file_row("TN001")])
		row = frappe.get_doc("Student Applicant", self.applicants()[0].name)
		self.assertFalse(row.get_password("oc_aadhaar", raise_exception=False))
		self.assertNotIn("234123412346", frappe.as_json(frappe.get_all("Allotment Import Row", fields=["*"])))

	def test_import_refreshes_the_allotted_count_of_the_matrix(self):
		matrix = self.matrix([(GOVT, OC, 10), (GOVT, BC, 10)])
		self.run_import([file_row("TN001"), file_row("TN002"), file_row("TN003", community=BC)])
		self.assertEqual((self.row(matrix, GOVT, OC).allotted, self.row(matrix, GOVT, BC).allotted), (2, 1))

	def test_missing_columns_and_unmapped_identity_fail_before_queueing(self):
		doc = frappe.get_doc(
			{"doctype": "Allotment Import", "company": COLLEGE, "counselling_authority": AUTHORITY, "academic_year": year(), "import_file": "/f.csv", "program_mapping": [{"source_code": "CS", "program": PROGRAM}]}
		).insert()  # fmt: skip
		with patch.object(allotment_import, "read_file", return_value=b"Allotment No,Name\nA1,x\n"), patch.object(bulk, "enqueue_run"):
			with self.assertRaises(frappe.ValidationError):
				allotment_import.start_import(doc.name)
		self.assertEqual(frappe.db.get_value("Allotment Import", doc.name, "status"), "Draft")

	def test_program_mapping_must_belong_to_the_company_and_start_is_once_only(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "Allotment Import", "company": COLLEGE, "counselling_authority": AUTHORITY, "academic_year": year(), "import_file": "/f.csv", "program_mapping": [{"source_code": "CS", "program": OTHER_PROGRAM}]}).insert()  # fmt: skip
		doc = self.run_import([file_row("TN001")])
		with self.assertRaises(frappe.ValidationError):
			allotment_import.start_import(doc.name)

	def test_xlsx_files_are_read(self):
		from frappe.utils.xlsxutils import make_xlsx

		content = make_xlsx([HEADER, file_row("TN001")], "Allotment").getvalue()
		with patch.object(allotment_import, "read_file", return_value=content):
			rows = allotment_import.parse_file("/files/tnea.xlsx")
		self.assertEqual(rows[1][0], "TN001")
		self.assertEqual(rows[0], HEADER)


class TestDocumentVerification(SeatTestCase):
	def rule(self, document_type, mandatory=1, verification_needed=1, **applies_to):
		return frappe.get_doc(
			{"doctype": "Admission Document Rule", "document_type": document_type, "mandatory": mandatory, "verification_needed": verification_needed, **applies_to}
		).insert()  # fmt: skip

	def statuses(self, applicant):
		doc = frappe.get_doc("Student Applicant", applicant if isinstance(applicant, str) else applicant.name)
		return {r.document_type: r.status for r in doc.oc_documents}

	def test_checklist_is_built_from_the_applicable_rules_only(self):
		self.rule("Transfer Certificate")
		self.rule("Community Certificate", student_category=BC)
		self.rule("Sports Certificate", quota=MGMT)
		self.rule("Lateral Diploma", admission_type="Lateral")
		self.rule("Original Marksheet", original_retained=1, mandatory=0)
		applicant = make_applicant(student_category=BC)
		self.assertEqual(
			self.statuses(applicant),
			{"Transfer Certificate": "Pending", "Community Certificate": "Pending", "Original Marksheet": "Pending"},
		)
		row = {r.document_type: r for r in frappe.get_doc("Student Applicant", applicant.name).oc_documents}
		self.assertEqual((row["Transfer Certificate"].mandatory, row["Original Marksheet"].mandatory, row["Original Marksheet"].original_required), (1, 0, 1))

	def test_resaving_is_idempotent_and_keeps_statuses(self):
		self.rule("Transfer Certificate")
		applicant = make_applicant()
		doc = frappe.get_doc("Student Applicant", applicant.name)
		doc.oc_documents[0].status = "Submitted"
		doc.save()
		doc.save()
		frappe.get_doc("Student Applicant", applicant.name).save()
		self.assertEqual(self.statuses(applicant), {"Transfer Certificate": "Submitted"})

	def test_changing_quota_type_or_category_updates_the_checklist(self):
		self.rule("Transfer Certificate")
		self.rule("Sports Certificate", quota=MGMT)
		applicant = make_applicant()
		self.assertEqual(set(self.statuses(applicant)), {"Transfer Certificate"})
		doc = frappe.get_doc("Student Applicant", applicant.name)
		doc.oc_admission_quota = MGMT
		doc.save()
		self.assertEqual(set(self.statuses(applicant)), {"Transfer Certificate", "Sports Certificate"})
		doc.oc_documents[1].status = "Submitted"  # work already done on a document is kept...
		doc.oc_admission_quota = GOVT
		doc.save()
		self.assertIn("Sports Certificate", self.statuses(applicant))
		doc.oc_documents[1].status = "Pending"  # ...but a Pending row of a rule that no longer applies is dropped
		doc.save()
		self.assertEqual(set(self.statuses(applicant)), {"Transfer Certificate"})

	def test_two_rules_for_one_document_give_one_row_with_the_stricter_flags(self):
		self.rule("Transfer Certificate", mandatory=0, verification_needed=0)
		self.rule("Transfer Certificate", mandatory=1, verification_needed=1, student_category=OC)
		doc = frappe.get_doc("Student Applicant", make_applicant().name)
		self.assertEqual([(r.document_type, r.mandatory, r.verification_needed) for r in doc.oc_documents], [("Transfer Certificate", 1, 1)])

	def test_documents_complete_needs_verification_where_the_rule_says_so(self):
		self.rule("Transfer Certificate")
		self.rule("Photo", verification_needed=0)
		self.rule("Hobby Note", mandatory=0)
		applicant = make_applicant().name
		self.assertFalse(documents_complete(applicant))
		self.assertEqual(sorted(pending_documents(applicant)), ["Photo", "Transfer Certificate"])
		frappe.set_user(VERIFIER)
		set_document_status(applicant, "Photo", "Submitted")  # no verification needed: submitting completes it
		self.assertEqual(pending_documents(applicant), ["Transfer Certificate"])
		set_document_status(applicant, "Transfer Certificate", "Submitted")
		self.assertFalse(documents_complete(applicant))  # still needs the verifier
		result = set_document_status(applicant, "Transfer Certificate", "Verified", original_retained=1)
		self.assertEqual(result, {"complete": True, "status": "Verified"})
		self.assertTrue(documents_complete(applicant))  # the optional note does not matter

	def test_only_a_verifier_may_verify_or_reject_and_it_is_stamped(self):
		self.rule("Transfer Certificate")
		applicant = make_applicant().name
		for user in (PLAIN, OVERRIDER):
			frappe.set_user(user)
			with self.assertRaises(frappe.ValidationError):
				set_document_status(applicant, "Transfer Certificate", "Verified")
			set_document_status(applicant, "Transfer Certificate", "Submitted")  # anyone with write access may submit
			frappe.set_user("Administrator")
		frappe.set_user(VERIFIER)
		with self.assertRaises(frappe.ValidationError):
			set_document_status(applicant, "Transfer Certificate", "Rejected")  # needs remarks
		set_document_status(applicant, "Transfer Certificate", "Rejected", remarks="blurred scan")
		row = frappe.get_doc("Student Applicant", applicant).oc_documents[0]
		self.assertEqual((row.status, row.verified_by, row.remarks), ("Rejected", VERIFIER, "blurred scan"))
		self.assertTrue(row.verified_on)
		set_document_status(applicant, "Transfer Certificate", "Pending")
		row = frappe.get_doc("Student Applicant", applicant).oc_documents[0]
		self.assertEqual((row.status, row.verified_by, row.verified_on), ("Pending", None, None))

	def test_unknown_document_is_refused(self):
		applicant = make_applicant().name
		with self.assertRaises(frappe.ValidationError):
			set_document_status(applicant, "No Such Document", "Submitted")

	def test_applicant_with_a_pending_mandatory_document_cannot_be_admitted(self):
		self.rule("Transfer Certificate")
		applicant = make_applicant().name
		doc = frappe.get_doc("Student Applicant", applicant)
		doc.application_status = "Admitted"
		with self.assertRaises(frappe.ValidationError) as ctx:
			doc.save()
		self.assertIn("Transfer Certificate", str(ctx.exception))
		frappe.set_user(VERIFIER)
		set_document_status(applicant, "Transfer Certificate", "Verified")
		frappe.set_user("Administrator")
		doc = frappe.get_doc("Student Applicant", applicant)
		doc.application_status = "Admitted"
		doc.save()  # cleared: now allowed
		self.assertEqual(frappe.db.get_value("Student Applicant", applicant, "application_status"), "Admitted")

	def test_pending_documents_report_lists_open_applicants_of_the_company_only(self):
		self.rule("Transfer Certificate")
		mine = make_applicant().name
		done = make_applicant().name
		admitted = make_applicant().name
		frappe.set_user(VERIFIER)
		set_document_status(done, "Transfer Certificate", "Verified")
		frappe.set_user("Administrator")
		frappe.db.set_value("Student Applicant", admitted, "application_status", "Admitted")
		rows = pending_report.execute({"company": COLLEGE})[1]
		self.assertEqual([(r["applicant"], r["document_type"], r["status"]) for r in rows], [(mine, "Transfer Certificate", "Pending")])
		frappe.set_user(OUTSIDER)
		self.assertEqual(pending_report.execute({"company": COLLEGE})[1], [])


class TestDocumentReminders(SeatTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.delete("Student Applicant", {"program": PROGRAM})
		frappe.db.delete("Message Log", {"event_key": documents.REMINDER_EVENT})
		documents_rule = frappe.get_doc({"doctype": "Admission Document Rule", "document_type": "Transfer Certificate", "mandatory": 1, "verification_needed": 1})
		documents_rule.insert()

	def applicant(self, mobile="+919876500001", **values):
		return make_applicant(student_mobile_number=mobile, **values).name

	def test_selection_is_open_applicants_with_pending_mandatory_documents_and_a_mobile(self):
		pending = self.applicant()
		rejected = self.applicant()
		frappe.db.set_value("Applicant Document", {"parent": rejected}, "status", "Rejected")
		cleared = self.applicant()
		frappe.db.set_value("Applicant Document", {"parent": cleared}, "status", "Verified")
		admitted = self.applicant()
		frappe.db.set_value("Student Applicant", admitted, "application_status", "Admitted")
		self.applicant(mobile=None)  # nobody to message
		optional = self.applicant()
		frappe.db.set_value("Applicant Document", {"parent": optional}, "mandatory", 0)
		items = documents.reminder_items()
		self.assertEqual(sorted(i["applicant"] for i in items), sorted([pending, rejected]))
		self.assertEqual(next(i for i in items if i["applicant"] == pending)["documents"], ["Transfer Certificate"])

	def test_daily_job_queues_one_bulk_run_and_does_nothing_when_nothing_is_pending(self):
		self.applicant()
		with patch.object(documents, "run_bulk", return_value="BULK-1") as run_bulk:
			self.assertEqual(documents.send_daily_reminders("2026-10-05"), "BULK-1")
		args, kwargs = run_bulk.call_args
		self.assertEqual((len(args[1]), args[2], kwargs["parameters"]), (1, documents.REMINDER_HANDLER, {"day": "2026-10-05"}))
		frappe.db.delete("Student Applicant", {"program": PROGRAM})
		with patch.object(documents, "run_bulk") as run_bulk:
			self.assertIsNone(documents.send_daily_reminders())
		run_bulk.assert_not_called()

	def reminder_logs(self, applicant):
		return frappe.get_all("Message Log", {"event_key": documents.REMINDER_EVENT, "reference_name": applicant}, pluck="name")

	def test_a_reminder_goes_once_a_day_until_the_documents_are_cleared(self):
		applicant = self.applicant()
		registry = {c: (lambda *a, **k: "id") for c in ("email", "sms", "whatsapp", "push")}
		with patch.dict(channels.ADAPTERS, registry), patch.object(frappe.db, "commit"), patch.object(bulk, "enqueue_run"):
			for day in ("2026-10-05", "2026-10-05", "2026-10-06"):  # a repeat run on the same day adds nothing
				run = bulk.run_bulk(documents.REMINDER_RUN_TYPE, documents.reminder_items(), documents.REMINDER_HANDLER, key=documents.REMINDER_KEY, parameters={"day": day})
				bulk.process_bulk_run(run)
			self.assertEqual(len(self.reminder_logs(applicant)), 2)
			frappe.db.set_value("Applicant Document", {"parent": applicant}, "status", "Verified")
			self.assertEqual(documents.reminder_items(), [])  # cleared: no more reminders
		log = frappe.get_doc("Message Log", self.reminder_logs(applicant)[0])
		self.assertIn("Transfer Certificate", log.message)

	def test_reminder_handler_sends_the_template_with_the_day_as_dedupe_token(self):
		applicant = self.applicant()
		run = SimpleNamespace(get_parameters=lambda: {"day": "2026-10-07"})
		item = documents.reminder_items()[0]
		with patch.object(documents, "send") as send:
			documents.send_reminder(item, run)
		args, kwargs = send.call_args
		self.assertEqual((args[0], args[1].name, args[2]), (documents.REMINDER_EVENT, applicant, ["phone:+919876500001"]))
		self.assertEqual(kwargs["context"], {"documents": "Transfer Certificate", "dedupe_token": "2026-10-07"})

	def test_the_daily_job_is_scheduled(self):
		self.assertIn("campus.admissions.documents.send_daily_reminders", frappe.get_hooks("scheduler_events")["daily"])


class TestLiveSeatMatrixReport(SeatTestCase):
	def test_live_counts_are_scoped_to_the_company(self):
		matrix = self.matrix([(GOVT, OC, 3), (SUPER, OC, 0)])
		self.enrollment(GOVT, OC)
		frappe.db.set_value("Seat Matrix Row", {"parent": matrix.name}, "filled", 99)  # stale stored counts are ignored
		rows = live_seat_matrix.execute({"company": COLLEGE, "program": PROGRAM, "academic_year": year()})[1]
		by_quota = {r["quota"]: r for r in rows}
		self.assertEqual((by_quota[GOVT]["sanctioned"], by_quota[GOVT]["filled"], by_quota[GOVT]["vacant"], by_quota[GOVT]["supernumerary"]), (3, 1, 2, 0))
		self.assertEqual(by_quota[SUPER]["supernumerary"], 1)
		self.assertEqual(live_seat_matrix.execute({"company": COLLEGE, "program": OTHER_PROGRAM})[1], [])
		frappe.set_user(OUTSIDER)
		self.assertEqual(live_seat_matrix.execute({"company": COLLEGE})[1], [])
		frappe.set_user(PLAIN)
		self.assertEqual(len(live_seat_matrix.execute({"company": COLLEGE})[1]), 2)
