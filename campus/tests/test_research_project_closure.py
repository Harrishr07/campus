"""P3-T19 (M08-08, M08-09) integration tests: project staff paid through payroll on the sanction, progress reports on
ERPNext Project Update, and project closure (final UC, unspent refunded or retained, project closed, no further spend).

Fixture: the shared research college with a fourth, revenue head "RSA Manpower" (account "RSA Manpower - RSAT",
Budget 300,000 in year 1). A Junior Research Fellow (employment type Project Staff) on the "Fellowship" component
(formula `base`, account RSA Manpower) at base 37,000 is paid for the current month: the accrual posts 37,000 to the
Manpower head on the sanction's cost centre and project, and the UC counts it as Manpower expenditure.

Closure: the first instalment (60% of 1,150,000 = 690,000) received and 20,000 consumables spent, so the final UC
(sanction start to today) closes with 670,000 unspent, which the closure refunds (or retains under the agency letter)."""

import frappe
from frappe.utils import add_days, get_first_day, get_last_day, getdate, today

from campus.campus_platform.approvals import approve, request_approval
from campus.research.budget_control import BUDGET_HEAD_FIELD, refuse_payment_cancel_on_closed, validate_payment_deductions
from campus.research.setup import PROJECT_STAFF, seed_research
from campus.research.utilisation import recheck_queued, utilisation_figures
from campus.tests.factories import make_user
from campus.tests.finance_factories import make_account
from campus.tests.research_fixtures import ABBR, COLLEGE, SanctionFixtures

PI_USER = "pcl-pi@example.com"
ACCOUNTS_USER = "pcl-accounts@example.com"
PRINCIPAL_USER = "pcl-principal@example.com"
FELLOWSHIP = "Fellowship"
JRF = "Junior Research Fellow"
UC = "Utilisation Certificate"


class ProjectFixtures(SanctionFixtures):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for user, role in ((PI_USER, None), (ACCOUNTS_USER, "Accounts Manager"), (PRINCIPAL_USER, "Principal")):
			make_user(user, [COLLEGE])
			if role:
				frappe.get_doc("User", user).add_roles(role)

	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		seed_research()
		employee = frappe.get_doc("Employee", self.pi)
		employee.user_id = PI_USER
		employee.save()
		self.manpower_account = make_account(COLLEGE, ABBR, "RSA Manpower", "Indirect Expenses")
		self.manpower = self.make_head("RSA Manpower", [(COLLEGE, self.manpower_account)])
		self.project_scheme = self.make_scheme("RSA Project Grant", [self.consumables, self.travel, self.equipment, self.manpower])
		self.month_start, self.month_end = get_first_day(today()), get_last_day(today())
		self.set_up_payroll()

	def project_sanction(self):
		heads = [*self.heads(), (self.manpower, self.year1.name, 300000)]
		sanction = self.sanction(heads=heads, scheme=self.project_scheme)
		sanction.submit()
		return sanction.reload()

	# payroll
	def set_up_payroll(self):
		component = frappe.get_doc("Salary Component", FELLOWSHIP)
		component.set("accounts", [{"company": COLLEGE, "account": self.manpower_account}])
		component.save()
		holiday_list = frappe.get_doc(
			{"doctype": "Holiday List", "holiday_list_name": f"RSA Project {frappe.generate_hash(length=4)}",
			 "from_date": self.year1.start, "to_date": self.year2.end}
		).insert(ignore_permissions=True)  # fmt: skip
		frappe.get_doc(
			{"doctype": "Holiday List Assignment", "applicable_for": "Company", "assigned_to": COLLEGE,
			 "holiday_list": holiday_list.name, "from_date": self.year1.start}
		).insert(ignore_permissions=True).submit()  # fmt: skip
		payable = frappe.db.get_value("Company", COLLEGE, "default_payroll_payable_account") or make_account(
			COLLEGE, ABBR, "RSA Payroll Payable", "Current Liabilities", root_type="Liability"
		)
		frappe.db.set_value("Account", payable, "account_type", "Payable")
		frappe.db.set_value("Company", COLLEGE, "default_payroll_payable_account", payable)
		self.structure = self.make_structure("RSA Fellowship", FELLOWSHIP)

	def make_structure(self, name, component):
		structure = frappe.get_doc(
			{
				"doctype": "Salary Structure", "name": name, "company": COLLEGE, "payroll_frequency": "Monthly",
				"currency": frappe.get_cached_value("Company", COLLEGE, "default_currency"), "is_active": "Yes",
				"earnings": [{"salary_component": component, "abbr": frappe.get_cached_value("Salary Component", component, "salary_component_abbr"),
					"amount_based_on_formula": 1, "formula": "base"}],
			}  # fmt: skip
		).insert()
		structure.submit()
		return structure.name

	def project_staff(self, employment_type=PROJECT_STAFF):
		employee = frappe.get_doc("Employee", self.make_employee("Fellow", COLLEGE))
		employee.employment_type = employment_type
		employee.save()
		return employee.name

	def appointment(self, sanction, employee, structure=None, **values):
		return frappe.get_doc(
			{
				"doctype": "Project Staff Appointment", "sanction": sanction.name, "employee": employee, "designation": JRF,
				"from_date": sanction.start_date, "salary_structure": structure or self.structure, "base": 37000, **values,
			}  # fmt: skip
		).insert()

	def run_payroll(self, posting_date=None):
		company = frappe.get_cached_doc("Company", COLLEGE)
		entry = frappe.new_doc("Payroll Entry")
		entry.update(
			{
				"company": COLLEGE, "posting_date": posting_date or self.month_end, "payroll_frequency": "Monthly",
				"start_date": self.month_start, "end_date": self.month_end, "currency": company.default_currency,
				"exchange_rate": 1, "cost_center": company.cost_center,
				"payroll_payable_account": company.default_payroll_payable_account,
			}
		)  # fmt: skip
		entry.fill_employee_details()
		entry.insert(ignore_permissions=True)
		entry.submit()
		entry.submit_salary_slips()
		return entry.reload()

	def accrual_entry(self, payroll_entry):
		return frappe.db.get_value(
			"Journal Entry Account", {"reference_type": "Payroll Entry", "reference_name": payroll_entry.name, "docstatus": 1}, "parent"
		)

	# vouchers
	def spend(self, sanction, account, amount, head, posting_date=None):
		entry = frappe.get_doc(
			{
				"doctype": "Journal Entry", "company": COLLEGE, "posting_date": posting_date or today(),
				"accounts": [
					{"account": account, "debit_in_account_currency": amount, "cost_center": sanction.cost_center,
					 "project": sanction.project, BUDGET_HEAD_FIELD: head},
					{"account": self.bank, "credit_in_account_currency": amount, "cost_center": sanction.cost_center},
				],
			}  # fmt: skip
		).insert()
		entry.submit()
		return entry

	def funded(self, sanction):
		receipt = self.receipt(sanction, posting_date=sanction.start_date, reference_date=sanction.start_date)
		receipt.submit()
		entry = self.spend(sanction, self.consumables_account, 20000, self.consumables, posting_date=add_days(today(), -2))
		return receipt, entry

	def recognise(self, sanction, to_date):
		recognition = frappe.get_doc(
			{"doctype": "Grant Income Recognition", "company": COLLEGE, "from_date": sanction.start_date, "to_date": to_date,
			 "sanctions": [{"sanction": sanction.name}]}
		).insert()  # fmt: skip
		recognition.submit()
		return recognition

	def approve_all(self, uc):
		request = request_approval(UC, uc.name)
		for user in (PI_USER, ACCOUNTS_USER, PRINCIPAL_USER):
			frappe.set_user(user)
			try:
				approve(request, None)
			finally:
				frappe.set_user("Administrator")
		return uc.reload()

	def final_uc(self, sanction, to_date=None, recognised=True):
		"""The approved final UC to `to_date` (default today), with grant income recognised to it first."""
		to_date = to_date or today()
		if recognised:
			self.recognise(sanction, to_date)
		return self.approve_all(
			frappe.get_doc({"doctype": UC, "sanction": sanction.name, "from_date": sanction.start_date, "to_date": to_date}).insert()
		)

	def closure(self, sanction, uc, **values):
		return frappe.get_doc(
			{
				"doctype": "Project Closure", "sanction": sanction.name, "final_uc": uc.name if uc else None,
				"posting_date": add_days(uc.to_date if uc else today(), 1), "treatment": "Refund to Agency",
				"paid_from": self.bank, "reference_no": "RFND0001", "reference_date": add_days(today(), 1), **values,
			}  # fmt: skip
		)

	def liability_balance(self, sanction):
		return frappe.db.sql(
			"select coalesce(sum(credit - debit), 0) from `tabGL Entry` where account = %s and is_cancelled = 0",
			sanction.liability_account,
		)[0][0]


class TestProjectStaff(ProjectFixtures):
	# acceptance 1: project staff salary posts to the project with head Manpower and counts in the UC
	def test_project_staff_salary_posts_to_the_manpower_head_and_counts_in_the_uc(self):
		sanction = self.project_sanction()
		self.appointment(sanction, self.project_staff()).submit()
		payroll = self.run_payroll()
		entry = self.accrual_entry(payroll)
		self.assertTrue(entry, payroll.error_message)
		[row] = frappe.get_all(
			"Journal Entry Account", {"parent": entry, "account": self.manpower_account},
			["debit", "cost_center", "project", BUDGET_HEAD_FIELD],
		)  # fmt: skip
		self.assertEqual(
			(row.debit, row.cost_center, row.project, row[BUDGET_HEAD_FIELD]),
			(37000, sanction.cost_center, sanction.project, self.manpower),
		)
		figures = utilisation_figures(sanction.name, self.month_start, self.month_end)
		manpower = next(h for h in figures.heads if h.budget_head == self.manpower)
		self.assertEqual((manpower.spent_in_period, manpower.balance), (37000, 263000))
		self.assertEqual(figures.total_expenditure, 37000)
		self.assertEqual(figures.unreconciled, [])

	def test_appointment_assigns_the_structure_on_the_sanction_cost_centre_until_the_sanction_end(self):
		sanction = self.project_sanction()
		employee = self.project_staff()
		appointment = self.appointment(sanction, employee)
		appointment.submit()
		self.assertEqual((appointment.to_date, appointment.budget_head), (getdate(sanction.end_date), self.manpower))
		ssa = frappe.get_doc("Salary Structure Assignment", appointment.salary_structure_assignment)
		self.assertEqual((ssa.docstatus, ssa.employee, ssa.base, ssa.salary_structure), (1, employee, 37000, self.structure))
		self.assertEqual([(r.cost_center, r.percentage) for r in ssa.payroll_cost_centers], [(sanction.cost_center, 100)])
		self.assertEqual(
			frappe.db.get_value("Employee", employee, ["contract_end_date", "designation"]), (getdate(sanction.end_date), JRF)
		)
		appointment.cancel()
		self.assertEqual(frappe.db.get_value("Salary Structure Assignment", ssa.name, "docstatus"), 2)

	def test_appointment_needs_project_staff_a_salary_on_a_sanction_head_and_a_date_in_the_period(self):
		sanction = self.project_sanction()
		with self.assertRaisesRegex(frappe.ValidationError, "Project Staff"):
			self.appointment(sanction, self.project_staff("Full-time"))
		employee = self.project_staff()
		other = make_account(COLLEGE, ABBR, "RSA Salaries Elsewhere", "Indirect Expenses")
		component = frappe.get_doc({"doctype": "Salary Component", "salary_component": "RSA Other Pay", "salary_component_abbr": "ROP",
			"type": "Earning", "accounts": [{"company": COLLEGE, "account": other}]}).insert()  # fmt: skip
		with self.assertRaisesRegex(frappe.ValidationError, "not an account of a budget head"):
			self.appointment(sanction, employee, structure=self.make_structure("RSA Other", component.name))
		with self.assertRaisesRegex(frappe.ValidationError, "sanction period"):
			self.appointment(sanction, employee, from_date=add_days(sanction.end_date, 1))
		self.appointment(sanction, employee).submit()
		with self.assertRaisesRegex(frappe.ValidationError, "already"):
			self.appointment(sanction, employee)

	def test_salary_stops_at_the_sanction_end(self):
		end = add_days(self.year2.start, 14)  # mid-month: the 15th of the first month of year 2
		heads = [*self.heads(), (self.manpower, self.year1.name, 300000), (self.manpower, self.year2.name, 100000)]
		sanction = self.sanction(heads=heads, scheme=self.project_scheme, end_date=end)
		sanction.submit()
		employee = self.project_staff()
		appointment = self.appointment(sanction, employee)
		appointment.submit()
		self.assertEqual(frappe.db.get_value("Employee", employee, "relieving_date"), getdate(end))
		self.month_start, self.month_end = get_first_day(end), get_last_day(end)
		payroll = self.run_payroll(posting_date=end)
		slip = frappe.get_doc("Salary Slip", {"payroll_entry": payroll.name, "employee": employee})
		days = (getdate(self.month_end) - getdate(self.month_start)).days + 1
		self.assertEqual(slip.payment_days, 15)
		self.assertEqual(slip.gross_pay, round(37000 * 15 / days, 2))

	def test_cancelling_the_appointment_restores_the_employee(self):
		sanction = self.project_sanction()
		employee = self.project_staff()
		frappe.db.set_value("Employee", employee, {"contract_end_date": "2030-01-01", "designation": "Project Assistant"})
		appointment = self.appointment(sanction, employee)
		appointment.submit()
		appointment.cancel()
		self.assertEqual(
			frappe.db.get_value("Employee", employee, ["contract_end_date", "designation", "relieving_date"]),
			(getdate("2030-01-01"), "Project Assistant", None),
		)

	def test_an_employer_contribution_must_post_to_a_sanction_head_too(self):
		sanction = self.project_sanction()
		other = make_account(COLLEGE, ABBR, "RSA Employer PF", "Indirect Expenses")
		component = frappe.get_doc({"doctype": "Salary Component", "salary_component": "RSA Employer PF", "salary_component_abbr": "REPF",
			"type": "Deduction", "accounts": [{"company": COLLEGE, "account": other}]}).insert()  # fmt: skip
		structure = frappe.get_doc(
			{
				"doctype": "Salary Structure", "name": "RSA Fellowship PF", "company": COLLEGE, "payroll_frequency": "Monthly",
				"currency": frappe.get_cached_value("Company", COLLEGE, "default_currency"), "is_active": "Yes",
				"earnings": [{"salary_component": FELLOWSHIP, "abbr": "FEL", "amount_based_on_formula": 1, "formula": "base"}],
				"deductions": [{"salary_component": component.name, "abbr": "REPF", "amount": 100}],
			}  # fmt: skip
		).insert()
		structure.submit()
		with self.assertRaisesRegex(frappe.ValidationError, "not an account of a budget head"):
			self.appointment(sanction, self.project_staff(), structure=structure.name)

	def test_seed_gives_the_project_staff_employment_type_designations_and_fellowship_component(self):
		self.assertTrue(frappe.db.exists("Employment Type", PROJECT_STAFF))
		for designation in (JRF, "Senior Research Fellow", "Project Assistant"):
			self.assertTrue(frappe.db.exists("Designation", designation))
		self.assertEqual(frappe.db.get_value("Salary Component", FELLOWSHIP, "type"), "Earning")


class TestProgressReport(ProjectFixtures):
	def test_progress_report_is_a_project_update_with_period_milestones_and_deliverables(self):
		sanction = self.project_sanction()
		frappe.get_doc({"doctype": "Task", "subject": "Prototype sensor", "project": sanction.project, "is_milestone": 1,
			"exp_end_date": add_days(today(), 10)}).insert()  # fmt: skip
		frappe.get_doc({"doctype": "Task", "subject": "Order chemicals", "project": sanction.project}).insert()
		update = frappe.get_doc(
			{
				"doctype": "Project Update", "project": sanction.project, "date": today(), "oc_report_type": "Progress Report",
				"oc_from_date": sanction.start_date, "oc_to_date": today(), "oc_deliverables": "Two sensors field-tested.",
			}  # fmt: skip
		).insert()
		self.assertEqual(update.oc_sanction, sanction.name)
		self.assertIn("Prototype sensor", update.oc_milestones)
		self.assertNotIn("Order chemicals", update.oc_milestones)
		update.submit()
		review = frappe.get_doc(
			{"doctype": "Project Update", "project": sanction.project, "date": today(), "oc_report_type": "Mid-term Review",
			 "oc_from_date": sanction.start_date, "oc_to_date": today()}
		).insert()  # fmt: skip
		self.assertEqual(review.oc_sanction, sanction.name)

	def test_a_report_on_a_sanction_project_needs_a_type_and_a_period_inside_the_sanction(self):
		sanction = self.project_sanction()
		values = {"doctype": "Project Update", "project": sanction.project, "date": today(), "oc_from_date": sanction.start_date, "oc_to_date": today()}
		with self.assertRaisesRegex(frappe.ValidationError, "report type"):
			frappe.get_doc(values).insert()
		with self.assertRaisesRegex(frappe.ValidationError, "sanction period"):
			frappe.get_doc(values | {"oc_report_type": "Progress Report", "oc_to_date": add_days(sanction.end_date, 1)}).insert()


class TestProjectClosure(ProjectFixtures):
	# acceptance 2: closure is blocked until the final UC is approved and unspent is refunded or retained
	def test_closure_refunds_the_unspent_balance_through_the_liability_and_closes_the_project(self):
		sanction = self.project_sanction()
		self.funded(sanction)
		uc = self.final_uc(sanction)
		self.assertEqual(uc.closing_unspent, 690000 - 20000)
		closure = self.closure(sanction, uc).insert()
		self.assertEqual(closure.unspent_balance, 670000)
		closure.submit()
		rows = {r.account: r for r in frappe.get_all("Journal Entry Account", {"parent": closure.journal_entry},
			["account", "debit", "credit", "cost_center", "project"])}  # fmt: skip
		self.assertEqual((rows[sanction.liability_account].debit, rows[self.bank].credit), (670000, 670000))
		self.assertEqual(rows[sanction.liability_account].project, sanction.project)
		self.assertEqual(frappe.db.get_value("Journal Entry", closure.journal_entry, "docstatus"), 1)
		self.assertEqual(self.liability_balance(sanction), 0)  # the spent part recognised, the unspent refunded
		self.assertEqual(frappe.db.get_value("Project", sanction.project, "status"), "Completed")
		self.assertEqual(frappe.db.get_value("Sanction", sanction.name, "project_closure"), closure.name)
		recheck_queued()
		self.assertEqual(frappe.db.get_value(UC, uc.name, "source_changed"), 0)  # the refund is after the final UC

	def test_no_spending_receipt_or_appointment_after_closure(self):
		sanction = self.project_sanction()
		self.funded(sanction)
		employee = self.project_staff()
		closure = self.closure(sanction, self.final_uc(sanction)).insert()
		closure.submit()
		with self.assertRaisesRegex(frappe.ValidationError, "closed"):
			self.spend(sanction, self.consumables_account, 100, self.consumables, posting_date=add_days(today(), 2))
		with self.assertRaisesRegex(frappe.ValidationError, "closed"):
			self.receipt(sanction, "Second")
		with self.assertRaisesRegex(frappe.ValidationError, "closed"):
			self.appointment(sanction, employee)

	def test_closure_needs_an_approved_final_uc(self):
		sanction = self.project_sanction()
		self.funded(sanction)
		with self.assertRaises(frappe.MandatoryError):
			self.closure(sanction, None).insert()
		draft = frappe.get_doc({"doctype": UC, "sanction": sanction.name, "from_date": sanction.start_date, "to_date": today()}).insert()
		with self.assertRaisesRegex(frappe.ValidationError, "approved"):
			self.closure(sanction, draft).insert()

	def test_closure_refused_while_the_ledger_moved_after_the_final_uc(self):
		sanction = self.project_sanction()
		self.funded(sanction)
		uc = self.final_uc(sanction, to_date=add_days(today(), -1))
		closure = self.closure(sanction, uc, posting_date=add_days(today(), 1)).insert()
		later = self.spend(sanction, self.travel_account, 500, self.travel)  # after the final UC's period
		with self.assertRaisesRegex(frappe.ValidationError, "after the final"):
			closure.submit()
		later.cancel()
		self.spend(sanction, self.travel_account, 700, self.travel, posting_date=add_days(today(), -3))  # inside it
		closure = self.closure(sanction, uc, posting_date=add_days(today(), 1)).insert()
		with self.assertRaisesRegex(frappe.ValidationError, "changed"):
			closure.submit()
		self.assertFalse(frappe.db.get_value("Sanction", sanction.name, "project_closure"))
		self.assertEqual(frappe.db.get_value("Project", sanction.project, "status"), "Open")

	def test_closure_needs_the_latest_uc_and_a_date_after_it(self):
		sanction = self.project_sanction()
		self.funded(sanction)
		first = self.final_uc(sanction, to_date=add_days(today(), -1))
		second = self.approve_all(
			frappe.get_doc({"doctype": UC, "sanction": sanction.name, "from_date": today(), "to_date": today()}).insert()
		)
		with self.assertRaisesRegex(frappe.ValidationError, "latest"):
			self.closure(sanction, first, posting_date=add_days(today(), 1)).insert().submit()
		with self.assertRaisesRegex(frappe.ValidationError, "after"):
			self.closure(sanction, second, posting_date=today()).insert()

	def test_retaining_needs_the_agency_letter_and_moves_the_unspent_to_the_named_account(self):
		sanction = self.project_sanction()
		self.funded(sanction)
		uc = self.final_uc(sanction)
		retained = make_account(COLLEGE, ABBR, "RSA Retained Grants", "Current Liabilities", root_type="Liability")
		values = {"treatment": "Retain per Agency Letter", "paid_from": None, "reference_no": None, "retained_to": retained}
		with self.assertRaisesRegex(frappe.ValidationError, "agency letter"):
			self.closure(sanction, uc, **values).insert()
		closure = self.closure(
			sanction, uc, **values, agency_letter_no="DST/RET/1", agency_letter_date=today(), agency_letter="/files/letter.pdf"
		).insert()
		closure.submit()
		rows = {r.account: r for r in frappe.get_all("Journal Entry Account", {"parent": closure.journal_entry}, ["account", "debit", "credit"])}
		self.assertEqual((rows[sanction.liability_account].debit, rows[retained].credit), (670000, 670000))
		self.assertEqual(self.liability_balance(sanction), 0)
		self.assertEqual(frappe.db.get_value("Project", sanction.project, "status"), "Completed")

	def test_refund_needs_a_bank_or_cash_ledger(self):
		sanction = self.project_sanction()
		self.funded(sanction)
		with self.assertRaisesRegex(frappe.ValidationError, "bank or cash"):
			self.closure(sanction, self.final_uc(sanction), paid_from=self.consumables_account).insert()

	def test_cancelling_the_closure_reverses_the_refund_and_reopens_the_project(self):
		sanction = self.project_sanction()
		self.funded(sanction)
		closure = self.closure(sanction, self.final_uc(sanction)).insert()
		closure.submit()
		closure.cancel()
		self.assertEqual(frappe.db.get_value("Journal Entry", closure.journal_entry, "docstatus"), 2)
		self.assertEqual(frappe.db.get_value("Project", sanction.project, "status"), "Open")
		self.assertFalse(frappe.db.get_value("Sanction", sanction.name, "project_closure"))
		self.assertEqual(self.liability_balance(sanction), 670000)  # the refund reversed; the recognition stays

	# fix round 1
	def test_closure_needs_grant_income_recognised_to_the_final_uc(self):
		sanction = self.project_sanction()
		self.funded(sanction)
		closure = self.closure(sanction, self.final_uc(sanction, recognised=False)).insert()
		with self.assertRaisesRegex(frappe.ValidationError, "Grant Income Recognition"):
			closure.submit()
		self.assertFalse(frappe.db.get_value("Sanction", sanction.name, "project_closure"))

	def test_no_interest_or_cancels_on_a_closed_sanction(self):
		sanction = self.project_sanction()
		receipt, entry = self.funded(sanction)
		self.closure(sanction, self.final_uc(sanction)).insert().submit()
		with self.assertRaisesRegex(frappe.ValidationError, "closed"):
			frappe.get_doc(
				{"doctype": "Grant Interest", "sanction": sanction.name, "posting_date": add_days(today(), 2), "amount": 10,
				 "received_in": self.bank, "reference_no": "INT1"}
			).insert()  # fmt: skip
		with self.assertRaisesRegex(frappe.ValidationError, "closed"):
			frappe.get_doc("Journal Entry", entry.name).cancel()
		with self.assertRaisesRegex(frappe.ValidationError, "closed"):
			frappe.get_doc("Grant Receipt", receipt.name).cancel()
		self.assertEqual(frappe.db.get_value("Journal Entry", entry.name, "docstatus"), 1)

	def test_payment_entry_deductions_on_a_closed_sanction_are_refused(self):
		self.assertIn(
			"campus.research.budget_control.validate_payment_deductions", frappe.get_hooks("doc_events")["Payment Entry"]["validate"]
		)
		sanction = self.project_sanction()
		self.funded(sanction)
		payment = frappe.get_doc(
			{"doctype": "Payment Entry", "company": COLLEGE,
			 "deductions": [{"account": self.consumables_account, "cost_center": sanction.cost_center, "amount": 10}]}
		)  # fmt: skip
		validate_payment_deductions(payment)  # an open sanction: allowed
		self.closure(sanction, self.final_uc(sanction)).insert().submit()
		with self.assertRaisesRegex(frappe.ValidationError, "closed"):
			validate_payment_deductions(payment)

	def test_retaining_into_a_sanction_liability_is_refused(self):
		sanction = self.project_sanction()
		self.funded(sanction)
		other = self.project_sanction()
		with self.assertRaisesRegex(frappe.ValidationError, "grant liability"):
			self.closure(
				sanction, self.final_uc(sanction), treatment="Retain per Agency Letter", paid_from=None, reference_no=None,
				retained_to=other.liability_account, agency_letter_no="L1", agency_letter_date=today(), agency_letter="/files/l.pdf",
			).insert()  # fmt: skip

	def test_no_extension_re_appropriation_or_new_uc_on_a_closed_sanction(self):
		sanction = self.project_sanction()
		self.funded(sanction)
		self.closure(sanction, self.final_uc(sanction)).insert().submit()
		with self.assertRaisesRegex(frappe.ValidationError, "closed"):
			frappe.get_doc("Sanction", sanction.name).extend_sanction(add_days(sanction.end_date, 30), "EXT/1", today())
		with self.assertRaisesRegex(frappe.ValidationError, "closed"):
			frappe.get_doc(
				{"doctype": "Re-appropriation Request", "sanction": sanction.name, "fiscal_year": self.year2.name,
				 "from_head": self.consumables, "to_head": self.travel, "amount": 100, "agency_letter_no": "R1",
				 "agency_letter_date": today(), "agency_approval_letter": "/files/r.pdf"}
			).insert()  # fmt: skip
		with self.assertRaisesRegex(frappe.ValidationError, "closed"):
			frappe.get_doc({"doctype": UC, "sanction": sanction.name, "from_date": add_days(today(), 1), "to_date": add_days(today(), 2)}).insert()

	def test_cancelling_the_closure_restores_the_project_status(self):
		sanction = self.project_sanction()
		self.funded(sanction)
		frappe.db.set_value("Project", sanction.project, "status", "Cancelled")  # whatever it was before closing
		closure = self.closure(sanction, self.final_uc(sanction)).insert()
		closure.submit()
		self.assertEqual(frappe.db.get_value("Project", sanction.project, "status"), "Completed")
		closure.cancel()
		self.assertEqual(frappe.db.get_value("Project", sanction.project, "status"), "Cancelled")

	# fix round 2
	def test_no_grant_income_recognition_cancel_on_a_closed_sanction(self):
		sanction = self.project_sanction()
		self.funded(sanction)
		uc = self.final_uc(sanction)
		recognition = frappe.get_all(
			"Grant Income Recognition Sanction", {"sanction": sanction.name, "docstatus": 1}, pluck="parent"
		)[0]  # fmt: skip
		self.closure(sanction, uc).insert().submit()
		with self.assertRaisesRegex(frappe.ValidationError, "closed"):
			frappe.get_doc("Grant Income Recognition", recognition).cancel()
		self.assertEqual(frappe.db.get_value("Grant Income Recognition", recognition, "docstatus"), 1)
		self.assertEqual(self.liability_balance(sanction), 0)

	def test_payment_entry_cancel_with_a_deduction_on_a_closed_sanction_is_refused(self):
		before_cancel = frappe.get_hooks("doc_events")["Payment Entry"]["before_cancel"]
		self.assertIn("campus.research.pfms.refuse_exported_cancel", before_cancel)
		self.assertIn("campus.research.budget_control.refuse_payment_cancel_on_closed", before_cancel)
		sanction = self.project_sanction()
		self.funded(sanction)
		payment = frappe.get_doc(
			{"doctype": "Payment Entry", "company": COLLEGE, "docstatus": 1,
			 "deductions": [{"account": self.consumables_account, "cost_center": sanction.cost_center, "amount": 10}]}
		)  # fmt: skip
		refuse_payment_cancel_on_closed(payment)  # an open sanction: allowed
		self.closure(sanction, self.final_uc(sanction)).insert().submit()
		with self.assertRaisesRegex(frappe.ValidationError, "closed"):
			refuse_payment_cancel_on_closed(payment)

	def test_closure_names_a_recognition_posted_after_the_final_uc(self):
		sanction = self.project_sanction()
		self.funded(sanction)
		uc = self.final_uc(sanction, to_date=add_days(today(), -1))
		self.spend(sanction, self.travel_account, 500, self.travel)
		later = self.recognise(sanction, today())
		with self.assertRaisesRegex(frappe.ValidationError, f"Grant Income Recognition {later.name}"):
			self.closure(sanction, uc).insert().submit()
		self.assertFalse(frappe.db.get_value("Sanction", sanction.name, "project_closure"))


class TestProjectStaffFix2(ProjectFixtures):
	def sanction_for(self, start_date, end_date, fiscal_year):
		sanction = self.sanction(
			heads=[(self.manpower, fiscal_year, 300000)], scheme=self.project_scheme, start_date=start_date, end_date=end_date
		)
		sanction.submit()
		return sanction.reload()

	def test_cancelling_an_earlier_appointment_leaves_a_later_appointment_on_the_employee(self):
		first = self.sanction_for(self.year1.start, self.year1.end, self.year1.name)
		second = self.sanction_for(self.year2.start, self.year2.end, self.year2.name)
		employee = self.project_staff()
		frappe.db.set_value("Employee", employee, {"contract_end_date": "2030-01-01", "designation": "Project Assistant"})
		earlier = self.appointment(first, employee)
		earlier.submit()
		later = self.appointment(second, employee, from_date=second.start_date, designation="Senior Research Fellow")
		later.submit()
		earlier.cancel()
		self.assertEqual(
			frappe.db.get_value("Employee", employee, ["contract_end_date", "designation", "relieving_date"]),
			(getdate(second.end_date), "Senior Research Fellow", getdate(second.end_date)),
		)
