"""P1-T15 tests (M04-01, M04-02, M04-03): seat matrix, allotment import, document verification, reminders, reports."""

import csv
import io
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.utils import today

from campus.admissions import allotment_import, documents, seat_matrix
from campus.admissions.api import (
	check_seat_available,
	documents_complete,
	pending_documents,
	set_document_status,
)
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
OVERRIDER, PLAIN, VERIFIER, OUTSIDER = (
	f"seat-{r}@example.com" for r in ("override", "plain", "verifier", "outsider")
)
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
				"doctype": "Seat Matrix",
				"company": company,
				"program": program,
				"academic_year": year(),
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
		was_importing, frappe.flags.in_import = (
			frappe.flags.in_import,
			True,
		)  # skip the user-creation throttle
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
		self.assertEqual(
			dict(self.row(matrix, GOVT, OC)), {"sanctioned": 10, "allotted": 0, "filled": 0, "vacant": 10}
		)
		self.assertEqual(self.row(matrix, GOVT, BC).vacant, 5)

	def test_filled_counts_submitted_enrollments_only_and_cancel_frees_the_seat(self):
		matrix = self.matrix([(GOVT, OC, 3), (GOVT, BC, 3)])
		self.enrollment(GOVT, OC, submit=False)  # a draft is not a seat
		self.assertEqual(self.row(matrix, GOVT, OC).filled, 0)
		first = self.enrollment(GOVT, OC)
		self.enrollment(GOVT, OC)
		self.enrollment(GOVT, BC)
		self.assertEqual(
			dict(self.row(matrix, GOVT, OC)), {"sanctioned": 3, "allotted": 0, "filled": 2, "vacant": 1}
		)
		self.assertEqual(self.row(matrix, GOVT, BC).filled, 1)
		first.cancel()
		self.assertEqual(
			dict(self.row(matrix, GOVT, OC)), {"sanctioned": 3, "allotted": 0, "filled": 1, "vacant": 2}
		)

	def test_enrollment_without_a_matching_row_or_matrix_changes_nothing(self):
		matrix = self.matrix([(GOVT, OC, 3)])
		self.enrollment(MGMT, OC)  # no row for this quota
		self.enrollment(GOVT, MBC)  # no row for this category
		self.assertEqual(self.row(matrix, GOVT, OC).filled, 0)
		frappe.db.delete("Seat Matrix")
		self.enrollment(GOVT, OC)  # no matrix at all: no error

	def test_enforcement_uses_the_live_count_not_the_cached_filled(self):
		matrix = self.matrix([(GOVT, OC, 2), (GOVT, BC, 5)])
		self.enrollment(GOVT, OC)
		self.enrollment(GOVT, OC)
		frappe.db.set_value(
			"Seat Matrix Row", {"parent": matrix.name, "category": OC}, {"filled": 0, "vacant": 2}
		)  # stale cache
		frappe.set_user(PLAIN)
		with self.assertRaises(frappe.ValidationError):
			check_seat_available(PROGRAM, year(), GOVT, OC)
		frappe.set_user("Administrator")
		# a category edit after submit moves the seat with no drift
		name = frappe.db.get_value(
			"Program Enrollment", {"program": PROGRAM, "docstatus": 1, "student_category": OC}, "name"
		)
		frappe.db.set_value("Program Enrollment", name, "student_category", BC)
		frappe.set_user(PLAIN)
		self.assertIs(check_seat_available(PROGRAM, year(), GOVT, OC), True)
		frappe.set_user("Administrator")
		# an enrollment inserted straight into the database is counted too
		other = self.enrollment(GOVT, OC, submit=False)
		frappe.db.set_value("Program Enrollment", other.name, "docstatus", 1)
		frappe.set_user(PLAIN)
		with self.assertRaises(frappe.ValidationError):
			check_seat_available(PROGRAM, year(), GOVT, OC)

	def statements_of(self, action):
		"""Classify the SQL of `action()`: matrix locks, enrollment locks and enrollment writes, in order."""
		events, real_sql = [], frappe.db.sql

		def sql_spy(query, *args, **kwargs):
			text = str(query).lower()
			if "`tabseat matrix`" in text and "for update" in text:
				events.append("matrix lock")
			elif "`tabprogram enrollment`" in text and (
				"for update" in text or "lock in share mode" in text or text.startswith(("update", "insert"))
			):
				events.append("enrollment lock")
			return real_sql(query, *args, **kwargs)

		with patch.object(frappe.db, "sql", side_effect=sql_spy):
			action()
		return events

	def test_matrix_is_locked_before_any_lock_on_the_enrollment_row(self):
		self.matrix([(GOVT, OC, 2)])
		enrollment = self.enrollment(GOVT, OC, submit=False)
		for action in (enrollment.submit, enrollment.cancel):
			events = self.statements_of(action)  # includes check_if_latest's SELECT ... FOR UPDATE
			self.assertIn("matrix lock", events)
			self.assertLess(events.index("matrix lock"), events.index("enrollment lock"))
		submitted = frappe.get_doc("Program Enrollment", self.enrollment(GOVT, OC).name)
		events = self.statements_of(submitted.save)  # update after submit
		self.assertLess(events.index("matrix lock"), events.index("enrollment lock"))

	def test_insert_as_submitted_locks_the_matrix_first_and_counts(self):
		matrix = self.matrix([(GOVT, OC, 2)])
		doc = frappe.get_doc(
			{
				"doctype": "Program Enrollment", "student": self.student(), "program": PROGRAM, "academic_year": year(),
				"enrollment_date": today(), "student_category": OC, "oc_admission_quota": GOVT, "docstatus": 1,
			}
		)  # fmt: skip
		events = self.statements_of(doc.insert)
		self.assertIn("matrix lock", events)
		self.assertLess(events.index("matrix lock"), events.index("enrollment lock"))
		self.assertEqual(self.row(matrix, GOVT, OC).filled, 1)

	def test_the_nested_save_of_a_submit_does_not_lock_the_matrix_twice(self):
		self.matrix([(GOVT, OC, 2)])
		enrollment = self.enrollment(GOVT, OC, submit=False)
		self.assertEqual(self.statements_of(enrollment.submit).count("matrix lock"), 1)

	def test_old_and_new_matrices_are_locked_in_key_order_when_the_program_changes(self):
		self.matrix([(GOVT, OC, 2)])
		self.matrix([(GOVT, OC, 2)], program=OTHER_PROGRAM, company=OTHER_COLLEGE)
		enrollment = frappe.get_doc("Program Enrollment", self.enrollment(GOVT, OC).name)
		locked = []
		real_get = frappe.db.get_value

		def spy(doctype, filters=None, *args, **kwargs):
			if doctype == "Seat Matrix" and kwargs.get("for_update"):
				locked.append(filters["matrix_key"])
			return real_get(doctype, filters, *args, **kwargs)

		enrollment.program = OTHER_PROGRAM
		with patch.object(frappe.db, "get_value", side_effect=spy):
			seat_matrix.lock_matrices(enrollment)
		self.assertEqual(len(locked), 2)
		self.assertEqual(locked, sorted(locked))

	def test_count_is_blocking_and_uses_the_composite_index(self):
		self.assertTrue(frappe.db.has_index("tabProgram Enrollment", "oc_seat_count_index"))
		seen = []
		real_sql = frappe.db.sql
		frappe.db.sql = lambda query, *a, **k: (seen.append(str(query).lower()), real_sql(query, *a, **k))[1]
		try:
			seat_matrix.live_counts(COLLEGE, PROGRAM, year())
		finally:
			frappe.db.sql = real_sql
		self.assertIn("lock in share mode", seen[0])
		self.assertNotIn("skip locked", seen[0])
		plan = frappe.db.sql(
			"explain select oc_admission_quota from `tabProgram Enrollment` where oc_company=%s and program=%s and academic_year=%s and docstatus=1",
			(COLLEGE, PROGRAM, year()), as_dict=True,
		)  # fmt: skip
		self.assertEqual(plan[0]["key"], "oc_seat_count_index")

	def test_recount_rebuilds_the_cache_from_the_live_count(self):
		matrix = self.matrix([(GOVT, OC, 4)])
		self.enrollment(GOVT, OC)
		self.enrollment(GOVT, OC).cancel()
		frappe.db.set_value(
			"Seat Matrix Row", {"parent": matrix.name}, {"filled": 7, "vacant": -3}
		)  # simulate drift
		seat_matrix.recount_seat_matrix(matrix.name)
		self.assertEqual(
			dict(self.row(matrix, GOVT, OC)), {"sanctioned": 4, "allotted": 0, "filled": 1, "vacant": 3}
		)

	def test_saving_the_matrix_keeps_filled_and_a_new_row_is_counted_from_enrollments(self):
		matrix = self.matrix([(GOVT, OC, 4)])
		self.enrollment(GOVT, OC)
		self.enrollment(MGMT, BC)
		doc = frappe.get_doc("Seat Matrix", matrix.name)
		doc.rows[0].filled = 99  # a forged form value is ignored
		doc.rows[0].sanctioned = 6
		doc.append("rows", {"quota": MGMT, "category": BC, "sanctioned": 2})
		doc.save()
		self.assertEqual(
			dict(self.row(matrix, GOVT, OC)), {"sanctioned": 6, "allotted": 0, "filled": 1, "vacant": 5}
		)
		self.assertEqual(self.row(matrix, MGMT, BC).filled, 1)  # counted from the existing enrollment

	def test_allotted_counts_applicants_with_an_allotment_number(self):
		matrix = self.matrix([(GOVT, OC, 4)])
		self.applicant(oc_allotment_no="A1", oc_counselling_authority=self.authority())
		self.applicant(
			oc_allotment_no="A2", oc_counselling_authority=self.authority(), application_status="Rejected"
		)
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
				"doctype": "Counselling Authority",
				"authority_name": AUTHORITY,
				"column_mapping": [
					{"source_column": s, "target_field": t} for s, t in (mapping or MAPPING).items()
				],
			}
		).insert()
	return AUTHORITY


MAPPING = {
	"Allotment No": "oc_allotment_no",
	"Name": "first_name",
	"Branch": "program",
	"Community": "student_category",
	"Quota": "oc_admission_quota",
	"Rank": "oc_rank",
	"Cutoff": "oc_cutoff",
	"Mobile": "student_mobile_number",
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
		self.assertEqual(
			check_seat_available(PROGRAM, year(), GOVT, OC, applicant.name, "Court order"), "override"
		)
		frappe.set_user("Administrator")
		log = frappe.get_all("Seat Override Log", fields=["*"])
		self.assertEqual(len(log), 1)
		self.assertEqual(
			(
				log[0].user,
				log[0].company,
				log[0].program,
				log[0].quota,
				log[0].category,
				log[0].applicant,
				log[0].sanctioned,
				log[0].filled,
			),
			(OVERRIDER, COLLEGE, PROGRAM, GOVT, OC, applicant.name, 1, 1),
		)
		self.assertEqual(log[0].justification, "Court order")

	def test_an_override_without_a_justification_is_refused_and_not_logged(self):
		self.full_matrix()
		frappe.set_user(OVERRIDER)
		for blank in (None, "", "   "):
			with self.assertRaisesRegex(frappe.ValidationError, "justification"):
				check_seat_available(PROGRAM, year(), GOVT, OC, None, blank)
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.count("Seat Override Log"), 0)

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

	def test_supernumerary_quota_and_unconfigured_rows_are_not_enforced_outside_strict_mode(self):
		self.full_matrix()
		strict(False)
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


def strict(on):
	frappe.db.set_single_value("Admission Settings", "strict_seat_matrix", int(on))


class TestStrictSeatMatrix(SeatTestCase):
	"""M04-08: in strict mode a missing matrix or row refuses admission unless an override is logged."""

	def setUp(self):
		super().setUp()
		strict(True)

	def refused(self, program, quota, category, message):
		frappe.set_user(PLAIN)
		with self.assertRaises(frappe.ValidationError) as ctx:
			check_seat_available(program, year(), quota, category)
		frappe.set_user("Administrator")
		self.assertIn(message, str(ctx.exception))

	def overridden(self, program, quota, category):
		applicant = make_applicant()
		frappe.set_user(OVERRIDER)
		self.assertEqual(
			check_seat_available(program, year(), quota, category, applicant.name, "Sanction pending"),
			"override",
		)
		frappe.set_user("Administrator")
		return applicant.name

	def logs(self):
		return frappe.get_all(
			"Seat Override Log",
			fields=["program", "quota", "category", "applicant", "user", "reason", "sanctioned"],
		)

	def test_missing_row_is_refused_and_nothing_is_logged(self):
		self.matrix([(GOVT, OC, 5)])
		self.refused(PROGRAM, GOVT, MBC, "no row")
		self.assertEqual(frappe.db.count("Seat Override Log"), 0)

	def test_missing_matrix_is_refused(self):
		self.refused(OTHER_PROGRAM, GOVT, OC, "No Seat Matrix")

	def test_override_of_a_missing_row_admits_logs_the_reason_and_keeps_the_intake(self):
		matrix = self.matrix([(GOVT, OC, 5)])
		applicant = self.overridden(PROGRAM, GOVT, MBC)
		log = self.logs()
		self.assertEqual(len(log), 1)
		self.assertEqual(
			(
				log[0].program,
				log[0].quota,
				log[0].category,
				log[0].applicant,
				log[0].user,
				log[0].reason,
				log[0].sanctioned,
			),
			(PROGRAM, GOVT, MBC, applicant, OVERRIDER, "No Seat Matrix Row", 0),
		)
		rows = frappe.get_all("Seat Matrix Row", {"parent": matrix.name}, ["quota", "category", "sanctioned"])
		self.assertEqual(
			[(r.quota, r.category, r.sanctioned) for r in rows], [(GOVT, OC, 5)]
		)  # no row added, intake unchanged

	def test_override_of_a_missing_matrix_logs_and_creates_no_matrix(self):
		self.overridden(OTHER_PROGRAM, GOVT, OC)
		self.assertEqual([r.reason for r in self.logs()], ["No Seat Matrix"])
		self.assertEqual(frappe.db.count("Seat Matrix"), 0)

	def test_a_full_row_override_is_logged_as_row_full_and_keeps_the_sanctioned_seats(self):
		matrix = self.matrix([(GOVT, OC, 1)])
		self.enrollment(GOVT, OC)
		self.overridden(PROGRAM, GOVT, OC)
		self.assertEqual([(r.reason, r.sanctioned) for r in self.logs()], [("Row Full", 1)])
		self.assertEqual(self.row(matrix, GOVT, OC).sanctioned, 1)

	def test_supernumerary_quota_is_still_not_enforced(self):
		frappe.set_user(PLAIN)
		self.assertIs(check_seat_available(OTHER_PROGRAM, year(), SUPER, OC), True)
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.count("Seat Override Log"), 0)

	def test_a_configured_row_with_a_free_seat_is_allowed(self):
		self.matrix([(GOVT, OC, 2)])
		frappe.set_user(PLAIN)
		self.assertIs(check_seat_available(PROGRAM, year(), GOVT, OC), True)

	def test_strict_mode_is_seeded_on_once_and_a_stored_choice_is_kept(self):
		from campus.admissions.setup import seed_strict_seat_matrix

		frappe.db.delete("Singles", {"doctype": "Admission Settings", "field": "strict_seat_matrix"})
		seed_strict_seat_matrix()
		self.assertEqual(
			frappe.db.get_single_value("Admission Settings", "strict_seat_matrix", cache=False), 1
		)
		strict(False)
		seed_strict_seat_matrix()
		self.assertEqual(
			frappe.db.get_single_value("Admission Settings", "strict_seat_matrix", cache=False), 0
		)

	def test_a_missing_row_is_checked_under_the_matrix_lock(self):
		self.matrix([(GOVT, OC, 1)])
		real = frappe.db.get_value
		calls = []

		def spy(doctype, *args, **kwargs):
			calls.append((doctype, bool(kwargs.get("for_update"))))
			return real(doctype, *args, **kwargs)

		frappe.set_user(PLAIN)
		with patch.object(frappe.db, "get_value", side_effect=spy), self.assertRaises(frappe.ValidationError):
			check_seat_available(PROGRAM, year(), GOVT, MBC)
		frappe.set_user("Administrator")
		self.assertIn(("Seat Matrix", True), calls)
		self.assertIn(("Seat Matrix Row", True), calls)
		self.assertNotIn(("Seat Matrix Row", False), calls)


class TestProgramsWithoutSeatMatrix(SeatTestCase):
	"""M04-08 rollout check: the college's programs with no Seat Matrix for the year, with applicants still to join."""

	def test_lists_only_the_permitted_colleges_programs_without_a_matrix(self):
		from campus.admissions.report.programs_without_seat_matrix import (
			programs_without_seat_matrix as report,
		)
		from campus.tests.test_regulation import make_program

		bare = "Seat Test BE ECE"
		make_program(bare, COLLEGE)
		self.matrix([(GOVT, OC, 5)])
		for status in ("Approved", "Admitted", "Applied", "Rejected"):
			make_applicant(program=bare, application_status=status)
		filters = {"company": COLLEGE, "academic_year": year()}
		rows = report.execute(filters)[1]
		self.assertEqual(
			[(r["program"], r["applicants"]) for r in rows], [(bare, 2)]
		)  # Approved and Admitted wait to join
		self.assertEqual(report.execute({"company": COLLEGE})[1], [])  # the year is required
		frappe.set_user(OUTSIDER)
		self.assertEqual(report.execute(filters)[1], [])


def csv_bytes(rows):
	out = io.StringIO()
	csv.writer(out).writerows(rows)
	return out.getvalue().encode()


HEADER = [
	"Allotment No",
	"Name",
	"Branch",
	"Community",
	"Quota",
	"Rank",
	"Cutoff",
	"Mobile",
	"Aadhaar",
	"Remark",
]


def file_row(no, rank=100, cutoff="190.5", branch="CS", community=OC, name="default", quota=GOVT):
	return [
		no,
		f"Student {no}" if name == "default" else name,
		branch,
		community,
		quota,
		rank,
		cutoff,
		"9876500000",
		"234123412346",
		"x",
	]


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
			patch.object(allotment_import, "make_private"),
			patch.object(bulk, "enqueue_run"),
			patch.object(
				frappe.db, "commit"
			),  # keep the test transaction; the runner's chunk commit is a no-op
		):
			run = allotment_import.start_import(doc.name)
			bulk.process_bulk_run(run)
		return frappe.get_doc("Allotment Import", doc.name)

	def applicants(self):
		return frappe.get_all(
			"Student Applicant",
			{"oc_counselling_authority": AUTHORITY},
			[
				"name",
				"oc_rank",
				"oc_cutoff",
				"oc_allotment_key",
				"oc_company",
				"program",
				"student_category",
				"oc_admission_quota",
			],
			order_by="oc_allotment_no",
		)

	def counts(self, doc):
		return (doc.total_rows, doc.created_rows, doc.updated_rows, doc.unchanged_rows, doc.error_rows)

	def test_import_creates_applicants_with_mapped_fields(self):
		doc = self.run_import([file_row("TN001", rank=7, community=BC), file_row("TN002", rank=9)])
		self.assertEqual((doc.status, self.counts(doc)), ("Completed", (2, 2, 0, 0, 0)))
		first = self.applicants()[0]
		self.assertEqual(
			(
				first.oc_rank,
				first.oc_cutoff,
				first.oc_allotment_key,
				first.oc_company,
				first.program,
				first.student_category,
				first.oc_admission_quota,
			),
			(7, 190.5, f"{AUTHORITY}:TN001", COLLEGE, PROGRAM, BC, GOVT),
		)

	def test_importing_the_same_file_twice_creates_no_duplicates_and_updates_changed_ranks(self):
		rows = [file_row("TN001", rank=7), file_row("TN002", rank=9), file_row("TN003", rank=11)]
		first = self.run_import(rows)
		before = {a.name: a.oc_rank for a in self.applicants()}
		again = self.run_import(rows)
		self.assertEqual(self.counts(again), (3, 0, 0, 3, 0))
		self.assertEqual(
			{a.name: a.oc_rank for a in self.applicants()}, before
		)  # same applicants, nothing duplicated
		changed = self.run_import(
			[file_row("TN001", rank=7), file_row("TN002", rank=4, cutoff="195"), file_row("TN003", rank=11)]
		)
		self.assertEqual(self.counts(changed), (3, 0, 1, 2, 0))
		updated = next(a for a in self.applicants() if a.oc_allotment_key.endswith("TN002"))
		self.assertEqual(
			(updated.oc_rank, updated.oc_cutoff, updated.name),
			(4, 195, next(n for n, r in before.items() if r == 9)),
		)
		message = frappe.db.get_value(
			"Allotment Import Row", {"allotment_import": changed.name, "status": "Updated"}, "message"
		)
		self.assertIn("oc_cutoff", message)
		self.assertEqual(first.status, "Completed")

	def test_row_errors_are_listed_and_do_not_stop_the_import(self):
		doc = self.run_import(
			[
				file_row("TN001"),
				file_row(""),
				file_row("TN003", branch="XX"),
				file_row("TN004", name=""),
				file_row("TN005", community="NOPE"),
				file_row("TN006"),
			]
		)
		self.assertEqual((doc.status, self.counts(doc)), ("Completed with errors", (6, 2, 0, 0, 4)))
		errors = {
			r.row_no: r.message
			for r in frappe.get_all(
				"Allotment Import Row",
				{"allotment_import": doc.name, "status": "Error"},
				["row_no", "message"],
			)
		}
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
		row = frappe.db.get_value(
			"Allotment Import Row", {"allotment_import": doc.name}, ["message", "applicant"], as_dict=True
		)
		self.assertIn("another college", row.message)
		self.assertIsNone(row.applicant)  # the other college's applicant is not revealed

	def test_blank_cells_do_not_overwrite_stored_values(self):
		self.run_import([file_row("TN001", rank=5, cutoff="180")])
		doc = self.run_import([file_row("TN001", rank=5, cutoff="")])
		self.assertEqual(self.counts(doc), (1, 0, 0, 1, 0))
		self.assertEqual(self.applicants()[0].oc_cutoff, 180)

	def test_the_allotment_key_is_unique_in_the_database(self):
		self.run_import([file_row("TN001")])
		with self.assertRaises(frappe.UniqueValidationError):
			make_applicant(oc_counselling_authority=AUTHORITY, oc_allotment_no="TN001")
		manual = make_applicant(
			oc_counselling_authority=AUTHORITY, oc_allotment_no="TN777"
		)  # validate fills the key
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
		mapped = {
			**allotment_import.column_mapping(AUTHORITY),
			"aadhaar": "oc_aadhaar",
		}  # a mapping that slipped in directly
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
		with (
			patch.object(allotment_import, "read_file", return_value=b"Allotment No,Name\nA1,x\n"),
			patch.object(allotment_import, "make_private"),
			patch.object(bulk, "enqueue_run"),
		):
			with self.assertRaises(frappe.ValidationError):
				allotment_import.start_import(doc.name)
		self.assertEqual(frappe.db.get_value("Allotment Import", doc.name, "status"), "Draft")

	def test_program_mapping_must_belong_to_the_company_and_start_is_once_only(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "Allotment Import", "company": COLLEGE, "counselling_authority": AUTHORITY, "academic_year": year(), "import_file": "/f.csv", "program_mapping": [{"source_code": "CS", "program": OTHER_PROGRAM}]}).insert()  # fmt: skip
		doc = self.run_import([file_row("TN001")])
		with self.assertRaises(frappe.ValidationError):
			allotment_import.start_import(doc.name)

	def test_file_is_made_private_hashed_and_deleted_on_completion(self):
		import hashlib

		content = csv_bytes([HEADER, file_row("TN001")])
		file = frappe.get_doc(
			{"doctype": "File", "file_name": "seat-tnea.csv", "content": content, "is_private": 0}
		).insert()
		doc = frappe.get_doc(
			{"doctype": "Allotment Import", "company": COLLEGE, "counselling_authority": AUTHORITY, "academic_year": year(),
			 "import_file": file.file_url, "program_mapping": [{"source_code": "CS", "program": PROGRAM}]}
		).insert()  # fmt: skip
		frappe.db.set_value(
			"File", file.name, {"attached_to_doctype": "Allotment Import", "attached_to_name": doc.name}
		)
		with patch.object(bulk, "enqueue_run"), patch.object(frappe.db, "commit"):
			run = allotment_import.start_import(doc.name)
			self.assertEqual(frappe.db.get_value("File", file.name, "is_private"), 1)
			self.assertTrue(
				frappe.db.get_value("Allotment Import", doc.name, "import_file").startswith("/private/")
			)
			bulk.process_bulk_run(run)
		done = frappe.get_doc("Allotment Import", doc.name)
		self.assertEqual(
			(done.status, done.file_sha256, done.import_file),
			("Completed", hashlib.sha256(content).hexdigest(), None),
		)
		self.assertFalse(frappe.db.exists("File", file.name))
		frappe.db.after_rollback.reset()  # the file is gone for good: File's rollback hook would try to move it back

	def test_a_failing_outcome_row_is_replaced_by_a_generic_error_row(self):
		doc = frappe.get_doc(
			{
				"doctype": "Allotment Import",
				"company": COLLEGE,
				"counselling_authority": AUTHORITY,
				"academic_year": year(),
				"import_file": "/f.csv",
				"total_rows": 1,
			}
		).insert()
		boom = patch.object(allotment_import, "apply_row", side_effect=RuntimeError("deadlock-ish"))
		with (
			boom,
			patch.object(
				allotment_import, "record", side_effect=[RuntimeError("write failed"), None]
			) as record,
		):
			allotment_import.process_row({"import": doc.name, "row_no": 2, "allotment_no": "X"}, None)
		self.assertEqual(record.call_count, 2)

	def start_unprocessed_import(self, rows):
		doc = frappe.get_doc(
			{"doctype": "Allotment Import", "company": COLLEGE, "counselling_authority": AUTHORITY, "academic_year": year(), "import_file": "/files/tnea.csv", "program_mapping": [{"source_code": "cs", "program": PROGRAM}]}
		).insert()  # fmt: skip
		with (
			patch.object(allotment_import, "read_file", return_value=csv_bytes([HEADER, *rows])),
			patch.object(allotment_import, "make_private"),
			patch.object(bulk, "enqueue_run"),
			patch.object(frappe.db, "commit"),
		):
			return doc.name, allotment_import.start_import(doc.name)

	def process_with_lost_transaction(self, run, deadlock, dead_savepoints):
		"""Run the bulk run where TN002's row loses the whole transaction: a full rollback only returns to 'pre_run'."""
		real_apply, real_rollback = allotment_import.apply_row, frappe.db.rollback
		frappe.db.savepoint("pre_run")

		def apply(item):
			if (
				item["allotment_no"] == "TN001"
			):  # the first row: a full rollback to 'pre_run' loses nothing else
				raise frappe.QueryDeadlockError("deadlock found") if deadlock else RuntimeError("row failed")
			return real_apply(item)

		def rollback(*args, **kwargs):
			point = kwargs.get("save_point")
			if point in dead_savepoints:
				raise RuntimeError(f"SAVEPOINT {point} does not exist")
			return real_rollback(save_point=point or "pre_run")  # no argument = the full rollback

		with (
			patch.object(allotment_import, "apply_row", side_effect=apply),
			patch.object(frappe.db, "rollback", side_effect=rollback),
			patch.object(frappe.db, "commit"),
		):
			bulk.process_bulk_run(run)

	def assert_import_completes_with_an_error_row(self, name, run):
		self.assertEqual(
			frappe.db.get_value("Bulk Run", run, ["status", "failed", "done"]),
			("Completed with errors", 1, 2),
		)
		self.assertEqual(
			frappe.db.get_value("Allotment Import", name, "status"), "Processing"
		)  # the failed item has no row yet
		allotment_import.reconcile(name)
		done = frappe.get_doc("Allotment Import", name)
		self.assertEqual((done.status, done.created_rows, done.error_rows), ("Completed with errors", 2, 1))
		errors = frappe.get_all(
			"Allotment Import Row", {"allotment_import": name, "status": "Error"}, ["row_no", "message"]
		)
		self.assertEqual([e.row_no for e in errors], [2])  # file row 2 = TN001
		allotment_import.reconcile(name)  # idempotent
		self.assertEqual(frappe.db.get_value("Allotment Import", name, "error_rows"), 1)

	def test_real_deadlock_loses_every_savepoint_and_the_run_still_completes(self):
		name, run = self.start_unprocessed_import([file_row("TN001"), file_row("TN002"), file_row("TN003")])
		self.process_with_lost_transaction(run, deadlock=True, dead_savepoints=())
		self.assert_import_completes_with_an_error_row(name, run)

	def test_dead_row_and_runner_savepoints_are_handled_like_a_deadlock(self):
		name, run = self.start_unprocessed_import([file_row("TN001"), file_row("TN002"), file_row("TN003")])
		self.process_with_lost_transaction(
			run, deadlock=False, dead_savepoints=(allotment_import.SAVEPOINT, bulk.SAVEPOINT)
		)
		self.assert_import_completes_with_an_error_row(name, run)

	def test_a_lost_transaction_redoes_the_rest_of_a_larger_chunk(self):
		CHUNK_CALLS.clear()
		with patch.object(bulk, "enqueue_run"), patch.object(frappe.db, "commit"):
			run = bulk.run_bulk(
				"T15 chunk",
				[{"n": n} for n in range(4)],
				"campus.tests.test_seats_allotments.chunk_handler",
				chunk=4,
			)
			frappe.db.savepoint("pre_run")
			real_rollback = frappe.db.rollback
			with patch.object(
				frappe.db,
				"rollback",
				side_effect=lambda *a, **k: real_rollback(save_point=k.get("save_point") or "pre_run"),
			):
				bulk.process_bulk_run(run)
		self.assertEqual(
			frappe.db.get_value("Bulk Run", run, ["status", "done", "failed"]),
			("Completed with errors", 3, 1),
		)
		self.assertEqual(
			CHUNK_CALLS, [0, 1, 0, 2, 3]
		)  # item 1 failed for good; item 0 was redone after the rollback

	def test_a_failed_run_is_reconciled_with_not_processed_rows(self):
		name, run = self.start_unprocessed_import([file_row("TN001"), file_row("TN002")])
		frappe.db.set_value("Bulk Run", run, "status", "Failed")
		allotment_import.reconcile(name)
		done = frappe.get_doc("Allotment Import", name)
		self.assertEqual((done.status, done.error_rows), ("Completed with errors", 2))
		self.assertTrue(
			all(
				"Not processed" in m
				for m in frappe.get_all("Allotment Import Row", {"allotment_import": name}, pluck="message")
			)
		)

	def test_one_bad_import_does_not_stop_the_hourly_reconcile(self):
		first, run1 = self.start_unprocessed_import([file_row("TN001")])
		second, run2 = self.start_unprocessed_import([file_row("TN002")])
		for run in (run1, run2):
			frappe.db.set_value("Bulk Run", run, "status", "Failed")
		real = allotment_import.reconcile

		def flaky(name):
			if name == second:  # processed first (newest first): the failure must not undo the other import
				raise RuntimeError("boom")
			return real(name)

		frappe.db.savepoint("pre_hourly")
		real_rollback = frappe.db.rollback
		with (
			patch.object(allotment_import, "reconcile", side_effect=flaky),
			patch.object(frappe.db, "commit"),
			patch.object(frappe, "log_error") as log,
			patch.object(
				frappe.db, "rollback", side_effect=lambda *a, **k: real_rollback(save_point="pre_hourly")
			),
		):
			allotment_import.reconcile_finished_imports()
		self.assertEqual(frappe.db.get_value("Allotment Import", first, "status"), "Completed with errors")
		self.assertEqual(log.call_count, 1)

	def test_a_same_named_private_file_does_not_block_make_private(self):
		import os

		path = frappe.get_site_path("private", "files", "seat-clash.csv")
		with open(path, "w") as f:
			f.write("someone else's file")
		self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
		file = frappe.get_doc(
			{"doctype": "File", "file_name": "seat-clash.csv", "content": b"a,b\n1,2\n", "is_private": 0}
		).insert()
		public = frappe.get_site_path("public", "files", file.file_name)
		url = allotment_import.make_private(file.file_url)
		self.addCleanup(
			lambda: os.path.exists(frappe.get_site_path(url.lstrip("/")))
			and os.remove(frappe.get_site_path(url.lstrip("/")))
		)
		self.assertTrue(url.startswith("/private/files/seat-clash-"))
		self.assertEqual(frappe.db.get_value("File", {"file_url": url}, "is_private"), 1)
		self.assertEqual(open(path).read(), "someone else's file")  # the other file is untouched
		self.assertFalse(os.path.exists(public))  # the allotment data is no longer readable at its public url
		frappe.db.after_rollback.reset()

	def test_long_digit_runs_are_masked_in_stored_messages(self):
		self.assertEqual(
			allotment_import.mask_numbers("bad 234123412346 and 98765"), "bad XXXXXXXXXXXX and 98765"
		)
		self.assertEqual(allotment_import.mask_numbers("<b>9876543210</b>"), "XXXXXXXXXX")

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
			{
				"Transfer Certificate": "Pending",
				"Community Certificate": "Pending",
				"Original Marksheet": "Pending",
			},
		)
		row = {r.document_type: r for r in frappe.get_doc("Student Applicant", applicant.name).oc_documents}
		self.assertEqual(
			(
				row["Transfer Certificate"].mandatory,
				row["Original Marksheet"].mandatory,
				row["Original Marksheet"].original_required,
			),
			(1, 0, 1),
		)

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
		doc.oc_documents[
			1
		].status = "Pending"  # ...but a Pending row of a rule that no longer applies is dropped
		doc.save()
		self.assertEqual(set(self.statuses(applicant)), {"Transfer Certificate"})

	def test_two_rules_for_one_document_give_one_row_with_the_stricter_flags(self):
		self.rule("Transfer Certificate", mandatory=0, verification_needed=0)
		self.rule("Transfer Certificate", mandatory=1, verification_needed=1, student_category=OC)
		doc = frappe.get_doc("Student Applicant", make_applicant().name)
		self.assertEqual(
			[(r.document_type, r.mandatory, r.verification_needed) for r in doc.oc_documents],
			[("Transfer Certificate", 1, 1)],
		)

	def test_documents_complete_needs_verification_where_the_rule_says_so(self):
		self.rule("Transfer Certificate")
		self.rule("Photo", verification_needed=0)
		self.rule("Hobby Note", mandatory=0)
		applicant = make_applicant().name
		self.assertFalse(documents_complete(applicant))
		self.assertEqual(sorted(pending_documents(applicant)), ["Photo", "Transfer Certificate"])
		frappe.set_user(VERIFIER)
		set_document_status(
			applicant, "Photo", "Submitted"
		)  # no verification needed: submitting completes it
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
			set_document_status(
				applicant, "Transfer Certificate", "Submitted"
			)  # anyone with write access may submit
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

	def test_only_a_verifier_may_reopen_a_verified_document(self):
		self.rule("Transfer Certificate")
		applicant = make_applicant().name
		frappe.set_user(VERIFIER)
		set_document_status(applicant, "Transfer Certificate", "Verified")
		frappe.set_user(PLAIN)
		for status in ("Pending", "Submitted"):
			with self.assertRaises(frappe.ValidationError):
				set_document_status(applicant, "Transfer Certificate", status)
		frappe.set_user(VERIFIER)
		set_document_status(applicant, "Transfer Certificate", "Submitted")

	def test_a_verified_row_cannot_be_deleted_by_a_non_verifier(self):
		self.rule("Transfer Certificate", mandatory=0)
		applicant = make_applicant().name
		frappe.set_user(VERIFIER)
		set_document_status(applicant, "Transfer Certificate", "Verified")
		frappe.set_user(PLAIN)
		doc = frappe.get_doc("Student Applicant", applicant)
		doc.oc_documents = []
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		frappe.set_user(VERIFIER)
		doc = frappe.get_doc("Student Applicant", applicant)
		doc.oc_documents = []
		doc.save()  # a verifier may (the rule then re-adds the row, but the removal is allowed)

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
		self.assertEqual(
			frappe.db.get_value("Student Applicant", applicant, "application_status"), "Admitted"
		)

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
		self.assertEqual(
			[(r["applicant"], r["document_type"], r["status"]) for r in rows],
			[(mine, "Transfer Certificate", "Pending")],
		)
		frappe.set_user(OUTSIDER)
		self.assertEqual(pending_report.execute({"company": COLLEGE})[1], [])


class TestDocumentReminders(SeatTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.delete("Student Applicant", {"program": PROGRAM})
		frappe.db.delete("Message Log", {"event_key": documents.REMINDER_EVENT})
		documents_rule = frappe.get_doc(
			{
				"doctype": "Admission Document Rule",
				"document_type": "Transfer Certificate",
				"mandatory": 1,
				"verification_needed": 1,
			}
		)
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
		self.assertEqual(
			next(i for i in items if i["applicant"] == pending)["documents"], ["Transfer Certificate"]
		)

	def test_daily_job_queues_one_bulk_run_and_does_nothing_when_nothing_is_pending(self):
		self.applicant()
		with patch.object(documents, "run_bulk", return_value="BULK-1") as run_bulk:
			self.assertEqual(documents.send_daily_reminders("2026-10-05"), "BULK-1")
		args, kwargs = run_bulk.call_args
		self.assertEqual(
			(len(args[1]), args[2], kwargs["parameters"]),
			(1, documents.REMINDER_HANDLER, {"day": "2026-10-05"}),
		)
		frappe.db.delete("Student Applicant", {"program": PROGRAM})
		with patch.object(documents, "run_bulk") as run_bulk:
			self.assertIsNone(documents.send_daily_reminders())
		run_bulk.assert_not_called()

	def reminder_logs(self, applicant):
		return frappe.get_all(
			"Message Log", {"event_key": documents.REMINDER_EVENT, "reference_name": applicant}, pluck="name"
		)

	def test_a_reminder_goes_once_a_day_until_the_documents_are_cleared(self):
		applicant = self.applicant()
		registry = {c: (lambda *a, **k: "id") for c in ("email", "sms", "whatsapp", "push")}
		with (
			patch.dict(channels.ADAPTERS, registry),
			patch.object(frappe.db, "commit"),
			patch.object(bulk, "enqueue_run"),
		):
			for day in (
				"2026-10-05",
				"2026-10-05",
				"2026-10-06",
			):  # a repeat run on the same day adds nothing
				run = bulk.run_bulk(
					documents.REMINDER_RUN_TYPE,
					documents.reminder_items(),
					documents.REMINDER_HANDLER,
					key=documents.REMINDER_KEY,
					parameters={"day": day},
				)
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
		self.assertEqual(
			(args[0], args[1].name, args[2]), (documents.REMINDER_EVENT, applicant, ["phone:+919876500001"])
		)
		self.assertEqual(
			kwargs["context"], {"documents": "Transfer Certificate", "dedupe_token": "2026-10-07"}
		)

	def test_the_daily_job_is_scheduled(self):
		self.assertIn(
			"campus.admissions.documents.send_daily_reminders", frappe.get_hooks("scheduler_events")["daily"]
		)


class TestLiveSeatMatrixReport(SeatTestCase):
	def test_live_counts_are_scoped_to_the_company(self):
		matrix = self.matrix([(GOVT, OC, 3), (SUPER, OC, 0)])
		self.enrollment(GOVT, OC)
		frappe.db.set_value(
			"Seat Matrix Row", {"parent": matrix.name}, "filled", 99
		)  # stale stored counts are ignored
		rows = live_seat_matrix.execute({"company": COLLEGE, "program": PROGRAM, "academic_year": year()})[1]
		by_quota = {r["quota"]: r for r in rows}
		self.assertEqual(
			(
				by_quota[GOVT]["sanctioned"],
				by_quota[GOVT]["filled"],
				by_quota[GOVT]["vacant"],
				by_quota[GOVT]["supernumerary"],
			),
			(3, 1, 2, 0),
		)
		self.assertEqual(by_quota[SUPER]["supernumerary"], 1)
		self.assertEqual(live_seat_matrix.execute({"company": COLLEGE, "program": OTHER_PROGRAM})[1], [])
		frappe.set_user(OUTSIDER)
		self.assertEqual(live_seat_matrix.execute({"company": COLLEGE})[1], [])
		frappe.set_user(PLAIN)
		self.assertEqual(len(live_seat_matrix.execute({"company": COLLEGE})[1]), 2)


CHUNK_CALLS = []


def chunk_handler(item, run):
	"""Bulk handler for the lost-transaction test: item 1 deadlocks the first time it runs."""
	CHUNK_CALLS.append(item["n"])
	frappe.db.sql("select 1")
	if item["n"] == 1 and CHUNK_CALLS.count(1) == 1:
		raise frappe.QueryDeadlockError("deadlock found")


class TestAdmitDeadlockRetry(SeatTestCase):
	def test_a_deadlock_is_retried_once_then_reported_as_busy(self):
		from campus.admissions import admit as admit_module

		deadlock = frappe.QueryDeadlockError("deadlock found")
		with patch.object(frappe, "only_for"), patch.object(frappe.db, "rollback") as rollback:
			with patch.object(admit_module, "admit_once", side_effect=[deadlock, {"student": "S"}]) as once:
				self.assertEqual(admit_module.admit("APP-1"), {"student": "S"})
			self.assertEqual((once.call_count, rollback.call_count), (2, 1))
			rollback.reset_mock()
			with patch.object(admit_module, "admit_once", side_effect=[deadlock, deadlock]) as once:
				with self.assertRaises(frappe.ValidationError) as ctx:
					admit_module.admit("APP-1")
			self.assertEqual((once.call_count, rollback.call_count), (2, 2))
			self.assertIn("busy", str(ctx.exception))

	def test_a_joining_deadlock_is_retried_and_not_masked_by_the_savepoint_rollback(self):
		from campus.admissions import joining

		deadlock = frappe.QueryDeadlockError("deadlock found")
		with patch.object(frappe, "only_for"), patch.object(frappe.db, "rollback") as rollback:
			with patch.object(joining, "join_once", side_effect=[deadlock, {"student": "S"}]) as once:
				self.assertEqual(joining.confirm_joining("APP-1"), {"student": "S"})
			self.assertEqual((once.call_count, rollback.call_count), (2, 1))
		with (
			patch.object(joining, "lock_applicant", return_value=frappe._dict()),
			patch.object(joining, "check_company_access"),
			patch.object(joining, "lock_student", return_value=frappe._dict(oc_academic_status="Admitted")),
			patch.object(joining, "check_joinable"),
			patch.object(joining, "join", side_effect=deadlock),
			patch.object(
				frappe.db, "rollback", side_effect=RuntimeError("SAVEPOINT campus_joining does not exist")
			),
			patch.object(frappe.db, "savepoint"),
		):
			with self.assertRaises(frappe.QueryDeadlockError):
				joining.join_once("APP-1", None, None)

	def test_a_deadlock_inside_the_admission_is_not_masked_by_the_savepoint_rollback(self):
		from campus.admissions import admit as admit_module

		state = frappe._dict()
		with (
			patch.object(admit_module, "lock_applicant", return_value=state),
			patch.object(admit_module, "check_company_access"),
			patch.object(admit_module, "check_admittable"),
			patch.object(
				admit_module, "create_admission", side_effect=frappe.QueryDeadlockError("deadlock found")
			),
			patch.object(
				frappe.db, "rollback", side_effect=RuntimeError("SAVEPOINT campus_admit does not exist")
			),
			patch.object(frappe.db, "savepoint"),
		):
			with self.assertRaises(frappe.QueryDeadlockError):
				admit_module.admit_once("APP-1")
