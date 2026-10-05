"""P1-T16 tests (M04-01, M04-04): Admit transaction, register numbers, cancellation refund, prints and reports."""

import threading
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.utils import add_days, flt, today

from campus.admissions import admit as admit_module
from campus.admissions import numbers, refund
from campus.admissions.api import admit, check_seat_available
from campus.admissions.report.admissions_by_quota_and_category import admissions_by_quota_and_category as quota_report
from campus.admissions.report.refund_register import refund_register
from campus.tests.factories import make_company, make_user
from campus.tests.finance_factories import make_finance_company, make_fee_structure
from campus.tests.test_admissions import VALID, delete_log_rows, log_rows, own_connection
from campus.tests.utils import CampusTestCase

COLLEGE, ABBR = "Admit Flow College", "AFC"
PROGRAM, CODE = "Admit Flow BE CSE", "CS"
YEAR = "Admit Flow 2026"
QUOTA, FREE_QUOTA = "AFGQ", "AFMQ"
OC, BC = "AF OC", "AF BC"
OFFICER, PLAIN = "admit-officer@example.com", "admit-plain@example.com"
OTHER_COLLEGE, OTHER_OFFICER = "Admit Flow Other College", "admit-other@example.com"
TUITION_FEE, EXAM_FEE, BC_TUITION = 50000, 2000, 30000
SERIAL = [0]


def slab(from_day, to_day, percent=0, fee=0):
	return SimpleNamespace(days_from_admission_start=from_day, days_to_admission_start=to_day, deduction_percent=percent, processing_fee=fee)


class TestRefundCalculation(CampusTestCase):
	"""The pure refund functions: every branch."""

	slabs = [slab(0, 15, fee=1000), slab(16, 30, percent=20), slab(31, 60, percent=50, fee=500)]

	def test_days_since_start_never_negative(self):
		self.assertEqual(refund.days_since_start("2026-07-01", "2026-07-11"), 10)
		self.assertEqual(refund.days_since_start("2026-07-01", "2026-07-01"), 0)
		self.assertEqual(refund.days_since_start("2026-07-01", "2026-06-20"), 0)

	def test_full_refund_less_processing_fee_before_the_cutoff(self):
		result = refund.refund_for(self.slabs, 15, 52000)
		self.assertEqual((result["deduction"], result["refundable"]), (1000, 51000))

	def test_percent_deduction_after_the_cutoff(self):
		result = refund.refund_for(self.slabs, 16, 52000)
		self.assertEqual((result["deduction"], result["refundable"]), (10400, 41600))

	def test_percent_and_fee_add_up(self):
		result = refund.refund_for(self.slabs, 31, 10000)
		self.assertEqual((result["deduction"], result["refundable"]), (5500, 4500))

	def test_deduction_is_capped_at_the_amount(self):
		result = refund.refund_for([slab(0, 5, fee=1000)], 3, 400)
		self.assertEqual((result["deduction"], result["refundable"]), (400, 0))

	def test_no_slab_after_the_last_one_means_no_refund(self):
		result = refund.refund_for(self.slabs, 61, 52000)
		self.assertIsNone(result["slab"])
		self.assertEqual((result["deduction"], result["refundable"]), (52000, 0))

	def test_slab_boundaries_are_inclusive(self):
		self.assertEqual(refund.slab_for(self.slabs, 0).days_to_admission_start, 15)
		self.assertEqual(refund.slab_for(self.slabs, 30).days_from_admission_start, 16)
		self.assertEqual(refund.slab_for(self.slabs, 60).days_to_admission_start, 60)

	def test_pattern_validation(self):
		numbers.validate_pattern("{abbr}{yy}{program_code}{####}")
		for bad in ("{abbr}", "{abbr}{####}x", "{nope}{####}", "{#}", ""):
			with self.assertRaises(frappe.ValidationError):
				numbers.validate_pattern(bad)


class AdmitTestCase(CampusTestCase):
	"""One college with fee structures, a refund rule, an officer and a plain user; each test runs in a savepoint."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.original_skip = frappe.db.get_single_value("Education Settings", "user_creation_skip")
		frappe.db.set_single_value("Education Settings", "user_creation_skip", 1)
		cls.accounts = make_finance_company(COLLEGE, ABBR)
		frappe.db.set_value("Company", COLLEGE, "default_bank_account", cls.accounts["bank"])
		cls.make_year_program()
		cls.make_masters()
		cls.structure = make_fee_structure(COLLEGE, PROGRAM, YEAR, {"Tuition": TUITION_FEE, "Exam": EXAM_FEE}, cls.accounts)
		cls.bc_structure = make_fee_structure(
			COLLEGE, PROGRAM, YEAR, {"Tuition": BC_TUITION, "Exam": EXAM_FEE}, cls.accounts, student_category=BC
		)
		make_company(OTHER_COLLEGE, "AFO")
		make_user(OFFICER, [COLLEGE])
		make_user(PLAIN, [COLLEGE])
		make_user(OTHER_OFFICER, [OTHER_COLLEGE])
		frappe.get_doc("User", OFFICER).add_roles("Admission Officer")
		frappe.get_doc("User", OTHER_OFFICER).add_roles("Admission Officer")

	@classmethod
	def tearDownClass(cls):
		frappe.db.set_single_value("Education Settings", "user_creation_skip", cls.original_skip)
		super().tearDownClass()

	@classmethod
	def make_year_program(cls):
		if not frappe.db.exists("Academic Year", YEAR):
			frappe.get_doc(
				{"doctype": "Academic Year", "academic_year_name": YEAR, "year_start_date": today(), "year_end_date": add_days(today(), 330)}
			).insert()
		if not frappe.db.exists("Program", PROGRAM):
			frappe.get_doc({"doctype": "Program", "program_name": PROGRAM, "program_abbreviation": CODE, "oc_company": COLLEGE}).insert()

	@classmethod
	def make_masters(cls):
		for category in (OC, BC):
			if not frappe.db.exists("Student Category", category):
				frappe.get_doc({"doctype": "Student Category", "category": category}).insert()
		if not frappe.db.exists("Gender", "Male"):
			frappe.get_doc({"doctype": "Gender", "gender": "Male"}).insert()
		for code in (QUOTA, FREE_QUOTA):
			if not frappe.db.exists("Admission Quota", code):
				frappe.get_doc({"doctype": "Admission Quota", "code": code, "title": code}).insert()

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("admit_test")
		self.addCleanup(frappe.db.rollback, save_point="admit_test")
		self.addCleanup(frappe.set_user, "Administrator")
		self.touched = []
		self.addCleanup(lambda: delete_log_rows(self.touched))
		was_importing, frappe.flags.in_import = frappe.flags.in_import, True  # skip the user-creation throttle
		self.addCleanup(setattr, frappe.flags, "in_import", was_importing)
		frappe.db.delete("Seat Matrix")
		frappe.db.delete("Refund Rule")
		self.settings(register_no_pattern="{abbr}{yy}{program_code}{####}", roll_no_pattern="")
		self.rule(slabs=[(0, 15, 0, 1000), (16, 30, 20, 0)])

	def settings(self, **values):
		doc = frappe.get_doc("Admission Settings")
		doc.update({"active_admission_year": YEAR, **values})
		doc.save()

	def rule(self, slabs, year=None):
		frappe.get_doc(
			{
				"doctype": "Refund Rule", "company": COLLEGE, "admission_year": year,
				"slabs": [
					{"days_from_admission_start": a, "days_to_admission_start": b, "deduction_percent": p, "processing_fee": f}
					for a, b, p, f in slabs
				],
			}
		).insert()

	def matrix(self, rows):
		return frappe.get_doc(
			{
				"doctype": "Seat Matrix", "company": COLLEGE, "program": PROGRAM, "academic_year": YEAR,
				"rows": [{"quota": q, "category": c, "sanctioned": n} for q, c, n in rows],
			}
		).insert()

	def applicant(self, category=OC, quota=QUOTA, status="Approved", eligibility="Eligible", aadhaar=None):
		SERIAL[0] += 1
		doc = frappe.get_doc(
			{
				"doctype": "Student Applicant", "first_name": f"Flow{SERIAL[0]}", "program": PROGRAM, "academic_year": YEAR,
				"student_email_id": f"flow{SERIAL[0]}-{frappe.generate_hash(length=6)}@flow.example.com", "oc_company": COLLEGE,
				"student_category": category, "oc_admission_quota": quota, "application_status": status, "oc_aadhaar": aadhaar,
				"gender": "Male", "state": "Tamil Nadu",
			}
		).insert()
		frappe.db.set_value("Student Applicant", doc.name, "oc_eligibility_status", eligibility)
		if aadhaar:
			self.touched.append(doc.name)
		return doc.name

	def admit_as_officer(self, applicant):
		frappe.set_user(OFFICER)
		try:
			return admit(applicant)
		finally:
			frappe.set_user("Administrator")

	def counts(self):
		return {
			dt: frappe.db.count(dt) for dt in ("Student", "Program Enrollment", "Sales Invoice", "Customer")
		}  # fmt: skip

	def seat_free(self, quota=QUOTA, category=OC):
		"""check_seat_available passing for a user without the override role."""
		frappe.set_user(PLAIN)
		try:
			return check_seat_available(PROGRAM, YEAR, quota, category) is True
		except frappe.ValidationError:
			return False
		finally:
			frappe.set_user("Administrator")


class TestAdmit(AdmitTestCase):
	def test_admit_creates_student_enrollment_numbers_and_invoice(self):
		self.matrix([(QUOTA, OC, 2)])
		applicant = self.applicant()
		result = self.admit_as_officer(applicant)
		student = frappe.get_doc("Student", result["student"])
		self.assertEqual(student.student_applicant, applicant)
		self.assertEqual(student.oc_company, COLLEGE)
		self.assertEqual(student.oc_register_no, f"{ABBR}{YEAR_YY}{CODE}0001")
		self.assertTrue(student.customer)
		enrollment = frappe.get_doc("Program Enrollment", result["program_enrollment"])
		self.assertEqual(
			(enrollment.docstatus, enrollment.oc_admission_quota, enrollment.student_category, enrollment.academic_year),
			(1, QUOTA, OC, YEAR),
		)
		invoice = frappe.get_doc("Sales Invoice", result["invoice"])
		self.assertEqual((invoice.docstatus, invoice.student, invoice.customer), (1, student.name, student.customer))
		self.assertEqual(flt(invoice.grand_total), TUITION_FEE + EXAM_FEE)
		self.assertEqual(invoice.oc_program_enrollment, enrollment.name)
		self.assertEqual(frappe.db.get_value("Student Applicant", applicant, "application_status"), "Admitted")

	def test_invoice_uses_the_category_fee_structure(self):
		result = self.admit_as_officer(self.applicant(category=BC))
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", result["invoice"], "grand_total")), BC_TUITION + EXAM_FEE)

	def test_admit_fills_the_seat(self):
		self.matrix([(QUOTA, OC, 1)])
		self.assertTrue(self.seat_free())
		self.admit_as_officer(self.applicant())
		self.assertFalse(self.seat_free())
		second = self.applicant()
		with self.assertRaises(frappe.ValidationError):
			self.admit_as_officer(second)
		self.assertEqual(frappe.db.get_value("Student Applicant", second, "application_status"), "Approved")

	def test_aadhaar_is_copied_through_the_gate_and_logged(self):
		result = self.admit_as_officer(self.applicant(aadhaar=VALID))
		self.touched.append(result["student"])
		self.assertEqual(frappe.db.get_value("Student", result["student"], "oc_aadhaar_masked"), f"XXXX-XXXX-{VALID[-4:]}")
		reasons = [r.reason for r in log_rows(self.touched[0])]
		self.assertEqual(reasons, ["admission copy"])

	def test_preconditions_are_enforced(self):
		for kwargs in ({"status": "Applied"}, {"eligibility": "Pending"}, {"eligibility": "Ineligible"}):
			applicant = self.applicant(**kwargs)
			with self.assertRaises(frappe.ValidationError, msg=str(kwargs)):
				self.admit_as_officer(applicant)
			self.assertNotEqual(frappe.db.get_value("Student Applicant", applicant, "application_status"), "Admitted")

	def test_incomplete_documents_block_admission(self):
		applicant = self.applicant()
		with patch.object(admit_module.documents, "documents_complete", return_value=False):
			with self.assertRaises(frappe.ValidationError):
				self.admit_as_officer(applicant)

	def test_only_admission_officers_can_admit_and_a_second_admit_fails(self):
		applicant = self.applicant()
		frappe.set_user(PLAIN)
		with self.assertRaises(frappe.PermissionError):
			admit(applicant)
		frappe.set_user("Administrator")
		self.admit_as_officer(applicant)
		with self.assertRaises(frappe.ValidationError):
			self.admit_as_officer(applicant)

	def test_failure_leaves_nothing_half_created(self):
		self.matrix([(QUOTA, OC, 1)])
		applicant = self.applicant(aadhaar=VALID)
		before = self.counts()
		with patch.object(admit_module, "create_fee_invoice", side_effect=frappe.ValidationError("boom")):
			with self.assertRaises(frappe.ValidationError):
				self.admit_as_officer(applicant)
		self.assertEqual(self.counts(), before)
		self.assertEqual(frappe.db.get_value("Student Applicant", applicant, "application_status"), "Approved")
		self.assertFalse(frappe.db.exists("Student", {"student_applicant": applicant}))
		self.assertTrue(self.seat_free())  # the seat is not consumed
		self.assertEqual(self.admit_as_officer(applicant)["register_no"], f"{ABBR}{YEAR_YY}{CODE}0001")  # and neither is the number

	def test_missing_fee_structure_rolls_back_too(self):
		applicant = self.applicant(quota=FREE_QUOTA, category=OC)
		frappe.db.set_value("Fee Structure", self.structure.name, "docstatus", 2)
		self.addCleanup(frappe.db.set_value, "Fee Structure", self.structure.name, "docstatus", 1)
		before = self.counts()
		with self.assertRaises(frappe.ValidationError):
			self.admit_as_officer(applicant)
		self.assertEqual(self.counts(), before)

	def test_roll_numbers_follow_their_own_pattern(self):
		self.settings(roll_no_pattern="R{yyyy}{program_code}-{###}")
		first = frappe.get_doc("Student", self.admit_as_officer(self.applicant())["student"])
		second = frappe.get_doc("Student", self.admit_as_officer(self.applicant())["student"])
		self.assertEqual((first.oc_roll_no, second.oc_roll_no), (f"R{YEAR_FULL}{CODE}-001", f"R{YEAR_FULL}{CODE}-002"))
		self.assertEqual(second.oc_register_no[-4:], "0002")


YEAR_FULL = int(today()[:4])
YEAR_YY = today()[2:4]


class TestRegisterNumbers(AdmitTestCase):
	def test_rolled_back_number_is_reissued(self):
		frappe.db.savepoint("numbering")
		first = numbers.next_number("{abbr}{yy}{program_code}{####}", COLLEGE, PROGRAM, YEAR)
		frappe.db.rollback(save_point="numbering")
		self.assertEqual(numbers.next_number("{abbr}{yy}{program_code}{####}", COLLEGE, PROGRAM, YEAR), first)


class TestCancellation(AdmitTestCase):
	def admitted(self, **kwargs):
		result = self.admit_as_officer(self.applicant(**kwargs))
		return SimpleNamespace(applicant=frappe.db.get_value("Student", result["student"], "student_applicant"), **result)

	def cancel(self, admission, days, submit=True, user=OFFICER):
		"""Cancel today, `days` days after the admission year started (the refund slab counts from that start)."""
		frappe.db.set_value("Academic Year", YEAR, "year_start_date", add_days(today(), -days))
		return self.cancel_on(admission, today(), submit, user)

	def cancel_on(self, admission, date, submit=True, user=OFFICER):
		doc = frappe.get_doc(
			{
				"doctype": "Admission Cancellation", "student": admission.student, "program_enrollment": admission.program_enrollment,
				"cancellation_date": date, "reason": "Joined another college",
			}
		)
		frappe.set_user(user)
		try:
			doc.insert()
			return doc.submit() if submit else doc
		finally:
			frappe.set_user("Administrator")

	def pay_in_full(self, invoice):
		from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

		payment = get_payment_entry("Sales Invoice", invoice)
		payment.reference_no, payment.reference_date = "UTR1", today()
		payment.insert().submit()

	def gl(self, voucher):
		rows = frappe.get_all("GL Entry", {"voucher_no": voucher, "is_cancelled": 0}, ["account", "debit", "credit"])
		return {r.account: (flt(r.debit), flt(r.credit)) for r in rows}

	def test_refund_preview_on_the_draft(self):
		admission = self.admitted()
		doc = self.cancel(admission, 10, submit=False)
		self.assertEqual((doc.days_since_start, flt(doc.deduction), flt(doc.refundable_amount)), (10, 1000, 51000))
		self.assertEqual(doc.fee_invoice, admission.invoice)

	def test_before_the_cutoff_unpaid_invoice_full_refund_less_fee(self):
		self.matrix([(QUOTA, OC, 1)])
		admission = self.admitted()
		self.assertFalse(self.seat_free())
		doc = self.cancel(admission, 10)
		self.assertEqual((flt(doc.deduction), flt(doc.refundable_amount), flt(doc.cash_refund)), (1000, 51000, 0))
		note = frappe.get_doc("Sales Invoice", doc.credit_note)
		self.assertEqual((note.docstatus, note.is_return, note.return_against), (1, 1, admission.invoice))
		self.assertEqual(flt(note.grand_total), -51000)
		entries = self.gl(note.name)
		self.assertEqual(entries[f"Sales - {ABBR}"], (51000, 0))  # income reversed
		self.assertEqual(sum(d for d, _c in entries.values()), sum(c for _d, c in entries.values()))
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", admission.invoice, "outstanding_amount")), 1000)
		self.assertFalse(doc.payment_entry)  # nothing was paid, so nothing to pay back
		self.assertEqual(frappe.db.get_value("Program Enrollment", admission.program_enrollment, "docstatus"), 2)
		self.assertTrue(self.seat_free())  # seat freed
		self.assertEqual(frappe.db.get_value("Student", admission.student, "enabled"), 0)
		self.assertEqual(frappe.db.get_value("Student Applicant", admission.applicant, "application_status"), "Rejected")

	def test_after_the_cutoff_the_slab_deduction_applies_and_a_payment_entry_is_drafted(self):
		admission = self.admitted()
		self.pay_in_full(admission.invoice)
		doc = self.cancel(admission, 20)
		self.assertEqual((flt(doc.deduction), flt(doc.refundable_amount), flt(doc.cash_refund)), (10400, 41600, 41600))
		payment = frappe.get_doc("Payment Entry", doc.payment_entry)
		self.assertEqual((payment.docstatus, payment.payment_type, payment.party_type), (0, "Pay", "Customer"))
		self.assertEqual(flt(payment.paid_amount), 41600)
		self.assertEqual([r.reference_name for r in payment.references], [doc.credit_note])
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", doc.credit_note, "grand_total")), -41600)

	def test_beyond_the_last_slab_nothing_is_refunded(self):
		admission = self.admitted()
		doc = self.cancel(admission, 45)
		self.assertEqual((flt(doc.refundable_amount), flt(doc.deduction)), (0, 52000))
		self.assertFalse(doc.credit_note)
		self.assertEqual(frappe.db.get_value("Program Enrollment", admission.program_enrollment, "docstatus"), 2)

	def test_the_rule_of_the_admission_year_wins_over_the_general_rule(self):
		self.rule(slabs=[(0, 60, 50, 0)], year=YEAR)
		doc = self.cancel(self.admitted(), 5, submit=False)
		self.assertEqual(flt(doc.deduction), 26000)

	def test_a_cancellation_is_final_and_cannot_be_repeated(self):
		admission = self.admitted()
		doc = self.cancel(admission, 1)
		with self.assertRaises(frappe.ValidationError):
			doc.cancel()
		with self.assertRaises(frappe.ValidationError):
			self.cancel(admission, 2)

	def test_an_officer_of_another_company_cannot_cancel_and_sees_no_amounts(self):
		admission = self.admitted()
		for submit in (False, True):
			with self.assertRaises(frappe.PermissionError) as raised:
				self.cancel_on(admission, today(), submit, user=OTHER_OFFICER)
			self.assertNotIn("51000", str(raised.exception))
			self.assertNotIn("52000", str(raised.exception))
		self.assertEqual(frappe.db.count("Admission Cancellation"), 0)

	def test_cancellation_date_is_not_future_and_not_before_admission(self):
		admission = self.admitted()
		with self.assertRaises(frappe.ValidationError):
			self.cancel_on(admission, add_days(today(), 1), submit=False)
		frappe.db.set_value("Program Enrollment", admission.program_enrollment, "enrollment_date", add_days(today(), -2))
		with self.assertRaises(frappe.ValidationError):
			self.cancel_on(admission, add_days(today(), -3), submit=False)
		self.assertTrue(self.cancel_on(admission, add_days(today(), -2), submit=False))

	def test_documents_are_dated_today_and_the_frozen_date_applies(self):
		admission = self.admitted()
		self.pay_in_full(admission.invoice)
		earlier = add_days(today(), -2)
		frappe.db.set_value("Program Enrollment", admission.program_enrollment, "enrollment_date", add_days(today(), -5))
		doc = self.cancel_on(admission, earlier)
		self.assertEqual(str(frappe.db.get_value("Sales Invoice", doc.credit_note, "posting_date")), today())
		self.assertEqual(str(frappe.db.get_value("Payment Entry", doc.payment_entry, "posting_date")), today())
		second = self.admitted()
		frappe.db.set_value("Company", COLLEGE, "accounts_frozen_till_date", today())  # rolled back with the test savepoint
		with self.assertRaises(frappe.ValidationError):
			self.cancel(second, 5)  # an officer has no frozen-accounts modifier role: no bypass

	def test_the_officer_session_survives_admit_and_cancellation(self):
		"""No user switching: sid, session data, csrf token, user and form_dict are exactly as the request had them."""
		frappe.set_user(OFFICER)
		session_data = frappe._dict(user=OFFICER, csrf_token="csrf-token", data=frappe._dict(user=OFFICER, session_expiry="06:00:00"))
		frappe.local.session = frappe._dict(user=OFFICER, sid="sid-123", data=session_data.data, csrf_token="csrf-token", session_obj=None)
		frappe.local.form_dict = frappe._dict(applicant="x", cmd="campus.admissions.api.admit")
		snapshot = lambda: (  # noqa: E731
			frappe.session.user, frappe.session.sid, frappe.session.csrf_token, dict(frappe.session.data), dict(frappe.local.form_dict)
		)
		before = snapshot()
		try:
			result = admit(self.applicant())
			self.assertEqual(snapshot(), before)
			self.cancel_with_current_user(result)
			self.assertEqual(snapshot(), before)
		finally:
			frappe.set_user("Administrator")

	def cancel_with_current_user(self, result):
		student = frappe.db.get_value("Student", result["student"], "name")
		doc = frappe.get_doc(
			{"doctype": "Admission Cancellation", "student": student, "program_enrollment": result["program_enrollment"],
			 "cancellation_date": today(), "reason": "Session check"}
		)  # fmt: skip
		doc.insert()
		doc.submit()

	def test_refund_register_and_admission_report(self):
		admission = self.admitted()
		self.pay_in_full(admission.invoice)
		doc = self.cancel(admission, 20)
		_columns, rows = refund_register.execute({"company": COLLEGE})
		self.assertEqual([(r.name, flt(r.refundable_amount), r.payment_status) for r in rows], [(doc.name, 41600, "Draft")])
		_columns, rows = refund_register.execute({"company": COLLEGE, "from_date": add_days(today(), 25)})
		self.assertEqual(rows, [])
		make_user(PLAIN, [COLLEGE])
		frappe.set_user(PLAIN)
		self.assertEqual(refund_register.execute({"company": OTHER_COLLEGE})[1], [])
		self.assertEqual(quota_report.execute({"company": OTHER_COLLEGE})[1], [])


class TestConcurrentNumbers(CampusTestCase):
	def test_concurrent_numbers_are_unique_and_gap_free(self):
		"""Eight real connections draw from a brand new series at once (committed, then removed)."""
		prefix = f"CONC{frappe.generate_hash(length=6).upper()}"
		site, sites_path, errors, drawn = frappe.local.site, frappe.local.sites_path, [], []

		def worker():
			try:
				frappe.init(site, sites_path=sites_path)
				frappe.connect()
				with patch.object(numbers, "render_prefix", return_value=prefix):
					drawn.append(numbers.next_number("X{####}", COLLEGE, PROGRAM, YEAR))
				frappe.db.commit()
			except Exception as error:
				errors.append(repr(error))
			finally:
				frappe.destroy()

		threads = [threading.Thread(target=worker) for _ in range(8)]
		try:
			for thread in threads:
				thread.start()
			for thread in threads:
				thread.join()
		finally:
			connection = own_connection()
			connection.sql("delete from `tabSeries` where name = %s", (prefix,))
			connection.commit()
			connection.close()
		self.assertEqual(errors, [])
		self.assertEqual(sorted(drawn), [f"{prefix}{n:04d}" for n in range(1, 9)])


class TestPrintsAndReports(AdmitTestCase):
	def test_prints_render(self):
		applicant = self.applicant()
		doc = frappe.get_doc("Student Applicant", applicant)
		doc.append("oc_documents", {"document_type": "HSC Marksheet", "status": "Verified", "original_retained": 1})
		doc.append("oc_documents", {"document_type": "Photo", "status": "Submitted", "original_retained": 0})
		doc.save()
		letter = frappe.get_print("Student Applicant", applicant, "Provisional Admission Letter")
		self.assertIn(PROGRAM, letter)
		self.assertIn(YEAR, letter)
		receipt = frappe.get_print("Student Applicant", applicant, "Original Documents Receipt")
		self.assertIn("HSC Marksheet", receipt)
		self.assertNotIn("Photo", receipt)
		student = self.admit_as_officer(applicant)["student"]
		self.assertIn(frappe.db.get_value("Student", student, "oc_register_no"), frappe.get_print("Student", student, "Provisional Admission Letter Student"))

	def test_admissions_report_counts_by_quota_category_gender_state(self):
		self.matrix([(QUOTA, OC, 5), (QUOTA, BC, 5)])
		for category in (OC, OC, BC):
			self.admit_as_officer(self.applicant(category=category))
		_columns, rows = quota_report.execute({"company": COLLEGE, "academic_year": YEAR})
		table = {(r["grouping"], r["value"]): r["admitted"] for r in rows}
		self.assertEqual(table[("Total", "")], 3)
		self.assertEqual((table[("Quota", QUOTA)], table[("Category", OC)], table[("Category", BC)]), (3, 2, 1))
		self.assertEqual((table[("Gender", "Male")], table[("State", "Tamil Nadu")]), (3, 3))
		sanctioned = {r["value"]: r["sanctioned"] for r in rows if r["grouping"] == "Category"}
		self.assertEqual(sanctioned, {OC: 5, BC: 5})


class TestAqarCounts(CampusTestCase):
	"""AQAR 2.1.1 / 2.1.2: the report equals independent counts of the demo enrollments."""

	demo_scale = "small"

	def test_report_matches_the_demo_enrollments(self):
		from campus.tests.demo import ENGINEERING

		_columns, rows = quota_report.execute({"company": ENGINEERING})
		table = {(r["grouping"], r["value"]): r["admitted"] for r in rows}
		total = frappe.db.sql(
			"select count(*) from `tabProgram Enrollment` where docstatus = 1 and oc_company = %s", ENGINEERING
		)[0][0]
		self.assertGreater(total, 0)
		self.assertEqual(table[("Total", "")], total)
		by_category = frappe.db.sql(
			"select student_category, count(*) from `tabProgram Enrollment` where docstatus = 1 and oc_company = %s group by 1", ENGINEERING
		)
		self.assertEqual({v: n for (g, v), n in table.items() if g == "Category"}, dict(by_category))
		for grouping in ("Quota", "Category", "Gender", "State"):
			self.assertEqual(sum(n for (g, _v), n in table.items() if g == grouping), total, grouping)
