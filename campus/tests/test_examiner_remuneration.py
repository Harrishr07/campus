"""P2-T23 (M06-04) integration tests: Examiner Remuneration Claims computed from the source records, approved through
the approval engine (never by the examiner), paid by HRMS Additional Salary (internal) or a draft Purchase Invoice with
TDS by the Supplier's category (external); a source is claimed once.

Fixture (Exam Test College, the valuation fixture's session; rates of the college unless said otherwise):
- Bundle P1 (d22, d26), both valued in round 1 by the internal examiner (Employee with user VAL1) and in round 2 by
  the External Member whose email is VAL2's.
- QP Setter Nomination for EXM TH: the internal examiner sets, a second employee scrutinises; the paper is approved and
  was released on 2022-12-01.
- Invigilation: the internal examiner on 2022-12-01 FN and 2022-12-02 AN (plus a future duty, not yet claimable),
  the second employee on 2022-12-01 FN.
- Rates: Valuation Round 1 20 from 2020-01-01 and 25 from 2026-01-01 (valued today: 25); Valuation Round 2 30;
  QP Setting 1,500; QP Scrutiny 500; Invigilation 300 from 2020-01-01 and 400 from 2023-01-01 (duties in 2022: 300);
  the other college's Invigilation rate of 999 never applies.
Hand figures: internal examiner 2 x 25 + 1 x 1,500 + 2 x 300 = 2,150; second employee 500 + 300 = 800; external
examiner 2 x 30 = 60, TDS 10% = 6, net 54.
"""

import frappe
from frappe.utils import add_days, add_months, get_first_day, get_last_day, today

from campus.campus_platform.approvals import approve, request_approval
from campus.campus_finance.fee_heads import ensure_sac_code
from campus.examinations import remuneration_payment
from campus.examinations.report.remuneration_register import remuneration_register
from campus.tests.factories import make_company, make_user
from campus.tests.finance_factories import ensure_fiscal_years, make_account, make_company_with_accounts
from campus.tests.test_exam_seating import make_room
from campus.tests.test_results import COLLEGE
from campus.tests.test_valuation import COURSE, VAL1, VAL2, ValuationFixture

ABBR, OTHER = "EXTC", "Remuneration Other College"
APPROVER = "exr-approver@example.com"
CATEGORY = "EXR Test Professional Fees"
VALUATION_ITEM = "EXR-TEST-VAL"
CLAIM = "Examiner Remuneration Claim"
COMPONENT = remuneration_payment.SALARY_COMPONENT


class RemunerationFixture(ValuationFixture):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_fiscal_years()
		make_company_with_accounts(COLLEGE, ABBR)
		make_company(OTHER, "EXRO")
		if not frappe.db.exists("Gender", "Male"):
			frappe.get_doc({"doctype": "Gender", "gender": "Male"}).insert()
		make_user(APPROVER, [COLLEGE])
		frappe.get_doc("User", APPROVER).add_roles("Accounts Manager", "Accounts User")

	def setUp(self):
		super().setUp()
		remuneration_payment.setup_remuneration()
		self.internal = self.employee(VAL1)
		self.scrutiniser = self.employee(None)
		self.member = self.external_member(VAL2)
		self.make_rates()
		self.valued_bundle()
		self.set_paper()
		self.make_roster()

	# fixtures
	def employee(self, user):
		return frappe.get_doc(
			{
				"doctype": "Employee", "first_name": "Exr", "last_name": frappe.generate_hash(length=6), "gender": "Male",
				"date_of_birth": "1980-01-01", "date_of_joining": "2010-01-01", "company": COLLEGE, "user_id": user,
			}
		).insert().name  # fmt: skip

	def external_member(self, email, supplier=True):
		member = frappe.get_doc({"doctype": "External Member", "member_name": f"Dr. {email.split('@')[0]}", "email": email}).insert()
		if supplier:
			member.create_supplier()
			frappe.db.set_value("Supplier", member.supplier, "tax_withholding_category", self.tds_category())
		return member.name

	def tds_category(self):
		if not frappe.db.exists("Tax Withholding Category", CATEGORY):
			account = make_account(COLLEGE, ABBR, "TDS Payable", "Duties and Taxes", account_type="Tax")
			frappe.get_doc(
				{
					"doctype": "Tax Withholding Category", "name": CATEGORY, "category_name": CATEGORY,
					"accounts": [{"company": COLLEGE, "account": account}],
					"rates": [{"from_date": "2020-01-01", "to_date": "2030-12-31", "tax_withholding_rate": 10, "single_threshold": 1, "cumulative_threshold": 1}],
				}
			).insert()  # fmt: skip
		return CATEGORY

	def make_rates(self):
		if not frappe.db.exists("Item", VALUATION_ITEM):
			group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
			frappe.get_doc(
				{"doctype": "Item", "item_code": VALUATION_ITEM, "item_group": group, "stock_uom": "Nos", "is_stock_item": 0, "gst_hsn_code": ensure_sac_code()}
			).insert()  # fmt: skip
		for activity, from_date, rate, company in (
			("Valuation Round 1", "2020-01-01", 20, COLLEGE), ("Valuation Round 1", "2026-01-01", 25, COLLEGE),
			("Valuation Round 2", "2020-01-01", 30, COLLEGE), ("QP Setting", "2020-01-01", 1500, COLLEGE),
			("QP Scrutiny", "2020-01-01", 500, COLLEGE), ("Invigilation", "2020-01-01", 300, COLLEGE),
			("Invigilation", "2023-01-01", 400, COLLEGE), ("Invigilation", "2020-01-01", 999, OTHER),
		):  # fmt: skip
			frappe.get_doc(
				{"doctype": "Remuneration Rate", "company": company, "activity": activity, "from_date": from_date, "rate": rate, "item": VALUATION_ITEM}
			).insert()  # fmt: skip

	def valued_bundle(self):
		bundle = self.bundle()
		first = self.allocate(bundle, 1, VAL1, examiner_type="Internal", employee=self.internal)
		second = self.allocate(bundle, 2, VAL2, external_member=self.member)
		for dummy in (self.d22, self.d26):
			self.value(first, dummy, 20, 20, VAL1)
			self.value(second, dummy, 20, 22, VAL2)
		self.allocations = (first.name, second.name)

	def set_paper(self):
		frappe.get_doc(
			{
				"doctype": "QP Setter Nomination", "exam_session": self.session.name, "course": COURSE, "deadline": "2022-11-01",
				"setters": [{"employee": self.internal}], "scrutiniser": self.scrutiniser,
			}
		).insert()  # fmt: skip
		# stands in for a moderated, sealed and released paper (its sealing needs encrypted set files)
		frappe.get_doc(
			{
				"doctype": "Question Paper", "name": f"QP-EXR-{frappe.generate_hash(length=6)}", "exam_session": self.session.name,
				"course": COURSE, "company": COLLEGE, "docstatus": 1, "moderation_status": "Approved", "release_at": "2022-12-01 10:00:00",
			}
		).db_insert()  # fmt: skip

	def make_roster(self):
		room = make_room("Exr Hall", 2, 2, [], company=COLLEGE).name
		duty = lambda employee, date, slot: {"exam_date": date, "slot": slot, "room": room, "employee": employee}  # noqa: E731
		roster = frappe.get_doc(
			{
				"doctype": "Invigilation Roster", "exam_session": self.session.name, "invigilators_per_hall": 1,
				"faculty": [{"employee": self.internal}, {"employee": self.scrutiniser}],
				"duties": [
					duty(self.internal, "2022-12-01", "FN"), duty(self.internal, "2022-12-02", "AN"),
					duty(self.internal, add_days(today(), 30), "FN"), duty(self.scrutiniser, "2022-12-01", "FN"),
				],
			}
		)  # fmt: skip
		roster.flags.generating = True  # stands in for Generate Roster
		roster.insert()

	def salary_structure(self, employee):
		"""Basic = base 20,000 from 2026-04-01, and a holiday list for the slips."""
		if not frappe.db.exists("Salary Structure", "EXR Test Structure"):
			frappe.get_doc(
				{
					"doctype": "Salary Structure", "name": "EXR Test Structure", "company": COLLEGE, "currency": "INR",
					"payroll_frequency": "Monthly", "is_active": "Yes",
					"earnings": [{"salary_component": "Basic", "amount_based_on_formula": 1, "formula": "base"}],
				}
			).insert().submit()  # fmt: skip
			holidays = frappe.get_doc(
				{"doctype": "Holiday List", "holiday_list_name": "EXR Test", "from_date": "2026-01-01", "to_date": "2027-12-31"}
			).insert()  # fmt: skip
			frappe.get_doc(
				{"doctype": "Holiday List Assignment", "applicable_for": "Company", "assigned_to": COLLEGE, "holiday_list": holidays.name, "from_date": "2026-01-01"}
			).insert().submit()  # fmt: skip
		frappe.get_doc(
			{
				"doctype": "Salary Structure Assignment", "employee": employee, "company": COLLEGE, "from_date": "2026-04-01",
				"salary_structure": "EXR Test Structure", "base": 20000, "currency": "INR",
			}
		).insert().submit()  # fmt: skip

	def slip(self, employee, on_date):
		start, end = get_first_day(on_date), get_last_day(on_date)
		return frappe.get_doc(
			{"doctype": "Salary Slip", "employee": employee, "start_date": start, "end_date": end, "posting_date": end, "payroll_frequency": "Monthly"}
		).insert()  # fmt: skip

	# helpers
	def claim(self, employee=None, member=None, **values):
		examiner = {"examiner_type": "External", "external_member": member} if member else {"examiner_type": "Internal", "employee": employee or self.internal}
		return frappe.get_doc({"doctype": CLAIM, "exam_session": self.session.name, **examiner, **values}).insert()

	def approved(self, claim, approver=APPROVER):
		request = request_approval(CLAIM, claim.name)
		frappe.set_user(approver)
		try:
			approve(request, None)
		finally:
			frappe.set_user("Administrator")
		return frappe.get_doc(CLAIM, claim.name)

	@staticmethod
	def lines(claim):
		"""(activity, count, rate, amount) summed over the source rows of one activity and rate."""
		totals = {}
		for r in claim.items:
			count, amount = totals.get((r.activity, r.rate), (0, 0))
			totals[(r.activity, r.rate)] = (count + r.quantity, amount + r.amount)
		return sorted((activity, count, rate, amount) for (activity, rate), (count, amount) in totals.items())


class TestClaimComputation(RemunerationFixture):
	def test_internal_claim_is_rate_times_count_from_the_source_records(self):
		claim = self.claim()
		self.assertEqual(
			self.lines(claim),
			[("Invigilation", 2, 300, 600), ("QP Setting", 1, 1500, 1500), ("Valuation Round 1", 2, 25, 50)],
		)
		self.assertEqual(claim.total_amount, 2150)
		self.assertEqual(claim.company, COLLEGE)

	def test_each_line_links_its_source_record(self):
		claim = self.claim()
		sources = {r.activity: (r.source_doctype, r.source_name) for r in claim.items}
		self.assertEqual(sources["Valuation Round 1"], ("Valuation Allocation", self.allocations[0]))
		self.assertEqual(sources["QP Setting"][0], "QP Setter Nomination")
		self.assertEqual(sources["Invigilation"][0], "Invigilation Roster")

	def test_scrutiny_and_the_other_examiners_duties(self):
		claim = self.claim(self.scrutiniser)
		self.assertEqual(self.lines(claim), [("Invigilation", 1, 300, 300), ("QP Scrutiny", 1, 500, 500)])
		self.assertEqual(claim.total_amount, 800)

	def test_external_claim_takes_its_valuation_only(self):
		claim = self.claim(member=self.member)
		self.assertEqual(self.lines(claim), [("Valuation Round 2", 2, 30, 60)])
		self.assertEqual(claim.total_amount, 60)

	def test_posted_lines_are_ignored(self):
		claim = frappe.get_doc(
			{
				"doctype": CLAIM, "exam_session": self.session.name, "examiner_type": "Internal", "employee": self.internal,
				"items": [{"activity": "QP Setting", "quantity": 10, "rate": 9999, "amount": 99990}],
			}
		).insert()  # fmt: skip
		self.assertEqual(claim.total_amount, 2150)
		claim.items[0].rate = 9999
		claim.save()
		self.assertEqual(claim.total_amount, 2150)

	def test_a_missing_rate_is_refused_naming_the_activity(self):
		frappe.db.delete("Remuneration Rate", {"activity": "QP Scrutiny"})
		with self.assertRaises(frappe.ValidationError) as caught:
			self.claim(self.scrutiniser)
		self.assertIn("QP Scrutiny", str(caught.exception))

	def test_nothing_to_claim_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.claim(self.employee(None))

	def test_rates_are_one_per_activity_date_and_company(self):
		with self.assertRaises(frappe.DuplicateEntryError):
			frappe.get_doc(
				{"doctype": "Remuneration Rate", "company": COLLEGE, "activity": "Invigilation", "from_date": "2020-01-01", "rate": 350}
			).insert()  # fmt: skip


class TestClaimedOnce(RemunerationFixture):
	def test_a_second_claim_of_the_same_sources_is_refused(self):
		first = self.claim()
		with self.assertRaises(frappe.ValidationError) as caught:
			self.claim()
		self.assertIn(first.name, str(caught.exception))

	def test_the_database_refuses_a_second_row_for_a_claimed_source(self):
		first = self.claim()
		row = frappe.get_doc({**first.items[0].as_dict(), "name": None, "parent": "EXR-OTHER"})
		with self.assertRaises((frappe.UniqueValidationError, frappe.DuplicateEntryError)):
			row.db_insert()

	def test_a_cancelled_claim_frees_its_sources(self):
		self.salary_structure(self.internal)
		first = self.approved(self.claim())
		first.cancel()
		self.assertEqual(frappe.db.get_value("Additional Salary", first.additional_salary, "docstatus"), 2)
		self.assertEqual(self.claim().total_amount, 2150)


class TestInternalPayment(RemunerationFixture):
	def test_approval_posts_additional_salary_on_the_next_slip(self):
		self.salary_structure(self.internal)
		claim = self.approved(self.claim())
		self.assertEqual(claim.docstatus, 1)
		additional = frappe.get_doc("Additional Salary", claim.additional_salary)
		self.assertEqual(
			(additional.docstatus, additional.employee, additional.salary_component, additional.amount, str(additional.payroll_date)),
			(1, self.internal, COMPONENT, 2150, today()),
		)
		self.assertEqual((additional.ref_doctype, additional.ref_docname), (CLAIM, claim.name))
		slip = self.slip(self.internal, today())
		self.assertEqual({r.salary_component: r.amount for r in slip.earnings}, {"Basic": 20000, COMPONENT: 2150})

	def test_after_a_processed_slip_it_goes_to_the_following_month(self):
		self.salary_structure(self.internal)
		self.slip(self.internal, today()).submit()
		claim = self.approved(self.claim())
		next_month = get_first_day(add_months(today(), 1))
		self.assertEqual(str(claim.payroll_date), str(next_month))
		slip = self.slip(self.internal, next_month)
		self.assertEqual({r.salary_component: r.amount for r in slip.earnings}.get(COMPONENT), 2150)

	def test_the_examiner_cannot_approve_their_own_claim(self):
		frappe.get_doc("User", VAL1).add_roles("Accounts Manager", "Accounts User")
		make_user(VAL1, [COLLEGE])
		claim = self.claim()
		with self.assertRaises(frappe.PermissionError) as caught:
			self.approved(claim, approver=VAL1)
		self.assertIn("your own", str(caught.exception))
		self.assertEqual(frappe.db.get_value(CLAIM, claim.name, "docstatus"), 0)

	def test_submit_needs_the_approval(self):
		with self.assertRaises(frappe.ValidationError):
			self.claim().submit()


class TestExternalPayment(RemunerationFixture):
	def test_approval_drafts_a_purchase_invoice_with_tds_by_the_suppliers_category(self):
		claim = self.approved(self.claim(member=self.member))
		invoice = frappe.get_doc("Purchase Invoice", claim.purchase_invoice)
		supplier = frappe.db.get_value("External Member", self.member, "supplier")
		self.assertEqual((invoice.docstatus, invoice.supplier, invoice.company, invoice.bill_no), (0, supplier, COLLEGE, claim.name))
		self.assertEqual([(r.item_code, r.amount) for r in invoice.items], [(VALUATION_ITEM, 60)])
		self.assertEqual({r.tax_withholding_category for r in invoice.tax_withholding_entries}, {CATEGORY})
		self.assertEqual(sum(r.base_tax_amount for r in invoice.taxes if r.is_tax_withholding_account), 6)
		self.assertEqual((claim.tds_amount, claim.net_payable), (6, 54))
		self.assertFalse(claim.additional_salary)

	def test_the_claim_follows_its_invoice(self):
		claim = self.approved(self.claim(member=self.member))
		invoice = frappe.get_doc("Purchase Invoice", claim.purchase_invoice)
		invoice.submit()
		invoice.cancel()
		self.assertEqual(frappe.db.get_value(CLAIM, claim.name, ["tds_amount", "net_payable"]), (0, 0))

	def test_cancelling_the_claim_deletes_its_draft_invoice(self):
		claim = self.approved(self.claim(member=self.member))
		invoice = claim.purchase_invoice
		claim.cancel()
		self.assertFalse(frappe.db.exists("Purchase Invoice", invoice))

	def test_an_external_examiner_needs_a_supplier(self):
		member = self.external_member("exr-nosupplier@example.com", supplier=False)
		with self.assertRaises(frappe.ValidationError) as caught:
			self.claim(member=member)
		self.assertIn("Supplier", str(caught.exception))


class TestRemunerationRegister(RemunerationFixture):
	def test_register_lists_the_claims_of_the_company(self):
		claim = self.claim()
		_columns, rows = remuneration_register.execute({"company": COLLEGE})
		self.assertEqual([(r["claim"], r["total_amount"]) for r in rows], [(claim.name, 2150)])
		self.assertEqual(remuneration_register.execute({"company": OTHER})[1], [])

	def test_register_is_limited_to_the_users_companies(self):
		self.claim()
		make_user("exr-other@example.com", [OTHER])
		frappe.get_doc("User", "exr-other@example.com").add_roles("Accounts User")
		frappe.set_user("exr-other@example.com")
		self.assertEqual(remuneration_register.execute({"company": COLLEGE})[1], [])
