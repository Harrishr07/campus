"""P3-T20 (M08-10) tests: Consultancy Project (rule, team, agreement), its Sales Invoices with GST by place of supply through
india_compliance, the revenue share of a fully paid invoice (split, Additional Salary on payroll, never before receipt,
once per invoice) and the AQAR 3.5.1 / NIRF consultancy revenue report and data points.

Fixture: Consultancy Test College (Gujarat, GSTIN 24AAQCA8719H1ZC); a Gujarat client (24AANFA2641L1ZF) and a Karnataka
client (29AABCR1718E1ZL); agreement 1,00,000 before GST; rule 50 / 40 / 10 with two faculty (60 / 40) and one staff.
Hand figures for an invoice of 10,000: GST 18% = 1,800 (CGST 900 + SGST 900 in state, IGST 1,800 across); institution
5,000, faculty 4,000 (2,400 and 1,600), staff 1,000.
"""

import frappe
from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return
from frappe.tests import UnitTestCase
from frappe.utils import get_first_day, get_last_day, today

from campus.campus_platform.approvals import approve, request_approval
from campus.campus_platform.mandatory_approval import seed_mandatory_approval
from campus.iqac import registry
from campus.research import consultancy, consultancy_rules
from campus.research.report.consultancy_revenue import consultancy_revenue
from campus.research.setup import seed_research
from campus.tests.factories import make_company, make_user
from campus.tests.finance_factories import ensure_fiscal_years, ensure_selling_setup, make_company_with_accounts
from campus.tests.utils import CampusTestCase

COLLEGE, ABBR = "Consultancy Test College", "CONT"
OTHER, OTHER_ABBR = "Consultancy Other College", "CONO"
COLLEGE_GSTIN, LOCAL_GSTIN, KARNATAKA_GSTIN = "24AAQCA8719H1ZC", "24AANFA2641L1ZF", "29AABCR1718E1ZL"
YEAR = "Consultancy Test Year"
SAC = "998311"
ITEM = "CON-TEST-SERVICE"
STRUCTURE = "CON Test Structure"
ACCOUNTS = "con-accounts@example.com"
PRINCIPAL = "con-principal@example.com"
ACCOUNTS2 = "con-accounts2@example.com"
SHARE = consultancy.SHARE


class TestShareRules(UnitTestCase):
	def test_the_three_shares_must_total_100(self):
		consultancy_rules.check_rule(50, 40, 10)
		with self.assertRaises(frappe.ValidationError):
			consultancy_rules.check_rule(50, 40, 5)

	def test_a_share_outside_0_to_100_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			consultancy_rules.check_rule(120, -20, 0)

	def test_pools_round_to_the_institution(self):
		self.assertEqual(consultancy_rules.split_pools(10000, 50, 40, 10), (5000, 4000, 1000))
		self.assertEqual(consultancy_rules.split_pools(100.01, 33.34, 33.33, 33.33), (33.35, 33.33, 33.33))

	def test_a_pool_needs_members_and_an_empty_pool_has_none(self):
		with self.assertRaises(frappe.ValidationError):
			consultancy_rules.check_team([frappe._dict(employee="E1", category="Faculty", share_percent=100)], {"Faculty": 40, "Staff": 10})
		with self.assertRaises(frappe.ValidationError):
			consultancy_rules.check_team([frappe._dict(employee="E1", category="Staff", share_percent=100)], {"Faculty": 0, "Staff": 0})

	def test_blank_shares_are_equal_and_given_shares_total_100(self):
		team = [frappe._dict(employee=e, category="Faculty") for e in ("E1", "E2", "E3")]
		consultancy_rules.check_team(team, {"Faculty": 30})
		self.assertEqual([m.share_percent for m in team], [33.33, 33.33, 33.34])
		with self.assertRaises(frappe.ValidationError):
			consultancy_rules.check_team([frappe._dict(employee="E1", category="Faculty", share_percent=60)], {"Faculty": 30})

	def test_an_employee_is_listed_once(self):
		team = [frappe._dict(employee="E1", category="Faculty", share_percent=100), frappe._dict(employee="E1", category="Staff", share_percent=100)]
		with self.assertRaises(frappe.ValidationError):
			consultancy_rules.check_team(team, {"Faculty": 40, "Staff": 10})

	def test_member_amounts_divide_each_pool_and_the_last_takes_the_remainder(self):
		team = [
			frappe._dict(category="Faculty", share_percent=33.33), frappe._dict(category="Staff", share_percent=100),
			frappe._dict(category="Faculty", share_percent=66.67),
		]  # fmt: skip
		self.assertEqual(consultancy_rules.member_amounts(team, {"Faculty": 100, "Staff": 7}), [33.33, 7, 66.67])


class ConsultancyFixture(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_fiscal_years()
		ensure_selling_setup()
		make_company_with_accounts(COLLEGE, ABBR)
		make_company(OTHER, OTHER_ABBR)
		if not frappe.db.exists("Gender", "Male"):
			frappe.get_doc({"doctype": "Gender", "gender": "Male"}).insert()
		make_user(ACCOUNTS, [COLLEGE])
		frappe.get_doc("User", ACCOUNTS).add_roles("Accounts Manager", "Accounts User")
		make_user(ACCOUNTS2, [COLLEGE])
		frappe.get_doc("User", ACCOUNTS2).add_roles("Accounts Manager", "Accounts User")
		make_user(PRINCIPAL, [COLLEGE])
		frappe.get_doc("User", PRINCIPAL).add_roles("Principal")

	def setUp(self):
		frappe.db.savepoint("consultancy_test")
		self.addCleanup(frappe.db.rollback, save_point="consultancy_test")
		seed_research()
		seed_mandatory_approval()
		if not frappe.db.exists("GST HSN Code", SAC):
			frappe.get_doc({"doctype": "GST HSN Code", "hsn_code": SAC, "description": "Management consulting"}).insert()
		if not frappe.db.exists("Item", ITEM):
			frappe.get_doc(
				{"doctype": "Item", "item_code": ITEM, "item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"), "stock_uom": "Nos", "is_stock_item": 0,
				 "gst_hsn_code": SAC, "description": "Consultancy services"}
			).insert()  # fmt: skip
		self.address("Company", COLLEGE, COLLEGE_GSTIN, "Gujarat", "380015", is_company_address=1)
		self.local_client = self.customer("CON Gujarat Client", LOCAL_GSTIN, "Gujarat", "380015")
		self.outside_client = self.customer("CON Karnataka Client", KARNATAKA_GSTIN, "Karnataka", "560001")
		self.faculty1, self.faculty2, self.staff = (self.employee(name) for name in ("Fac1", "Fac2", "Staff"))
		if not frappe.db.exists("Academic Year", YEAR):
			frappe.get_doc({"doctype": "Academic Year", "academic_year_name": YEAR, "year_start_date": get_first_day(today()),
				"year_end_date": get_last_day(today())}).insert()  # fmt: skip

	# fixtures
	def address(self, link_doctype, link_name, gstin, state, pincode, **values):
		return frappe.get_doc(
			{
				"doctype": "Address", "address_title": link_name, "address_type": "Billing", "address_line1": "1 Test Road",
				"city": "Test City", "state": state, "pincode": pincode, "country": "India", "gstin": gstin,
				"gst_category": "Registered Regular" if gstin else "Unregistered", "is_primary_address": 1,
				"links": [{"link_doctype": link_doctype, "link_name": link_name}], **values,
			}
		).insert().name  # fmt: skip

	def customer(self, name, gstin, state, pincode):
		frappe.get_doc(
			{"doctype": "Customer", "customer_name": name, "customer_type": "Company", "gstin": gstin, "gst_category": "Registered Regular"}
		).insert()  # fmt: skip
		return frappe._dict(name=name, address=self.address("Customer", name, gstin, state, pincode))

	def employee(self, first_name, company=COLLEGE):
		return frappe.get_doc(
			{
				"doctype": "Employee", "first_name": first_name, "last_name": frappe.generate_hash(length=6), "gender": "Male",
				"date_of_birth": "1980-01-01", "date_of_joining": "2010-01-01", "company": company,
			}  # fmt: skip
		).insert().name

	def salary_structures(self):
		"""Basic = base 20,000 for each team member, and a holiday list for the slips."""
		frappe.get_doc(
			{
				"doctype": "Salary Structure", "name": STRUCTURE, "company": COLLEGE, "currency": "INR", "payroll_frequency": "Monthly",
				"is_active": "Yes", "earnings": [{"salary_component": "Basic", "amount_based_on_formula": 1, "formula": "base"}],
			}
		).insert().submit()  # fmt: skip
		holidays = frappe.get_doc(
			{"doctype": "Holiday List", "holiday_list_name": "CON Test", "from_date": "2026-01-01", "to_date": "2027-12-31"}
		).insert()  # fmt: skip
		frappe.get_doc(
			{"doctype": "Holiday List Assignment", "applicable_for": "Company", "assigned_to": COLLEGE, "holiday_list": holidays.name, "from_date": "2026-01-01"}
		).insert().submit()  # fmt: skip
		for employee in (self.faculty1, self.faculty2, self.staff):
			frappe.get_doc(
				{"doctype": "Salary Structure Assignment", "employee": employee, "company": COLLEGE, "from_date": "2026-01-01",
				 "salary_structure": STRUCTURE, "base": 20000, "currency": "INR"}
			).insert().submit()  # fmt: skip

	def project(self, client=None, **values):
		client = client or self.local_client
		return frappe.get_doc(
			{
				"doctype": "Consultancy Project", "title": "Water audit", "company": COLLEGE, "client": client.name,
				"client_address": client.address, "principal_consultant": self.faculty1, "service_item": ITEM,
				"status": "Agreed", "agreement_date": today(), "agreement_value": 100000, "estimate_amount": 100000,
				"institution_percent": 50, "faculty_percent": 40, "staff_percent": 10,
				"team": [
					{"employee": self.faculty1, "category": "Faculty", "share_percent": 60},
					{"employee": self.faculty2, "category": "Faculty", "share_percent": 40},
					{"employee": self.staff, "category": "Staff"},
				],
				"deliverables": [{"deliverable": "Audit report", "due_date": today()}], **values,
			}  # fmt: skip
		).insert()

	def invoice(self, project, amount=10000, submit=True):
		invoice = consultancy.draft_sales_invoice(project, amount)
		if submit:
			invoice.submit()
		return invoice

	def pay(self, invoice, amount=None):
		entry = get_payment_entry("Sales Invoice", invoice.name, party_amount=amount, bank_account=f"Cash - {ABBR}")
		entry.reference_no, entry.reference_date = "UTR-CON-1", today()
		entry.insert()
		entry.submit()
		return entry

	def share(self, project, invoice, submit=True):
		"""A share; submitted means approved by Accounts, then the Principal."""
		share = frappe.get_doc({"doctype": SHARE, "consultancy_project": project.name, "sales_invoice": invoice.name}).insert()
		if submit:
			request = request_approval(SHARE, share.name)
			for approver in (ACCOUNTS, PRINCIPAL):
				self.act_as(approver, approve, request)
			share = frappe.get_doc(SHARE, share.name)
		return share

	@staticmethod
	def act_as(user, method, *args):
		frappe.set_user(user)
		try:
			return method(*args)
		finally:
			frappe.set_user("Administrator")

	def paid_share(self, **values):
		"""A project with a paid invoice of 10,000 and its draft share."""
		project = self.project(**values)
		invoice = self.invoice(project)
		payment = self.pay(invoice)
		return project, invoice, payment

	@staticmethod
	def taxes(invoice):
		return {row.account_head: row.tax_amount for row in invoice.taxes}


class TestInvoiceGST(ConsultancyFixture):
	def test_a_client_in_the_colleges_state_is_charged_cgst_and_sgst(self):
		invoice = self.invoice(self.project())
		self.assertEqual(invoice.place_of_supply, "24-Gujarat")
		self.assertEqual(self.taxes(invoice), {f"Output Tax CGST - {ABBR}": 900, f"Output Tax SGST - {ABBR}": 900})
		self.assertEqual((invoice.net_total, invoice.grand_total), (10000, 11800))
		self.assertEqual(invoice.items[0].gst_hsn_code, SAC)

	def test_a_client_in_another_state_is_charged_igst(self):
		invoice = self.invoice(self.project(self.outside_client))
		self.assertEqual(invoice.place_of_supply, "29-Karnataka")
		self.assertEqual(self.taxes(invoice), {f"Output Tax IGST - {ABBR}": 1800})
		self.assertEqual(invoice.grand_total, 11800)

	def test_india_compliance_refuses_state_tax_on_an_inter_state_supply(self):
		invoice = self.invoice(self.project(self.outside_client), submit=False)
		invoice.taxes_and_charges = f"Output GST In-state - {ABBR}"
		invoice.set("taxes", [])
		invoice.append_taxes_from_master("Sales Taxes and Charges Template")
		self.assertEqual({row.account_head for row in invoice.taxes}, {f"Output Tax CGST - {ABBR}", f"Output Tax SGST - {ABBR}"})
		with self.assertRaises(frappe.ValidationError) as caught:
			invoice.save()
		self.assertIn("Inter-State", str(caught.exception).title())

	def test_the_invoice_bills_the_project(self):
		project = self.project()
		invoice = self.invoice(project, submit=False)
		self.assertEqual(
			(invoice.docstatus, invoice.company, invoice.customer, invoice.oc_consultancy_project, invoice.items[0].item_code),
			(0, COLLEGE, self.local_client.name, project.name, ITEM),
		)

	def test_a_project_is_invoiced_only_once_agreed(self):
		project = self.project(status="Estimate")
		with self.assertRaises(frappe.ValidationError):
			consultancy.draft_sales_invoice(project, 10000)

	def test_invoices_never_exceed_the_agreement_value(self):
		project = self.project()
		self.invoice(project, 90000)
		with self.assertRaises(frappe.ValidationError):
			consultancy.draft_sales_invoice(project, 10001)
		draft = self.invoice(project, 10000, submit=False)
		other = self.invoice(project, 5000, submit=False)
		draft.submit()
		with self.assertRaises(frappe.ValidationError) as caught:
			other.submit()
		self.assertIn("agreement value", str(caught.exception))

	def test_an_invoice_for_another_customer_is_not_submitted(self):
		invoice = self.invoice(self.project(), submit=False)
		invoice.customer = self.outside_client.name
		invoice.customer_address = self.outside_client.address
		invoice.save()
		with self.assertRaises(frappe.ValidationError):
			invoice.submit()

	def test_the_agreement_value_cant_drop_below_what_is_invoiced(self):
		project = self.project()
		self.invoice(project, 60000)
		project.reload()
		project.agreement_value = 50000
		with self.assertRaises(frappe.ValidationError):
			project.save()

	def test_an_agreed_project_needs_its_agreement(self):
		with self.assertRaises(frappe.ValidationError):
			self.project(agreement_value=0)


class TestRevenueShare(ConsultancyFixture):
	def test_no_share_before_payment_is_received(self):
		project = self.project()
		invoice = self.invoice(project)
		with self.assertRaises(frappe.ValidationError) as caught:
			self.share(project, invoice)
		self.assertIn("not fully paid", str(caught.exception))
		self.pay(invoice, 5000)
		with self.assertRaises(frappe.ValidationError):
			self.share(project, invoice)

	def test_a_paid_invoice_is_shared_by_the_rule_and_paid_through_payroll(self):
		self.salary_structures()
		project = self.project()
		invoice = self.invoice(project)
		self.pay(invoice)
		share = self.share(project, invoice)
		self.assertEqual(
			(share.taxable_amount, share.institution_amount, share.faculty_amount, share.staff_amount), (10000, 5000, 4000, 1000)
		)
		amounts = {m.employee: m.amount for m in share.members}
		self.assertEqual(amounts, {self.faculty1: 2400, self.faculty2: 1600, self.staff: 1000})
		for member in share.members:
			additional = frappe.get_doc("Additional Salary", frappe.db.get_value(member.doctype, member.name, "additional_salary"))
			self.assertEqual(
				(additional.docstatus, additional.employee, additional.salary_component, additional.amount, str(additional.payroll_date)),
				(1, member.employee, consultancy.SALARY_COMPONENT, member.amount, today()),
			)
			self.assertEqual((additional.ref_doctype, additional.ref_docname), (SHARE, share.name))
		slip = frappe.get_doc(
			{"doctype": "Salary Slip", "employee": self.faculty1, "start_date": get_first_day(today()), "end_date": get_last_day(today()),
			 "posting_date": get_last_day(today()), "payroll_frequency": "Monthly"}
		).insert()  # fmt: skip
		self.assertEqual({r.salary_component: r.amount for r in slip.earnings}.get(consultancy.SALARY_COMPONENT), 2400)

	def test_an_invoice_is_shared_once(self):
		self.salary_structures()
		project = self.project()
		invoice = self.invoice(project)
		self.pay(invoice)
		self.share(project, invoice)
		with self.assertRaises(frappe.ValidationError) as caught:
			self.share(project, invoice)
		self.assertIn("already shared", str(caught.exception))

	def test_the_payment_state_is_checked_again_at_submit(self):
		self.salary_structures()
		project, invoice, _payment = self.paid_share()
		share = self.share(project, invoice, submit=False)
		request = request_approval(SHARE, share.name)
		self.act_as(ACCOUNTS, approve, request)
		frappe.db.set_value("Sales Invoice", invoice.name, "outstanding_amount", 100)  # as a payment taken off meanwhile
		with self.assertRaises(frappe.ValidationError):
			self.act_as(PRINCIPAL, approve, request)
		self.assertEqual(frappe.db.get_value(SHARE, share.name, "docstatus"), 0)

	def test_another_projects_invoice_cant_be_shared(self):
		project, other = self.project(), self.project()
		invoice = self.invoice(other)
		self.pay(invoice)
		with self.assertRaises(frappe.ValidationError):
			self.share(project, invoice)

	def test_a_credited_invoice_isnt_shared(self):
		project = self.project()
		invoice = self.invoice(project)
		credit = make_sales_return(invoice.name)
		credit.insert()
		credit.submit()
		with self.assertRaises(frappe.ValidationError) as caught:
			self.share(project, invoice)
		self.assertIn("credit notes", str(caught.exception))

	def test_a_shared_invoice_its_payment_and_its_rule_stay(self):
		self.salary_structures()
		project = self.project()
		invoice = self.invoice(project)
		payment = self.pay(invoice)
		share = self.share(project, invoice)
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Payment Entry", payment.name).cancel()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Sales Invoice", invoice.name).cancel()
		credit = make_sales_return(invoice.name)
		credit.insert()
		with self.assertRaises(frappe.ValidationError):
			credit.submit()
		project.reload()
		project.institution_percent, project.faculty_percent = 60, 30
		with self.assertRaises(frappe.ValidationError):
			project.save()
		share.reload()
		share.cancel()
		for member in share.members:
			self.assertEqual(frappe.db.get_value("Additional Salary", member.additional_salary, "docstatus"), 2)
		frappe.get_doc("Payment Entry", payment.name).cancel()

	def test_the_team_is_paid_by_its_own_college(self):
		with self.assertRaises(frappe.ValidationError):
			self.project(team=[{"employee": self.employee("Out", OTHER), "category": "Faculty"}, {"employee": self.staff, "category": "Staff"}])

	def test_the_share_is_approved_by_accounts_then_the_principal(self):
		self.salary_structures()
		project, invoice, _payment = self.paid_share()
		share = self.share(project, invoice, submit=False)
		with self.assertRaises(frappe.ValidationError) as caught:
			share.submit()
		self.assertIn("needs approval", str(caught.exception))
		request = request_approval(SHARE, share.name)
		self.act_as(ACCOUNTS, approve, request)
		self.assertEqual(frappe.db.get_value(SHARE, share.name, "docstatus"), 0)
		self.act_as(PRINCIPAL, approve, request)
		share = frappe.get_doc(SHARE, share.name)
		self.assertEqual(share.docstatus, 1)
		self.assertTrue(all(m.additional_salary for m in share.members))

	def test_a_share_never_submits_without_a_policy(self):
		project, invoice, _payment = self.paid_share()
		share = self.share(project, invoice, submit=False)
		frappe.db.set_value("Approval Policy", {"document_type": SHARE}, "enabled", 0)
		with self.assertRaises(frappe.ValidationError) as caught:
			request_approval(SHARE, share.name)
		self.assertIn("No approval policy", str(caught.exception))

	def test_a_team_member_does_not_approve_their_own_share(self):
		self.salary_structures()
		frappe.db.set_value("Employee", self.faculty2, "user_id", ACCOUNTS)
		project, invoice, _payment = self.paid_share()
		share = self.share(project, invoice, submit=False)
		request = request_approval(SHARE, share.name)
		with self.assertRaises(frappe.PermissionError):
			self.act_as(ACCOUNTS, approve, request)
		self.act_as(ACCOUNTS2, approve, request)
		self.act_as(PRINCIPAL, approve, request)
		self.assertEqual(frappe.db.get_value(SHARE, share.name, "docstatus"), 1)

	def test_members_are_active_employees_of_the_college_at_share_time(self):
		project, invoice, _payment = self.paid_share()
		frappe.db.set_value("Employee", self.faculty2, "company", OTHER)  # as an Employee Transfer
		with self.assertRaises(frappe.ValidationError) as caught:
			self.share(project, invoice, submit=False)
		self.assertIn("not Active Employees", str(caught.exception))
		frappe.db.set_value("Employee", self.faculty2, {"company": COLLEGE, "status": "Left"})
		with self.assertRaises(frappe.ValidationError):
			self.share(project, invoice, submit=False)

	def test_members_are_checked_again_at_submit(self):
		project, invoice, _payment = self.paid_share()
		share = self.share(project, invoice, submit=False)
		request = request_approval(SHARE, share.name)
		self.act_as(ACCOUNTS, approve, request)
		frappe.db.set_value("Employee", self.staff, "company", OTHER)
		with self.assertRaises(frappe.ValidationError):
			self.act_as(PRINCIPAL, approve, request)

	def test_a_payment_of_a_shared_invoice_cant_be_unreconciled(self):
		self.salary_structures()
		project, invoice, payment = self.paid_share()
		self.share(project, invoice)
		unreconcile = frappe.new_doc("Unreconcile Payment")
		unreconcile.update({"company": COLLEGE, "voucher_type": "Payment Entry", "voucher_no": payment.name})
		unreconcile.add_references()
		unreconcile.insert()
		with self.assertRaises(frappe.ValidationError) as caught:
			unreconcile.submit()
		self.assertIn("shared consultancy invoice", str(caught.exception))
		self.assertEqual(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount"), 0)

	def test_a_journal_receipt_of_a_shared_invoice_cant_be_cancelled(self):
		self.salary_structures()
		project = self.project()
		invoice = self.invoice(project)
		receipt = self.journal(invoice, f"Cash - {ABBR}")
		self.share(project, invoice)
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Journal Entry", receipt.name).cancel()

	def test_a_journal_without_bank_or_cash_is_not_a_receipt(self):
		project = self.project()
		invoice = self.invoice(project)
		write_off = self.journal(invoice, frappe.db.get_value("Company", COLLEGE, "write_off_account"))
		with self.assertRaises(frappe.ValidationError) as caught:
			self.share(project, invoice, submit=False)
		self.assertIn(write_off.name, str(caught.exception))

	def test_a_written_off_invoice_is_not_shared(self):
		project = self.project()
		invoice = self.invoice(project)
		frappe.db.set_value(  # as a POS invoice written off at the counter
			"Sales Invoice", invoice.name, {"write_off_amount": invoice.grand_total, "base_write_off_amount": invoice.grand_total, "outstanding_amount": 0}
		)  # fmt: skip
		with self.assertRaises(frappe.ValidationError) as caught:
			self.share(project, invoice, submit=False)
		self.assertIn("write-off", str(caught.exception))

	def journal(self, invoice, account):
		"""A submitted Journal Entry settling the invoice's total against `account`."""
		if not frappe.db.exists("Party Type", "Customer"):  # bare test site: no ERPNext setup data
			frappe.get_doc({"doctype": "Party Type", "party_type": "Customer", "account_type": "Receivable"}).insert()
		frappe.db.set_value("Party Type", "Customer", "account_type", "Receivable")
		entry = frappe.get_doc(
			{
				"doctype": "Journal Entry", "company": COLLEGE, "posting_date": today(), "cheque_no": "CON-JE", "cheque_date": today(),
				"accounts": [
					{"account": invoice.debit_to, "party_type": "Customer", "party": invoice.customer, "credit_in_account_currency": invoice.grand_total,
						"reference_type": "Sales Invoice", "reference_name": invoice.name},
					{"account": account, "debit_in_account_currency": invoice.grand_total,
						"cost_center": frappe.db.get_value("Company", COLLEGE, "cost_center")},
				],
			}
		).insert()  # fmt: skip
		entry.submit()
		return entry


class TestConsultancyRevenue(ConsultancyFixture):
	def setUp(self):
		super().setUp()
		self.salary_structures()
		self.first = self.project()
		paid = self.invoice(self.first, 10000)
		self.pay(paid)
		self.share(self.first, paid)
		credited = self.invoice(self.first, 3000)
		credit = make_sales_return(credited.name)
		credit.insert()
		credit.submit()
		self.second = self.project(self.outside_client)
		self.invoice(self.second, 20000)
		self.invoice(self.project(), 7000, submit=False)  # a draft is no revenue

	def test_revenue_is_the_taxable_value_net_of_credit_notes(self):
		point = registry.data_point("consultancy_revenue", COLLEGE, YEAR)
		self.assertEqual(point["value"], 30000)
		self.assertEqual(len(point["records"]), 4)

	def test_projects_and_clients_count_once(self):
		self.invoice(self.second, 1000)
		self.assertEqual(registry.data_point("consultancy_projects", COLLEGE, YEAR)["value"], 2)
		self.assertEqual(registry.data_point("consultancy_clients", COLLEGE, YEAR)["value"], 2)

	def test_another_college_has_none(self):
		self.assertEqual(registry.data_point("consultancy_revenue", OTHER, YEAR)["value"], 0)
		self.assertEqual(registry.data_point("consultancy_received", OTHER, YEAR)["value"], 0)

	def test_received_is_the_years_receipts_before_gst(self):
		point = registry.data_point("consultancy_received", COLLEGE, YEAR)
		self.assertEqual(point["value"], 10000)  # 11,800 received on a 10,000 + GST invoice; the unpaid ones add nothing
		self.assertEqual(len(point["records"]), 1)

	def test_report_shows_gst_received_and_shares_by_project(self):
		_columns, rows = consultancy_revenue.execute({"company": COLLEGE, "academic_year": YEAR})
		by_project = {row.consultancy_project: row for row in rows}
		first, second = by_project[self.first.name], by_project[self.second.name]
		self.assertEqual(
			(first.invoices, first.taxable_value, first.gst, first.received, first.institution_share, first.faculty_share, first.staff_share),
			(2, 10000, 1800, 11800, 5000, 4000, 1000),
		)
		self.assertEqual(first.paid_not_shared, 0)  # the credited invoice has outstanding nil but was never received
		self.pay(frappe.get_doc("Sales Invoice", {"oc_consultancy_project": self.second.name, "docstatus": 1}))
		rows = consultancy_revenue.execute({"company": COLLEGE, "academic_year": YEAR})[1]
		self.assertEqual(next(r for r in rows if r.consultancy_project == self.second.name).paid_not_shared, 1)
		self.assertEqual((second.taxable_value, second.gst, second.received, second.faculty_share), (20000, 3600, 0, 0))
		self.assertEqual(consultancy_revenue.execute({"company": OTHER})[1], [])
