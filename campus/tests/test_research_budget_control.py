"""P3-T15 (M08-04, M08-05) tests: expenditure tagging, budget control and re-appropriation.

Lines of a sanctioned project (Purchase Order, Purchase Invoice, Journal Entry, Expense Claim) carry `oc_budget_head`,
a head of the sanction whose account they post to. Revenue heads are controlled by the sanction's ERPNext Budgets;
capital heads by campus under a lock on the sanction, Stop or Warn per the scheme. A submitted Re-appropriation
Request moves an amount between heads for a fiscal year: the Budgets follow and the sanction logs it."""

import json
from unittest.mock import patch

import frappe
from erpnext.accounts.doctype.budget.budget import BudgetError
from erpnext.accounts.utils import get_fiscal_year
from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_invoice
from erpnext.controllers.accounts_controller import update_child_qty_rate
from frappe.utils import add_days, getdate, today

from campus.campus_finance.fee_heads import ensure_sac_code
from campus.research.budget_control import BUDGET_HEAD_FIELD, budget_head_fields, validate_lines
from campus.tests.research_fixtures import ABBR, COLLEGE, SanctionFixtures

SUPPLIER, ITEM = "RSA Lab Supplies Co", "RSA Lab Item"


class TestBudgetControl(SanctionFixtures):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("Supplier", SUPPLIER):
			group = frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")
			frappe.get_doc({"doctype": "Supplier", "supplier_name": SUPPLIER, "supplier_group": group}).insert()
		if not frappe.db.exists("Item", ITEM):
			group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
			frappe.get_doc(
				{"doctype": "Item", "item_code": ITEM, "item_group": group, "stock_uom": "Nos", "is_stock_item": 0, "gst_hsn_code": ensure_sac_code()}
			).insert()  # fmt: skip

	def setUp(self):
		super().setUp()
		self.equipment_account = f"Capital Equipment - {ABBR}"
		self.creditors = frappe.db.get_value("Account", {"company": COLLEGE, "account_type": "Payable", "is_group": 0})
		frappe.db.set_value("Company", COLLEGE, "default_payable_account", self.creditors)

	def submitted_sanction(self, **values):
		sanction = self.sanction(**values)
		sanction.submit()
		return sanction.reload()

	# vouchers
	def journal(self, sanction, account, amount, head=None, posting_date=None, **row):
		return frappe.get_doc(
			{
				"doctype": "Journal Entry", "company": COLLEGE, "posting_date": posting_date or today(),
				"accounts": [
					{"account": account, "debit_in_account_currency": amount, "cost_center": sanction.cost_center,
					 "project": sanction.project, BUDGET_HEAD_FIELD: head, **row},
					{"account": self.bank, "credit_in_account_currency": amount, "cost_center": sanction.cost_center},
				],
			}  # fmt: skip
		).insert()

	def item_row(self, sanction, account, amount, head):
		return {
			"item_code": ITEM, "qty": 1, "rate": amount, "expense_account": account, "cost_center": sanction.cost_center,
			"project": sanction.project, BUDGET_HEAD_FIELD: head, "schedule_date": today(),
		}  # fmt: skip

	def invoice(self, sanction, lines):
		return frappe.get_doc(
			{
				"doctype": "Purchase Invoice", "company": COLLEGE, "supplier": SUPPLIER, "posting_date": today(),
				"set_posting_time": 1, "credit_to": self.creditors,
				"items": [self.item_row(sanction, *line) for line in lines],
			}  # fmt: skip
		).insert()

	def order(self, sanction, lines):
		return frappe.get_doc(
			{
				"doctype": "Purchase Order", "company": COLLEGE, "supplier": SUPPLIER, "transaction_date": today(),
				"schedule_date": today(), "items": [self.item_row(sanction, *line) for line in lines],
			}  # fmt: skip
		).insert()

	def reappropriation(self, sanction, from_head, to_head, amount, fiscal_year=None, **values):
		return frappe.get_doc(
			{
				"doctype": "Re-appropriation Request", "sanction": sanction.name, "fiscal_year": fiscal_year or self.year1.name,
				"from_head": from_head, "to_head": to_head, "amount": amount, "agency_letter_no": "DST/RA/1",
				"agency_letter_date": today(), "agency_approval_letter": "/files/ra-letter.pdf", **values,
			}  # fmt: skip
		).insert()

	def head_amounts(self, sanction):
		rows = frappe.get_all("Sanction Head", {"parent": sanction.name, "parenttype": "Sanction"}, ["budget_head", "fiscal_year", "amount"])
		return {(row.budget_head, row.fiscal_year): row.amount for row in rows}

	def budget(self, sanction, account):
		name = frappe.db.get_value("Budget", {"cost_center": sanction.cost_center, "account": account, "docstatus": 1})
		return frappe.get_doc("Budget", name) if name else None

	def distribution(self, budget):
		return {getdate(row.start_date): row.amount for row in budget.budget_distribution}

	def warnings(self):
		return " ".join(str(m) for m in frappe.message_log)

	# fields
	def test_budget_head_field_on_the_four_line_doctypes(self):
		for doctype in budget_head_fields():
			field = frappe.get_meta(doctype).get_field(BUDGET_HEAD_FIELD)
			self.assertEqual((field.fieldtype, field.options), ("Link", "Grant Budget Head"), doctype)
		self.assertEqual(
			set(budget_head_fields()), {"Purchase Order Item", "Purchase Invoice Item", "Journal Entry Account", "Expense Claim Detail"}
		)

	# tagging and head -> account validation
	def test_head_required_on_spending_lines_of_a_sanctioned_project(self):
		sanction = self.submitted_sanction()
		with self.assertRaisesRegex(frappe.ValidationError, "Budget Head"):
			self.journal(sanction, self.consumables_account, 100)
		with self.assertRaisesRegex(frappe.ValidationError, "Budget Head"):
			self.invoice(sanction, [(self.consumables_account, 100, None)])
		self.journal(sanction, self.consumables_account, 100, self.consumables)  # tagged: fine

	def test_pi_line_of_the_equipment_head_posting_to_consumables_is_rejected(self):
		sanction = self.submitted_sanction()
		with self.assertRaisesRegex(frappe.ValidationError, "RSA Equipment"):
			self.invoice(sanction, [(self.consumables_account, 1000, self.equipment)])
		with self.assertRaisesRegex(frappe.ValidationError, "RSA Consumables"):
			self.journal(sanction, self.equipment_account, 1000, self.consumables)

	def test_head_must_be_on_the_sanction(self):
		sanction = self.submitted_sanction(
			heads=[(self.consumables, self.year1.name, 1000)], instalments=[("First", 1000)]
		)  # fmt: skip
		with self.assertRaisesRegex(frappe.ValidationError, "not a head of"):
			self.journal(sanction, self.travel_account, 100, self.travel)

	def test_head_only_on_lines_of_a_sanction(self):
		sanction = self.submitted_sanction()
		other_cc = frappe.db.get_value("Cost Center", {"company": COLLEGE, "is_group": 0, "name": ["!=", sanction.cost_center]})
		with self.assertRaisesRegex(frappe.ValidationError, "only on lines of a sanctioned project"):
			self.journal(sanction, self.consumables_account, 100, self.consumables, cost_center=other_cc, project=None)

	def test_line_on_the_sanction_cost_centre_takes_its_project_and_must_not_mix_sanctions(self):
		sanction = self.submitted_sanction()
		entry = self.journal(sanction, self.consumables_account, 100, self.consumables, project=None)
		self.assertEqual(entry.accounts[0].project, sanction.project)
		other_cc = frappe.db.get_value("Cost Center", {"company": COLLEGE, "is_group": 0, "name": ["!=", sanction.cost_center]})
		with self.assertRaisesRegex(frappe.ValidationError, "cost centre"):
			self.journal(sanction, self.consumables_account, 100, self.consumables, cost_center=other_cc)

	def test_grant_receipt_rows_need_no_head(self):
		sanction = self.submitted_sanction()
		receipt = self.receipt(sanction)
		receipt.submit()
		self.assertEqual(frappe.db.get_value("Journal Entry", receipt.reload().journal_entry, "docstatus"), 1)

	def test_spend_outside_the_sanction_period_is_refused(self):
		sanction = self.submitted_sanction()
		with self.assertRaisesRegex(frappe.ValidationError, "outside the sanction period"):
			self.journal(sanction, self.consumables_account, 100, self.consumables, posting_date=add_days(self.year1.start, -1))

	def test_revenue_spend_in_a_year_without_a_budget_is_refused(self):
		sanction = self.submitted_sanction()
		budget = self.budget(sanction, self.travel_account)
		budget.cancel()  # e.g. cancelled by hand: ERPNext would then let any amount through
		with self.assertRaisesRegex(frappe.ValidationError, "no budget"):
			self.journal(sanction, self.travel_account, 10, self.travel)

	def test_head_defaults_from_the_item_group(self):
		sanction = self.submitted_sanction()
		group = frappe.db.get_value("Item", ITEM, "item_group")
		head = frappe.get_doc("Grant Budget Head", self.consumables)
		head.append("item_groups", {"item_group": group})
		head.save()
		invoice = self.invoice(sanction, [(self.consumables_account, 100, None)])
		self.assertEqual(invoice.items[0].get(BUDGET_HEAD_FIELD), self.consumables)
		with self.assertRaisesRegex(frappe.ValidationError, "item group"):
			self.invoice(sanction, [(self.travel_account, 100, self.travel)])

	def test_expense_claim_lines_are_tagged_and_checked(self):
		sanction = self.submitted_sanction()
		claim = frappe.get_doc(
			{
				"doctype": "Expense Claim", "company": COLLEGE, "posting_date": today(), "project": sanction.project,
				"expenses": [{"default_account": self.travel_account, "cost_center": sanction.cost_center, "amount": 100, "sanctioned_amount": 100}],
			}  # fmt: skip
		)
		with self.assertRaisesRegex(frappe.ValidationError, "Budget Head"):
			validate_lines(claim)
		claim.expenses[0].set(BUDGET_HEAD_FIELD, self.consumables)
		with self.assertRaisesRegex(frappe.ValidationError, "RSA Consumables"):
			validate_lines(claim)
		claim.expenses[0].set(BUDGET_HEAD_FIELD, self.travel)
		validate_lines(claim)
		self.assertEqual(claim.expenses[0].project, sanction.project)

	# acceptance 2: revenue heads through ERPNext Budget, capital heads by campus
	def test_revenue_spend_above_the_head_budget_is_stopped(self):
		sanction = self.submitted_sanction()
		self.invoice(sanction, [(self.travel_account, 25000, self.travel)]).submit()
		with self.assertRaises(BudgetError):  # travel: 30000 sanctioned in year 1
			self.invoice(sanction, [(self.travel_account, 6000, self.travel)]).submit()

	def test_revenue_spend_above_the_head_budget_warns_under_a_warn_scheme(self):
		scheme = self.make_scheme("RSA Warn Scheme", [self.consumables, self.equipment], budget_action="Warn")
		sanction = self.submitted_sanction(
			scheme=scheme, heads=[(self.consumables, self.year1.name, 1000), (self.equipment, self.year1.name, 2000)],
			instalments=[("First", 3000)],
		)  # fmt: skip
		frappe.clear_messages()
		self.journal(sanction, self.consumables_account, 1500, self.consumables).submit()
		self.assertIn("Budget Exceeded", self.warnings())
		frappe.clear_messages()
		self.journal(sanction, self.equipment_account, 2500, self.equipment).submit()
		self.assertIn("RSA Equipment", self.warnings())

	def test_capital_spend_above_the_head_is_stopped_under_a_lock(self):
		sanction = self.submitted_sanction()
		self.journal(sanction, self.equipment_account, 400000, self.equipment).submit()
		entry = self.journal(sanction, self.equipment_account, 150000, self.equipment)
		real, locked = frappe.db.get_value, []

		def spy(doctype, *args, **kwargs):
			if doctype == "Sanction" and kwargs.get("for_update"):
				locked.append(args[0])
			return real(doctype, *args, **kwargs)

		with patch.object(frappe.db, "get_value", side_effect=spy):
			with self.assertRaisesRegex(frappe.ValidationError, "RSA Equipment"):
				entry.submit()
		self.assertIn(sanction.name, locked)
		self.journal(sanction, self.equipment_account, 100000, self.equipment).submit()  # exactly up to 500000

	def test_capital_order_and_its_invoice_count_once(self):
		sanction = self.submitted_sanction()
		order = self.order(sanction, [(self.equipment_account, 400000, self.equipment)])
		order.submit()
		with self.assertRaisesRegex(frappe.ValidationError, "RSA Equipment"):
			self.order(sanction, [(self.equipment_account, 150000, self.equipment)]).submit()
		invoice = make_purchase_invoice(order.name)
		invoice.posting_date, invoice.set_posting_time, invoice.credit_to = today(), 1, self.creditors
		invoice.insert()
		self.assertEqual(invoice.items[0].get(BUDGET_HEAD_FIELD), self.equipment)
		invoice.submit()  # billing the order does not count it twice
		with self.assertRaisesRegex(frappe.ValidationError, "RSA Equipment"):
			self.journal(sanction, self.equipment_account, 150000, self.equipment).submit()
		self.journal(sanction, self.equipment_account, 100000, self.equipment).submit()

	def test_cancelling_a_capital_credit_is_checked(self):
		sanction = self.submitted_sanction()
		self.journal(sanction, self.equipment_account, 500000, self.equipment).submit()
		credit = self.journal(sanction, self.equipment_account, -100000, self.equipment)  # e.g. a supplier credit
		credit.submit()
		self.journal(sanction, self.equipment_account, 100000, self.equipment).submit()  # the head is full again
		with self.assertRaisesRegex(frappe.ValidationError, "RSA Equipment"):
			credit.reload().cancel()  # would bring spending back to 600000
		self.assertEqual(frappe.db.get_value("Journal Entry", credit.name, "docstatus"), 1)

	def test_cancelling_a_capital_debit_note_is_checked(self):
		from erpnext.controllers.sales_and_purchase_return import make_return_doc

		sanction = self.submitted_sanction()
		invoice = self.invoice(sanction, [(self.equipment_account, 500000, self.equipment)])
		invoice.submit()
		debit_note = make_return_doc("Purchase Invoice", invoice.name)
		debit_note.items[0].qty, debit_note.items[0].rate = -1, 500000
		debit_note.insert()
		debit_note.submit()
		self.journal(sanction, self.equipment_account, 500000, self.equipment).submit()
		with self.assertRaisesRegex(frappe.ValidationError, "RSA Equipment"):
			debit_note.reload().cancel()

	def update_order_items(self, order, rate, head=None):
		row = order.items[0]
		items = [{"docname": row.name, "item_code": row.item_code, "qty": 1, "rate": rate, "uom": row.uom,
			"conversion_factor": row.conversion_factor, "schedule_date": str(row.schedule_date)}]  # fmt: skip
		update_child_qty_rate("Purchase Order", json.dumps(items), order.name)

	def test_updating_order_items_is_checked_against_the_capital_limit(self):
		sanction = self.submitted_sanction()
		order = self.order(sanction, [(self.equipment_account, 400000, self.equipment)])
		order.submit()
		self.update_order_items(order, 450000)  # the order itself is counted once
		self.assertEqual(frappe.db.get_value("Purchase Order Item", order.items[0].name, "amount"), 450000)
		frappe.db.savepoint("update_items")
		with self.assertRaisesRegex(frappe.ValidationError, "RSA Equipment"):
			self.update_order_items(order, 600000)
		frappe.db.rollback(save_point="update_items")

	def test_updating_a_billed_order_counts_the_billed_part_once(self):
		sanction = self.submitted_sanction()
		order = self.order(sanction, [(self.equipment_account, 400000, self.equipment)])
		order.submit()
		invoice = make_purchase_invoice(order.name)
		invoice.posting_date, invoice.set_posting_time, invoice.credit_to = today(), 1, self.creditors
		invoice.insert()
		invoice.submit()
		self.update_order_items(order.reload(), 450000)  # 400000 invoiced + 50000 unbilled, within 500000
		self.assertEqual(frappe.db.get_value("Purchase Order Item", order.items[0].name, "amount"), 450000)
		frappe.db.savepoint("billed_update")
		with self.assertRaisesRegex(frappe.ValidationError, "RSA Equipment"):
			self.update_order_items(order.reload(), 550000)
		frappe.db.rollback(save_point="billed_update")

	def test_rows_added_by_update_items_to_a_sanction_order_are_refused(self):
		sanction = self.submitted_sanction()
		order = self.order(sanction, [(self.consumables_account, 1000, self.consumables)])
		order.submit()
		row = order.items[0]
		items = [
			{"docname": row.name, "item_code": row.item_code, "qty": 1, "rate": 1000, "uom": row.uom,
			 "conversion_factor": row.conversion_factor, "schedule_date": str(row.schedule_date)},
			{"item_code": ITEM, "qty": 1, "rate": 500, "uom": row.uom, "conversion_factor": 1, "schedule_date": str(row.schedule_date)},
		]  # fmt: skip
		with self.assertRaisesRegex(frappe.ValidationError, "new Purchase Order"):
			update_child_qty_rate("Purchase Order", json.dumps(items), order.name)

	def test_head_rules_hold_on_updated_order_items(self):
		sanction = self.submitted_sanction()
		order = self.order(sanction, [(self.consumables_account, 1000, self.consumables)])
		order.submit()
		frappe.db.set_value("Purchase Order Item", order.items[0].name, BUDGET_HEAD_FIELD, self.equipment)  # a stale tag
		with self.assertRaisesRegex(frappe.ValidationError, "RSA Equipment"):
			self.update_order_items(order.reload(), 900)

	def test_capital_spend_is_limited_to_the_amount_sanctioned_to_date(self):
		sanction = self.submitted_sanction(
			heads=[(self.equipment, self.year1.name, 300000), (self.equipment, self.year2.name, 200000)],
			instalments=[("First", 500000)],
		)  # fmt: skip
		with self.assertRaisesRegex(frappe.ValidationError, self.year1.name):
			self.journal(sanction, self.equipment_account, 350000, self.equipment).submit()
		self.journal(sanction, self.equipment_account, 300000, self.equipment).submit()

	def test_extension_carries_the_budgets_into_the_new_year(self):
		sanction = self.submitted_sanction()
		later = add_days(self.year2.end, 30)
		sanction.extend_sanction(add_days(self.year2.end, 90), "DST/EXT/9", today())
		budget = self.budget(sanction, self.consumables_account)
		self.assertEqual(budget.to_fiscal_year, get_fiscal_year(later, company=COLLEGE)[0])
		self.assertEqual(budget.budget_amount, 300000)
		self.journal(sanction, self.consumables_account, 1000, self.consumables, posting_date=later).submit()

	# acceptance 3: re-appropriation
	def test_reappropriation_moves_the_limits_and_logs_on_the_sanction(self):
		sanction = self.submitted_sanction()
		self.journal(sanction, self.travel_account, 30000, self.travel).submit()  # travel year 1 used up
		request = self.reappropriation(sanction, self.consumables, self.travel, 20000)
		request.submit()

		amounts = self.head_amounts(sanction)
		self.assertEqual(amounts[(self.consumables, self.year1.name)], 180000)
		self.assertEqual(amounts[(self.travel, self.year1.name)], 50000)
		self.assertEqual(frappe.db.get_value("Sanction", sanction.name, "total_sanctioned"), 850000)
		travel = self.budget(sanction, self.travel_account)
		self.assertEqual((travel.budget_amount, self.distribution(travel)[getdate(self.year1.start)]), (70000, 50000))
		self.assertEqual(self.budget(sanction, self.consumables_account).budget_amount, 280000)
		comments = frappe.get_all("Comment", {"reference_doctype": "Sanction", "reference_name": sanction.name}, pluck="content")
		self.assertTrue([c for c in comments if request.name in c and "DST/RA/1" in c])

		self.journal(sanction, self.travel_account, 20000, self.travel).submit()  # the new travel limit applies
		with self.assertRaises(BudgetError):
			self.journal(sanction, self.travel_account, 1, self.travel).submit()
		self.journal(sanction, self.consumables_account, 180000, self.consumables).submit()
		with self.assertRaises(BudgetError):  # and the reduced consumables limit
			self.journal(sanction, self.consumables_account, 1, self.consumables).submit()

	def test_reappropriation_into_a_capital_head(self):
		sanction = self.submitted_sanction()
		self.reappropriation(sanction, self.consumables, self.equipment, 100000).submit()
		self.journal(sanction, self.equipment_account, 600000, self.equipment).submit()
		with self.assertRaisesRegex(frappe.ValidationError, "RSA Equipment"):
			self.journal(sanction, self.equipment_account, 1, self.equipment).submit()

	def test_moving_a_whole_revenue_head_leaves_it_unbudgeted(self):
		sanction = self.submitted_sanction(
			heads=[(self.consumables, self.year1.name, 1000), (self.travel, self.year1.name, 500)], instalments=[("First", 1500)]
		)  # fmt: skip
		self.reappropriation(sanction, self.travel, self.consumables, 500).submit()
		self.assertIsNone(self.budget(sanction, self.travel_account))
		self.assertNotIn((self.travel, self.year1.name), self.head_amounts(sanction))
		with self.assertRaisesRegex(frappe.ValidationError, "not a head of"):
			self.journal(sanction, self.travel_account, 10, self.travel)
		self.assertEqual(self.budget(sanction, self.consumables_account).budget_amount, 1500)

	def test_reappropriation_cannot_move_money_already_spent(self):
		sanction = self.submitted_sanction()
		self.journal(sanction, self.consumables_account, 190000, self.consumables).submit()
		with self.assertRaisesRegex(frappe.ValidationError, "already"):
			self.reappropriation(sanction, self.consumables, self.travel, 20000).submit()
		self.journal(sanction, self.equipment_account, 450000, self.equipment).submit()
		with self.assertRaisesRegex(frappe.ValidationError, "already"):
			self.reappropriation(sanction, self.equipment, self.travel, 60000).submit()

	def test_reappropriation_validation(self):
		sanction = self.submitted_sanction()
		with self.assertRaisesRegex(frappe.ValidationError, "same"):
			self.reappropriation(sanction, self.travel, self.travel, 100)
		with self.assertRaisesRegex(frappe.ValidationError, "30,000|30000"):
			self.reappropriation(sanction, self.travel, self.consumables, 30001)
		with self.assertRaisesRegex(frappe.ValidationError, "amount"):
			self.reappropriation(sanction, self.travel, self.consumables, 0)
		with self.assertRaises(frappe.MandatoryError):
			self.reappropriation(sanction, self.travel, self.consumables, 100, agency_approval_letter=None)
		with self.assertRaisesRegex(frappe.ValidationError, "submitted"):
			self.reappropriation(self.sanction(), self.travel, self.consumables, 100)

	def test_reappropriation_reads_budgets_and_heads_with_locking_reads(self):
		sanction = self.submitted_sanction()
		request = self.reappropriation(sanction, self.consumables, self.travel, 20000)
		real, queries = frappe.db.sql, []

		def spy(query, *args, **kwargs):
			queries.append(str(query))
			return real(query, *args, **kwargs)

		with patch.object(frappe.db, "sql", side_effect=spy):
			request.submit()
		def locking(q):
			return "for update" in q.lower()

		start = next(i for i, q in enumerate(queries) if "from `tabsanction`" in q.lower() and locking(q))
		after_lock = queries[start:]
		# campus's own Budget reads (ERPNext's Budget controller has plain reads of its own, e.g. its duplicate check)
		budget_reads = [q for q in after_lock if "from `tabbudget`" in q.lower() and ("`cost_center`" in q or "`name` = %s" in q)]
		self.assertTrue(budget_reads)
		self.assertEqual([q for q in budget_reads if not locking(q)], [], "Budget reads after the sanction lock are locking")
		head_reads = [q for q in after_lock if q.lstrip().lower().startswith("select") and "`tabsanction head`" in q.lower()]
		self.assertTrue(head_reads)
		self.assertEqual([q for q in head_reads if not locking(q)], [], "Sanction Head reads after the lock are locking")

	def test_cancelling_a_reappropriation_restores_the_limits(self):
		sanction = self.submitted_sanction()
		request = self.reappropriation(sanction, self.consumables, self.travel, 20000)
		request.submit()
		request.cancel()
		amounts = self.head_amounts(sanction)
		self.assertEqual((amounts[(self.consumables, self.year1.name)], amounts[(self.travel, self.year1.name)]), (200000, 30000))
		self.assertEqual(self.budget(sanction, self.travel_account).budget_amount, 50000)
		self.assertEqual(self.budget(sanction, self.consumables_account).budget_amount, 300000)
