"""P2-T10 (M07-07) integration tests: payroll for aided and self-financing staff on HRMS.

Fixture (Demo College of Engineering, September 2026, no leave, a holiday list without holidays, fiscal year 2026-27): the seeded Aided and
Self-financing Salary Structures are submitted as a college would after review, and assigned from 2026-04-01 by
campus.faculty.api.assign_salary_structure.

Hand figures from the seeded structure records:
- faculty_1, Aided, base (pay) 40,000 and variable (AGP) 9,000: Basic 40,000, AGP 9,000, DA 50% of 49,000 = 24,500,
  HRA 10% of 49,000 = 4,900; gross 78,400. PF 12% of (Basic + AGP + DA) 73,500 = 8,820, PT 208; net 69,372.
- faculty_2, Self-financing, base 30,000: Basic 30,000, DA 10% = 3,000, HRA 10% = 3,000; gross 36,000.
  PF 12% of (Basic + DA) 33,000 capped at the 15,000 wage ceiling = 1,800, PT 208; net 33,992.
- faculty_1 after a 3% increment (Employee Promotion from 2026-08-01, new assignment base 41,200): Basic 41,200, AGP 9,000,
  DA 25,100, HRA 5,020; gross 80,320. PF 12% of 75,300 = 9,036, PT 208; net 71,076.
"""

import frappe

from campus.faculty import api
from campus.faculty.payroll_setup import seed_salary_components, seed_salary_structures, structure_name
from campus.tests import demo
from campus.tests.utils import CampusTestCase

START, END = "2026-09-01", "2026-09-30"
ASSIGNED_FROM = "2026-04-01"
AIDED, SELF_FINANCING = "Aided", "Self-financing"


class PayrollFixture(CampusTestCase):
	demo_scale = "small"

	def setUp(self):
		super().setUp()
		frappe.db.savepoint("payroll_test")
		self.company = demo.ENGINEERING
		self.aided, self.self_financing = demo.employee_of("faculty_1"), demo.employee_of("faculty_2")
		seed_salary_components()
		seed_salary_structures(self.company)
		self.make_holiday_list()
		if not frappe.db.exists("Fiscal Year", {"year_start_date": "2026-04-01"}):
			frappe.get_doc(
				{"doctype": "Fiscal Year", "year": "Payroll Test 2026-27", "year_start_date": "2026-04-01", "year_end_date": "2027-03-31"}
			).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback(save_point="payroll_test")
		super().tearDown()

	def submit_structures(self, company=None):
		for mode in (AIDED, SELF_FINANCING):
			frappe.get_doc("Salary Structure", structure_name(mode, company or self.company)).submit()

	def make_holiday_list(self):
		holiday_list = frappe.get_doc(
			{"doctype": "Holiday List", "holiday_list_name": "Payroll Test 2026", "from_date": "2026-01-01", "to_date": "2026-12-31"}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Holiday List Assignment", "applicable_for": "Company", "assigned_to": self.company,
				"holiday_list": holiday_list.name, "from_date": "2026-01-01",
			}
		).insert(ignore_permissions=True).submit()  # fmt: skip

	def assign_demo_staff(self):
		api.assign_salary_structure(self.aided, ASSIGNED_FROM, base=40000, variable=9000)
		api.assign_salary_structure(self.self_financing, ASSIGNED_FROM, base=30000)

	def amounts(self, slip):
		rows = {r.salary_component: r.amount for r in (*slip.earnings, *slip.deductions)}
		return rows, (slip.gross_pay, slip.total_deduction, slip.net_pay)

	def direct_slip(self, employee):
		return frappe.get_doc(
			{"doctype": "Salary Slip", "employee": employee, "start_date": START, "end_date": END, "posting_date": END, "payroll_frequency": "Monthly"}
		).insert(ignore_permissions=True)


AIDED_ROWS = {
	"Basic": 40000, "Academic Grade Pay": 9000, "Dearness Allowance": 24500, "House Rent Allowance": 4900,
	"Provident Fund": 8820, "Professional Tax": 208,
}  # fmt: skip
SELF_FINANCING_ROWS = {"Basic": 30000, "Dearness Allowance": 3000, "House Rent Allowance": 3000, "Provident Fund": 1800, "Professional Tax": 208}


class TestPayrollEntry(PayrollFixture):
	def test_payroll_entry_slips_match_the_fixture(self):
		self.submit_structures()
		self.assign_demo_staff()
		entry = self.payroll_entry()
		slips = {s.employee: frappe.get_doc("Salary Slip", s.name) for s in frappe.get_all("Salary Slip", {"payroll_entry": entry.name}, ["name", "employee"])}

		self.assertEqual(set(slips), {self.aided, self.self_financing})
		self.assertEqual(self.amounts(slips[self.aided]), (AIDED_ROWS, (78400, 9028, 69372)))
		self.assertEqual(self.amounts(slips[self.self_financing]), (SELF_FINANCING_ROWS, (36000, 2008, 33992)))

	def test_increment_by_promotion_is_a_new_assignment(self):
		self.submit_structures()
		self.assign_demo_staff()
		promotion = frappe.get_doc(
			{
				"doctype": "Employee Promotion", "employee": self.aided, "promotion_date": "2026-08-01", "company": self.company,
				"current_ctc": 49000 * 12, "revised_ctc": 50200 * 12,
			}
		).insert(ignore_permissions=True)  # fmt: skip
		promotion.submit()
		api.assign_salary_structure(self.aided, promotion.promotion_date, base=41200, variable=9000)

		rows, totals = self.amounts(self.direct_slip(self.aided))
		self.assertEqual(rows["Basic"], 41200)
		self.assertEqual(rows["Dearness Allowance"], 25100)
		self.assertEqual(totals, (80320, 9244, 71076))

	def payroll_entry(self):
		company = frappe.get_cached_doc("Company", self.company)
		entry = frappe.new_doc("Payroll Entry")  # new_doc: the defaults the employee filter needs (not timesheet-based)
		entry.update(
			{
				"company": self.company, "posting_date": END, "payroll_frequency": "Monthly",
				"start_date": START, "end_date": END, "currency": company.default_currency, "exchange_rate": 1,
				"cost_center": company.cost_center, "payroll_payable_account": company.default_payroll_payable_account,
			}
		)  # fmt: skip
		frappe.db.set_value("Account", entry.payroll_payable_account, "account_type", "Payable")  # a college sets this once (guide step 1)
		entry.fill_employee_details()
		entry.insert(ignore_permissions=True)
		entry.submit()  # creates the draft slips (fewer than 30 employees: synchronously)
		return entry


class TestAssignmentHelper(PayrollFixture):
	def test_assignment_follows_the_employee_funding_mode(self):
		self.submit_structures()
		self.assign_demo_staff()
		for employee, mode in ((self.aided, AIDED), (self.self_financing, SELF_FINANCING)):
			ssa = frappe.get_doc("Salary Structure Assignment", {"employee": employee, "from_date": ASSIGNED_FROM})
			self.assertEqual((ssa.salary_structure, ssa.company, ssa.docstatus), (structure_name(mode, self.company), self.company, 1))

	def test_assignment_is_idempotent_per_employee_and_from_date(self):
		self.submit_structures()
		first = api.assign_salary_structure(self.aided, ASSIGNED_FROM, base=40000, variable=9000)
		again = api.assign_salary_structure(self.aided, ASSIGNED_FROM, base=45000)
		self.assertEqual(again, first)
		self.assertEqual(frappe.db.count("Salary Structure Assignment", {"employee": self.aided, "docstatus": ["<", 2]}), 1)
		self.assertEqual(frappe.db.get_value("Salary Structure Assignment", first, "base"), 40000)

	def test_only_the_employee_company_structure_is_used(self):
		seed_salary_structures(demo.ARTS)
		self.submit_structures(demo.ARTS)  # Engineering's stay drafts
		with self.assertRaises(frappe.ValidationError):
			api.assign_salary_structure(self.aided, ASSIGNED_FROM, base=40000)
		self.assertFalse(frappe.db.exists("Salary Structure Assignment", {"employee": self.aided}))

	def test_assignment_needs_a_funding_mode(self):
		self.submit_structures()
		frappe.db.set_value("Employee", self.aided, "oc_funding_mode", "")
		with self.assertRaises(frappe.ValidationError):
			api.assign_salary_structure(self.aided, ASSIGNED_FROM, base=40000)

	def test_two_active_structures_for_a_mode_are_refused(self):
		self.submit_structures()
		copy = frappe.copy_doc(frappe.get_doc("Salary Structure", structure_name(AIDED, self.company)))
		copy.name = "Aided Copy"
		copy.insert(ignore_permissions=True).submit()
		with self.assertRaises(frappe.ValidationError):
			api.assign_salary_structure(self.aided, ASSIGNED_FROM, base=40000)


class TestSeeding(PayrollFixture):
	def test_components_seeded_once_and_edits_kept(self):
		for component in ("Basic", "Dearness Allowance", "House Rent Allowance", "Academic Grade Pay"):
			self.assertTrue(frappe.db.exists("Salary Component", component))
		frappe.db.set_value("Salary Component", "Dearness Allowance", "description", "Edited by the college")
		seed_salary_components()
		self.assertEqual(frappe.db.get_value("Salary Component", "Dearness Allowance", "description"), "Edited by the college")

	def test_statutory_components_are_typed_for_the_hrms_reports(self):
		self.assertEqual(frappe.db.get_value("Salary Component", "Provident Fund", "component_type"), "Provident Fund")
		self.assertEqual(frappe.db.get_value("Salary Component", "Professional Tax", "component_type"), "Professional Tax")

	def test_structures_seeded_as_drafts_once_per_mode(self):
		seed_salary_structures(self.company)
		for mode in (AIDED, SELF_FINANCING):
			rows = frappe.get_all("Salary Structure", {"company": self.company, "oc_funding_mode": mode}, ["name", "docstatus"])
			self.assertEqual(rows, [{"name": structure_name(mode, self.company), "docstatus": 0}])

	def test_edited_structure_is_not_overwritten(self):
		name = structure_name(AIDED, self.company)
		doc = frappe.get_doc("Salary Structure", name)
		doc.earnings[0].formula = "base * 2"
		doc.save(ignore_permissions=True)
		seed_salary_structures(self.company)
		self.assertEqual(frappe.get_doc("Salary Structure", name).earnings[0].formula, "base * 2")
