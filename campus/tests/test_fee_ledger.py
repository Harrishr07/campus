"""P1-T24 tests (M09-04): cross-company ledger and dues vs the GL, scoped dues, report scoping, no-dues gating."""

import frappe
from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return
from frappe.utils import flt, today

from campus.campus_finance import api, ledger
from campus.campus_finance.fee_heads import CAUTION_DEPOSIT, EXAM, HOSTEL, TUITION
from campus.campus_finance.report.student_fee_ledger import student_fee_ledger as report
from campus.campus_platform.verification import verify
from campus.tests.factories import make_user
from campus.tests.finance_factories import make_enrolled_students, make_finance_company, make_year_and_program
from campus.tests.utils import CampusTestCase

COLLEGE, TRUST = "Ledger Test College", "Ledger Test Trust"
YEAR, PROGRAM = "Ledger Test 2026", "Ledger Test BE"
TRUST_USER, COLLEGE_USER = "ledger-trust@example.com", "ledger-college@example.com"
WARDEN_USER = "ledger-warden@example.com"


class TestSplit(CampusTestCase):
	"""The pure head-splitting rules."""

	def test_split_keeps_the_total_and_gives_the_remainder_to_the_last_head(self):
		parts = ledger.split(100, [("Tuition", 1 / 3), ("Exam", 1 / 3), ("Other", 1 / 3)])
		self.assertEqual(sum(amount for _head, amount in parts), 100)
		self.assertEqual([head for head, _amount in parts], ["Tuition", "Exam", "Other"])
		self.assertEqual(ledger.split(-50, [("Tuition", 1)]), [("Tuition", -50)])

	def test_split_follows_the_shares(self):
		self.assertEqual(ledger.split(1000, [("Tuition", 0.8), ("Exam", 0.2)]), [("Tuition", 800), ("Exam", 200)])


class LedgerFixture(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.college = make_finance_company(COLLEGE, "LTC")
		cls.trust = make_finance_company(TRUST, "LTT")
		make_year_and_program(COLLEGE, PROGRAM, YEAR)
		_group, cls.students = make_enrolled_students(COLLEGE, PROGRAM, YEAR, 3, "LdgStu")
		make_user(TRUST_USER, [TRUST])
		make_user(COLLEGE_USER, [COLLEGE])
		make_user(WARDEN_USER, [COLLEGE])
		for user in (TRUST_USER, COLLEGE_USER):
			frappe.get_doc("User", user).add_roles("Accounts User")
		frappe.get_doc("User", WARDEN_USER).add_roles("Warden")

	def setUp(self):
		frappe.db.savepoint("ledger_test")
		self.addCleanup(frappe.db.rollback, save_point="ledger_test")
		self.addCleanup(frappe.set_user, "Administrator")
		self.student = self.students[0]

	def invoice(self, company, accounts, heads, student=None):
		student = student or self.student
		items = [
			{
				"item_code": head, "qty": 1, "rate": amount,
				"income_account": accounts["deposit"] if head == CAUTION_DEPOSIT else accounts["income"],
			}
			for head, amount in heads.items()
		]  # fmt: skip
		doc = frappe.get_doc(
			{
				"doctype": "Sales Invoice", "company": company, "student": student, "posting_date": today(), "due_date": today(),
				"customer": frappe.db.get_value("Student", student, "customer"), "items": items,
			}
		).insert()
		return doc.submit()

	def invoice_both(self, student=None):
		"""College tuition and exam fee, trust hostel fee."""
		college = self.invoice(COLLEGE, self.college, {TUITION: 40000, EXAM: 2000}, student)
		trust = self.invoice(TRUST, self.trust, {HOSTEL: 10000}, student)
		return college, trust

	def pay(self, invoice, amount):
		payment = get_payment_entry("Sales Invoice", invoice.name, party_amount=amount, bank_account=None)
		payment.paid_to = (self.college if invoice.company == COLLEGE else self.trust)["bank"]
		payment.reference_no, payment.reference_date = f"LDG-{invoice.name}-{amount}", today()
		payment.insert()
		return payment.submit()

	def gl_balance(self, customer, company=None):
		filters = {"party_type": "Customer", "party": customer, "is_cancelled": 0}
		filters.update({"company": company} if company else {})
		entries = frappe.get_all("GL Entry", filters, ["debit", "credit"])
		return flt(sum(e.debit - e.credit for e in entries), 2)


class TestDues(LedgerFixture):
	def test_college_tuition_and_trust_hostel_show_with_the_company_split(self):
		self.invoice_both()
		dues = api.has_dues(self.student)
		self.assertEqual(dues.total, 52000)
		self.assertEqual(dues.by_company, {COLLEGE: 42000, TRUST: 10000})
		self.assertEqual(dues.by_head, {TUITION: 40000, EXAM: 2000, HOSTEL: 10000})

	def test_scopes_restrict_dues_to_those_heads(self):
		self.invoice_both()
		self.assertEqual(api.has_dues(self.student, scopes=[EXAM]), {"total": 2000, "by_company": {COLLEGE: 2000}, "by_head": {EXAM: 2000}, "blocking": 2000})
		self.assertEqual(api.has_dues(self.student, scopes=[EXAM, HOSTEL]).total, 12000)
		self.assertEqual(api.has_dues(self.student, scopes=["Library"]), {"total": 0, "by_company": {}, "by_head": {}, "blocking": 0})

	def test_payments_and_credit_notes_reduce_dues(self):
		college, _trust = self.invoice_both()
		self.pay(college, 2000)  # the invoice is tuition + exam: both heads are reduced pro rata
		note = make_sales_return(college.name)
		note.items = note.items[:1]
		note.items[0].qty = -0.1  # 4000 of the tuition line
		note.insert().submit()
		dues = api.has_dues(self.student)
		self.assertEqual(dues.total, 52000 - 2000 - 4000)
		self.assertEqual(dues.by_company, {COLLEGE: 42000 - 2000 - 4000, TRUST: 10000})

	def test_a_credit_note_is_attributed_to_its_own_heads(self):
		college, _trust = self.invoice_both()
		note = make_sales_return(college.name)
		note.items = note.items[:1]
		note.items[0].qty = -0.1  # 4000 off the tuition line
		note.insert().submit()
		dues = api.has_dues(self.student)
		self.assertEqual(dues.by_head, {TUITION: 36000, EXAM: 2000, HOSTEL: 10000})
		self.assertEqual(api.has_dues(self.student, scopes=[EXAM]).total, 2000)

	def test_a_refund_owed_by_one_company_does_not_hide_dues_of_another(self):
		self.invoice(COLLEGE, self.college, {TUITION: 5000})
		refund = frappe.get_doc(
			{
				"doctype": "Sales Invoice", "company": TRUST, "student": self.student, "is_return": 1, "posting_date": today(),
				"due_date": today(), "customer": frappe.db.get_value("Student", self.student, "customer"),
				"items": [{"item_code": HOSTEL, "qty": -1, "rate": 5000, "income_account": self.trust["income"]}],
			}
		).insert()
		refund.submit()
		dues = api.has_dues(self.student)
		self.assertEqual((dues.total, dues.blocking), (0, 5000))
		self.assertEqual(dues.by_company, {COLLEGE: 5000, TRUST: -5000})

	def test_an_invoice_without_a_student_counts_through_the_customer(self):
		invoice = self.invoice(COLLEGE, self.college, {TUITION: 700})
		frappe.db.set_value("Sales Invoice", invoice.name, "student", None)
		self.assertEqual(api.has_dues(self.student).total, 700)
		self.assertEqual([i.name for i in api.student_invoices(self.student)], [invoice.name])

	def test_a_student_with_no_invoices_owes_nothing(self):
		self.assertEqual(api.has_dues(self.students[2]).total, 0)

	def test_other_students_invoices_are_not_counted(self):
		self.invoice_both(self.students[1])
		self.assertEqual(api.has_dues(self.student).total, 0)

	def test_a_line_without_a_fee_category_counts_as_other(self):
		item = frappe.get_doc({"doctype": "Item", "item_code": "Ledger Test Misc", "item_group": "Fee Component", "is_stock_item": 0, "stock_uom": "Nos"})
		if frappe.get_meta("Item").has_field("gst_hsn_code"):
			item.gst_hsn_code = "999294"
		item.insert()
		self.invoice(COLLEGE, self.college, {"Ledger Test Misc": 300})
		self.assertEqual(api.has_dues(self.student).by_head, {"Other": 300})

	def test_caution_deposit_counts_as_its_own_head(self):
		self.invoice(COLLEGE, self.college, {CAUTION_DEPOSIT: 5000})
		self.assertEqual(api.has_dues(self.student).by_head, {CAUTION_DEPOSIT: 5000})


class TestLedgerReport(LedgerFixture):
	def run_report(self, **filters):
		columns, rows, _msg, _chart, summary = report.execute({"student": self.student, **filters})
		return columns, rows, summary

	def test_ledger_totals_match_the_gl_and_the_dues(self):
		college, _trust = self.invoice_both()
		self.pay(college, 12000)
		customer = frappe.db.get_value("Student", self.student, "customer")
		_columns, rows, summary = self.run_report()
		self.assertEqual(sum(r["debit"] - r["credit"] for r in rows), self.gl_balance(customer))
		self.assertEqual(rows[-1]["balance"], self.gl_balance(customer))
		self.assertEqual(rows[-1]["balance"], api.has_dues(self.student).total)
		for company in (COLLEGE, TRUST):
			self.assertEqual(sum(r["debit"] - r["credit"] for r in rows if r["company"] == company), self.gl_balance(customer, company))
		self.assertEqual(summary[0]["value"], 40000)
		self.assertEqual({r["currency"] for r in rows}, {"INR"})

	def test_invoices_split_by_head_and_payments_have_no_head(self):
		college, _trust = self.invoice_both()
		self.pay(college, 500)
		_columns, rows, _summary = self.run_report()
		invoice_rows = {(r["voucher_no"], r["head"]): r["debit"] for r in rows if r["voucher_type"] == "Sales Invoice"}
		self.assertEqual(invoice_rows[(college.name, TUITION)], 40000)
		self.assertEqual(invoice_rows[(college.name, EXAM)], 2000)
		payment = [r for r in rows if r["voucher_type"] == "Payment Entry"]
		self.assertEqual([(r["head"], r["credit"], r["company"]) for r in payment], [("", 500, COLLEGE)])

	def test_credit_note_appears_as_credit_rows(self):
		college, _trust = self.invoice_both()
		note = make_sales_return(college.name)
		note.insert().submit()
		_columns, rows, _summary = self.run_report(company=COLLEGE)
		credits = {r["head"]: r["credit"] for r in rows if r["voucher_no"] == note.name}
		self.assertEqual(credits, {TUITION: 40000, EXAM: 2000})
		self.assertEqual(rows[-1]["balance"], 0)

	def test_company_filter_limits_the_rows(self):
		self.invoice_both()
		_columns, rows, _summary = self.run_report(company=TRUST)
		self.assertEqual({r["company"] for r in rows}, {TRUST})

	def test_staff_see_only_their_permitted_companies(self):
		self.invoice_both()
		frappe.set_user(TRUST_USER)
		_columns, rows, summary = self.run_report()
		self.assertEqual({r["company"] for r in rows}, {TRUST})
		self.assertEqual(summary[0]["value"], 10000)
		with self.assertRaises(frappe.PermissionError):
			self.run_report(company=COLLEGE)

	def test_report_is_for_accounts_roles_only(self):
		roles = {r.role for r in frappe.get_doc("Report", "Student Fee Ledger").roles}
		self.assertEqual(roles, {"System Manager", "Accounts Manager", "Accounts User", "Principal"})


class TestNoDuesClearance(LedgerFixture):
	def clearance(self, **values):
		return frappe.get_doc({"doctype": "No Dues Clearance", "student": self.student, "purpose": "Transfer Certificate", **values})

	def row(self, doc, office):
		return next(r for r in doc.signoffs if r.office == office)

	def clear_all(self, doc):
		for row in doc.signoffs:
			row.status = "Cleared"

	def test_new_clearance_has_the_standard_offices_pending_and_checks_dues(self):
		self.invoice_both()
		doc = self.clearance().insert()
		self.assertEqual([(r.office, r.status, r.mandatory) for r in doc.signoffs], [(o, "Pending", 1) for o in ("Accounts", "Library", "Hostel", "Lab")])
		self.assertEqual((doc.dues_total, doc.company), (52000, COLLEGE))
		self.assertIn("Hostel: 10000", doc.dues_note)

	def test_cannot_submit_while_a_mandatory_office_is_pending(self):
		doc = self.clearance().insert()
		doc.signoffs[0].status = "Cleared"
		doc.save()
		with self.assertRaisesRegex(frappe.ValidationError, "Library"):
			doc.submit()

	def test_cannot_submit_while_dues_exist_even_if_every_office_cleared(self):
		self.invoice_both()
		doc = self.clearance()
		doc.insert()
		self.clear_all(doc)
		doc.save()
		with self.assertRaisesRegex(frappe.ValidationError, "dues"):
			doc.submit()

	def test_dues_raised_after_sign_off_block_the_submit(self):
		doc = self.clearance()
		doc.insert()
		self.clear_all(doc)
		doc.save()
		self.invoice(TRUST, self.trust, {HOSTEL: 100})
		with self.assertRaisesRegex(frappe.ValidationError, "dues"):
			doc.submit()

	def test_submits_when_cleared_and_paid_and_issues_a_verifiable_certificate(self):
		college, trust = self.invoice_both()
		self.pay(college, 42000)
		self.pay(trust, 10000)
		doc = self.clearance()
		doc.insert()
		self.clear_all(doc)
		doc.signoffs[0].cleared_by = TRUST_USER  # not trusted: the server stamps who cleared
		doc.save().submit()
		doc.reload()
		self.assertEqual((doc.docstatus, doc.dues_total), (1, 0))
		self.assertEqual({r.cleared_by for r in doc.signoffs}, {"Administrator"})
		record = frappe.get_doc("Verifiable Document", {"code": doc.verification_code})
		self.assertEqual((record.reference_doctype, record.reference_name, record.status), ("No Dues Clearance", doc.name, "Valid"))
		html = frappe.get_print("No Dues Clearance", doc.name, print_format="No Dues Certificate")
		for text in (doc.student_name, "Transfer Certificate", "Library", COLLEGE, doc.verification_code):
			self.assertIn(text, html)

	def test_optional_office_may_stay_pending_and_custom_offices_are_allowed(self):
		doc = self.clearance()
		doc.append("signoffs", {"office": "Sports", "mandatory": 0})
		doc.insert()
		for row in doc.signoffs:
			if row.mandatory:
				row.status = "Cleared"
		doc.save().submit()
		self.assertEqual(doc.docstatus, 1)

	def test_reopening_a_row_clears_who_signed(self):
		doc = self.clearance().insert()
		doc.signoffs[1].status = "Cleared"
		doc.save()
		self.assertEqual(doc.signoffs[1].cleared_by, "Administrator")
		doc.signoffs[1].status = "Pending"
		doc.save()
		self.assertFalse(doc.signoffs[1].cleared_by)

	def test_a_refund_owed_elsewhere_does_not_let_a_student_with_dues_through(self):
		self.invoice(COLLEGE, self.college, {TUITION: 5000})
		frappe.get_doc(
			{
				"doctype": "Sales Invoice", "company": TRUST, "student": self.student, "is_return": 1, "posting_date": today(),
				"due_date": today(), "customer": frappe.db.get_value("Student", self.student, "customer"),
				"items": [{"item_code": HOSTEL, "qty": -1, "rate": 5000, "income_account": self.trust["income"]}],
			}
		).insert().submit()
		doc = self.clearance().insert()
		self.clear_all(doc)
		doc.save()
		with self.assertRaisesRegex(frappe.ValidationError, "dues"):
			doc.submit()

	def test_standard_offices_cannot_be_removed_or_made_optional(self):
		doc = self.clearance().insert()
		doc.remove(doc.signoffs[1])
		with self.assertRaisesRegex(frappe.ValidationError, "Library"):
			doc.save()
		doc = self.clearance().insert()
		doc.signoffs[3].mandatory = 0
		with self.assertRaisesRegex(frappe.ValidationError, "Lab"):
			doc.save()
		doc = self.clearance().insert()
		doc.signoffs[0].office = "Accts"  # renaming is removing
		with self.assertRaisesRegex(frappe.ValidationError, "Accounts"):
			doc.save()

	def test_an_office_is_cleared_only_by_its_roles(self):
		doc = self.clearance().insert()
		frappe.set_user(COLLEGE_USER)  # an accounts user, not the warden
		doc = frappe.get_doc("No Dues Clearance", doc.name)
		doc.signoffs[2].status = "Cleared"
		with self.assertRaises(frappe.PermissionError):
			doc.save()
		doc = frappe.get_doc("No Dues Clearance", doc.name)
		doc.signoffs[0].status = "Cleared"  # Accounts: allowed
		doc.save()
		frappe.set_user(WARDEN_USER)
		doc = frappe.get_doc("No Dues Clearance", doc.name)
		doc.signoffs[2].status = "Cleared"
		doc.save()
		self.assertEqual(doc.signoffs[2].cleared_by, WARDEN_USER)
		doc = frappe.get_doc("No Dues Clearance", doc.name)
		doc.signoffs[0].status = "Pending"  # reopening the Accounts sign-off is not the warden's
		with self.assertRaises(frappe.PermissionError):
			doc.save()

	def test_clearance_tracks_changes(self):
		self.assertTrue(frappe.get_meta("No Dues Clearance").track_changes)

	def test_cancelling_revokes_the_certificate_and_an_amendment_issues_a_new_one(self):
		doc = self.clearance().insert()
		self.clear_all(doc)
		doc.save().submit()
		code = frappe.db.get_value("No Dues Clearance", doc.name, "verification_code")
		self.assertEqual(verify(code).status, "Valid")
		doc.cancel()
		found = verify(code)
		self.assertEqual(found.status, "Revoked")
		self.assertIn(doc.name, found.revocation_reason)
		amended = frappe.copy_doc(doc)
		amended.amended_from, amended.docstatus = doc.name, 0
		amended.insert()
		self.clear_all(amended)
		amended.save().submit()
		self.assertNotEqual(amended.verification_code, code)
		self.assertEqual(verify(amended.verification_code).status, "Valid")

	def test_duplicate_offices_are_rejected(self):
		doc = self.clearance().insert()
		doc.append("signoffs", {"office": " hostel ", "mandatory": 0})
		with self.assertRaisesRegex(frappe.ValidationError, "more than once"):
			doc.save()

	def test_renaming_a_cleared_row_to_another_office_is_not_a_way_round_the_roles(self):
		doc = self.clearance()
		doc.append("signoffs", {"office": "Sports", "mandatory": 0})
		doc.insert()
		self.row(doc, "Sports").status = "Cleared"  # Sports has no mapping: a manager (Administrator) clears it
		doc.save()
		frappe.set_user(WARDEN_USER)
		doc = frappe.get_doc("No Dues Clearance", doc.name)
		self.row(doc, "Sports").office = "Sports Complex"  # old office was cleared: not the warden's to touch
		with self.assertRaises(frappe.PermissionError):
			doc.save()

	def test_a_row_renamed_to_an_office_the_user_may_not_clear_resets_to_pending(self):
		settings = frappe.get_single("Campus Settings")
		settings.append("no_dues_office_roles", {"office": "Sports", "role": "Accounts Manager"})
		settings.append("no_dues_office_roles", {"office": "Games", "role": "Warden"})
		settings.save()
		doc = self.clearance()
		doc.append("signoffs", {"office": "Games", "mandatory": 0})
		doc.insert()
		frappe.set_user(WARDEN_USER)
		doc = frappe.get_doc("No Dues Clearance", doc.name)
		self.row(doc, "Games").status = "Cleared"
		doc.save()
		self.row(doc, "Games").office = "Sports"  # the warden may clear Games but not Sports
		doc.save()
		row = self.row(doc, "Sports")
		self.assertEqual((row.status, row.cleared_by), ("Pending", None))

	def test_an_unmapped_office_is_cleared_by_managers_only(self):
		doc = self.clearance()
		doc.append("signoffs", {"office": "Sports", "mandatory": 0})
		doc.insert()
		frappe.set_user(COLLEGE_USER)  # an accounts user, not a manager
		doc = frappe.get_doc("No Dues Clearance", doc.name)
		self.row(doc, "Sports").status = "Cleared"
		with self.assertRaises(frappe.PermissionError):
			doc.save()

	def test_migrate_reseeds_a_missing_standard_mapping_only(self):
		from campus.campus_finance.no_dues import clearing_roles, seed_office_roles

		settings = frappe.get_single("Campus Settings")
		settings.no_dues_office_roles = [r for r in settings.no_dues_office_roles if r.office != "Library"]
		settings.append("no_dues_office_roles", {"office": "Sports", "role": "Warden"})
		settings.save()
		self.assertFalse(clearing_roles("Library"))
		seed_office_roles()
		self.assertEqual(clearing_roles("Library"), {"Librarian"})
		self.assertEqual(clearing_roles("Sports"), {"Warden"})
