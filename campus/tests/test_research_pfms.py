"""P3-T18 (M08-07) tests: PFMS EAT export.

A PFMS Export Batch (sanction, export type, period) collects the payments of the sanction: Payment Entries to
suppliers against its Purchase Invoices (expenditure), against its Purchase Orders or unallocated on its project
(advance), payments to a supplier that is a registered PFMS agency (transfer), and Purchase Invoices paid on the
invoice itself (expenditure). Payments to vendors without a PFMS vendor code or bank details are excluded and reported.
A row exported once is never exported again unless PFMS reported it failed. The file adapter writes the EAT file from
a PFMS Export Layout record (the column mapping), neutralising spreadsheet formulas, and reads the status file back."""

import csv
import io
from unittest.mock import patch

import frappe
from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
from frappe.utils import add_days, today

from campus.campus_finance.fee_heads import ensure_sac_code
from campus.research import pfms_adapter
from campus.research.budget_control import BUDGET_HEAD_FIELD
from campus.research.pfms import DEFAULT_LAYOUTS, PFMS_AGENCY_FIELD, VENDOR_CODE_FIELD, export_key
from campus.research.pfms_adapter import FileAdapter, adapter_for, neutralise
from campus.tests.factories import make_user
from campus.tests.research_fixtures import ABBR, COLLEGE, OTHER, SanctionFixtures

ITEM, BANK = "PFMS Test Item", "PFMS Test Bank"
OTHER_COLLEGE_USER = "pfms-other-accounts@example.com"
BATCH = "PFMS Export Batch"


class TestPfmsExport(SanctionFixtures):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("Item", ITEM):
			group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
			frappe.get_doc(
				{"doctype": "Item", "item_code": ITEM, "item_group": group, "stock_uom": "Nos", "is_stock_item": 0, "gst_hsn_code": ensure_sac_code()}
			).insert()  # fmt: skip
		if not frappe.db.exists("Bank", BANK):
			frappe.get_doc({"doctype": "Bank", "bank_name": BANK}).insert()
		if not frappe.db.exists("Party Type", "Supplier"):  # the bare test site has only Student
			frappe.get_doc({"doctype": "Party Type", "party_type": "Supplier", "account_type": "Payable"}).insert()
		make_user(OTHER_COLLEGE_USER, [OTHER])
		frappe.get_doc("User", OTHER_COLLEGE_USER).add_roles("Accounts Manager")

	def setUp(self):
		super().setUp()
		self.creditors = frappe.db.get_value("Account", {"company": COLLEGE, "account_type": "Payable", "is_group": 0})
		frappe.db.set_value("Company", COLLEGE, "default_payable_account", self.creditors)
		frappe.db.set_value("Research Settings", COLLEGE, "pfms_unique_agency_code", "RSAT0001")
		frappe.db.set_value("Funding Agency", self.agency, "pfms_agency_code", "DST01")
		self.sanction_doc = self.submitted_sanction()
		self.vendor = self.supplier("PFMS Good Vendor", code="V0001")
		self.period = (add_days(today(), -10), today())

	def submitted_sanction(self, **values):
		sanction = self.sanction(**values)
		sanction.submit()
		return sanction.reload()

	# masters
	def supplier(self, name, code=None, bank=True, ifsc="SBIN0000001", agency=0):
		supplier = frappe.get_doc(
			{
				"doctype": "Supplier", "supplier_name": f"{name} {frappe.generate_hash(length=4)}",
				"supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}), VENDOR_CODE_FIELD: code,
				PFMS_AGENCY_FIELD: agency,
			}  # fmt: skip
		).insert()
		if bank:
			frappe.get_doc(
				{
					"doctype": "Bank Account", "account_name": supplier.supplier_name, "bank": BANK, "party_type": "Supplier",
					"party": supplier.name, "is_default": 1, "bank_account_no": f"0011{frappe.generate_hash(length=6)}",
					"branch_code": ifsc,
				}  # fmt: skip
			).insert()
		return supplier.name

	# vouchers
	def invoice(self, supplier, amount, sanction=None, posting_date=None, **values):
		sanction = sanction or self.sanction_doc
		invoice = frappe.get_doc(
			{
				"doctype": "Purchase Invoice", "company": COLLEGE, "supplier": supplier, "posting_date": posting_date or today(),
				"set_posting_time": 1, "credit_to": self.creditors,
				"items": [
					{"item_code": ITEM, "qty": 1, "rate": amount, "expense_account": self.consumables_account,
					 "cost_center": sanction.cost_center, "project": sanction.project, BUDGET_HEAD_FIELD: self.consumables}
				],
				**values,
			}  # fmt: skip
		).insert()
		invoice.submit()
		return invoice

	def pay(self, invoice, amount=None, posting_date=None):
		payment = get_payment_entry("Purchase Invoice", invoice.name, party_amount=amount, bank_account=self.bank)
		payment.update({"reference_no": "UTR-PFMS", "reference_date": today(), "posting_date": posting_date or today()})
		if amount:
			payment.paid_amount = payment.received_amount = amount
			payment.references[0].allocated_amount = amount
		payment.insert()
		payment.submit()
		return payment

	def advance(self, supplier, amount, posting_date=None, **values):
		payment = frappe.get_doc(
			{
				"doctype": "Payment Entry", "payment_type": "Pay", "company": COLLEGE, "posting_date": posting_date or today(),
				"party_type": "Supplier", "party": supplier, "paid_from": self.bank, "paid_to": self.creditors,
				"paid_amount": amount, "received_amount": amount, "reference_no": "UTR-ADV", "reference_date": today(),
				"project": self.sanction_doc.project, "cost_center": self.sanction_doc.cost_center, **values,
			}  # fmt: skip
		).insert()
		payment.submit()
		return payment

	def order(self, supplier, amount):
		sanction = self.sanction_doc
		order = frappe.get_doc(
			{
				"doctype": "Purchase Order", "company": COLLEGE, "supplier": supplier, "transaction_date": today(), "schedule_date": today(),
				"items": [
					{"item_code": ITEM, "qty": 1, "rate": amount, "expense_account": self.consumables_account, "schedule_date": today(),
					 "cost_center": sanction.cost_center, "project": sanction.project, BUDGET_HEAD_FIELD: self.consumables}
				],
			}  # fmt: skip
		).insert()
		order.submit()
		return order

	def amend(self, payment):
		amended = frappe.copy_doc(payment)
		amended.amended_from, amended.docstatus = payment.name, 0
		amended.insert()
		amended.submit()
		return amended

	def paid_invoice(self, supplier, amount):
		return self.invoice(supplier, amount, is_paid=1, cash_bank_account=self.bank, paid_amount=amount, mode_of_payment=None)

	def batch(self, export_type="Expenditure", period=None, **values):
		from_date, to_date = period or self.period
		return frappe.get_doc(
			{"doctype": BATCH, "sanction": self.sanction_doc.name, "export_type": export_type, "from_date": from_date, "to_date": to_date, **values}
		).insert()  # fmt: skip

	def exported(self, export_type="Expenditure", **values):
		batch = self.batch(export_type, **values)
		batch.submit()
		return batch.reload()

	def file_rows(self, batch):
		content = frappe.get_doc("File", {"file_url": batch.export_file}).get_content()
		return list(csv.reader(io.StringIO(content.decode() if isinstance(content, bytes) else content)))

	def status_file(self, batch, lines, header=("Unique Reference", "Status", "PFMS Reference", "Remarks")):
		buffer = io.StringIO()
		writer = csv.writer(buffer)
		writer.writerow(header)
		writer.writerows(lines)
		return frappe.get_doc(
			{"doctype": "File", "file_name": f"status-{frappe.generate_hash(length=6)}.csv", "content": buffer.getvalue(), "is_private": 1}
		).insert().file_url  # fmt: skip

	def vouchers(self, batch):
		return sorted((row.voucher_type, row.voucher_no) for row in batch.rows)

	# row selection
	def test_expenditure_rows_are_supplier_payments_of_the_sanctions_invoices_in_the_period(self):
		paid = self.pay(self.invoice(self.vendor, 1000))
		cash = self.paid_invoice(self.vendor, 400)
		self.pay(self.invoice(self.vendor, 700), posting_date=add_days(today(), -30))  # before the period
		advance = self.advance(self.vendor, 300)
		other = self.submitted_sanction()
		self.pay(self.invoice(self.vendor, 900, sanction=other))  # another sanction's invoice
		batch = self.batch()
		self.assertEqual(self.vouchers(batch), sorted([("Payment Entry", paid.name), ("Purchase Invoice", cash.name)]))
		row = next(r for r in batch.rows if r.voucher_no == paid.name)
		self.assertEqual((row.reference_doctype, row.amount, row.supplier, row.pfms_vendor_code, row.ifsc), ("Purchase Invoice", 1000, self.vendor, "V0001", "SBIN0000001"))
		self.assertEqual(row.budget_head, self.consumables)
		self.assertEqual((batch.row_count, batch.total_amount, batch.status), (2, 1400, "Draft"))
		self.assertEqual(self.vouchers(self.batch("Advance")), [("Payment Entry", advance.name)])

	def test_a_part_payment_exports_the_allocated_amount(self):
		invoice = self.invoice(self.vendor, 1000)
		self.pay(invoice, amount=600)
		self.assertEqual([row.amount for row in self.batch().rows], [600])

	def test_payments_to_a_registered_agency_are_transfers(self):
		agency = self.supplier("PFMS Implementing Agency", code="A0001", agency=1)
		transfer = self.advance(agency, 5000)
		self.pay(self.invoice(agency, 800))
		self.assertEqual(len(self.batch("Transfer").rows), 2)
		self.assertIn(("Payment Entry", transfer.name), self.vouchers(self.batch("Transfer")))
		self.assertFalse(self.batch("Advance").rows)
		self.assertFalse(self.batch("Expenditure").rows)

	def test_an_advance_against_a_purchase_order_is_an_advance_row(self):
		order = self.order(self.vendor, 2000)
		payment = get_payment_entry("Purchase Order", order.name, party_amount=500, bank_account=self.bank)
		payment.update({"reference_no": "UTR-PO", "reference_date": today()})
		payment.paid_amount = payment.received_amount = 500
		payment.references[0].allocated_amount = 500
		payment.insert()
		payment.submit()
		batch = self.batch("Advance")
		self.assertEqual([(r.voucher_no, r.reference_doctype, r.reference_name, r.amount) for r in batch.rows], [(payment.name, "Purchase Order", order.name, 500)])
		self.assertFalse(self.batch().rows)

	def test_an_unallocated_payment_naming_two_sanctions_is_excluded(self):
		other = self.submitted_sanction()
		payment = self.advance(self.vendor, 300, project=other.project)  # the other sanction's project, this one's cost centre
		batch = self.batch("Advance")
		self.assertFalse(batch.rows)
		self.assertIn(other.name, next(row.reason for row in batch.exclusions if row.voucher_no == payment.name))
		self.assertFalse(frappe.get_doc({"doctype": BATCH, "sanction": other.name, "export_type": "Advance", "from_date": self.period[0], "to_date": self.period[1]}).insert().rows)

	# acceptance 1: vendor check
	def test_vendors_without_a_pfms_code_or_bank_details_are_excluded_and_reported(self):
		good = self.pay(self.invoice(self.vendor, 1000))
		no_code = self.pay(self.invoice(self.supplier("PFMS No Code"), 200))
		no_bank = self.pay(self.invoice(self.supplier("PFMS No Bank", code="V0002", bank=False), 300))
		no_ifsc = self.pay(self.invoice(self.supplier("PFMS No IFSC", code="V0003", ifsc=None), 400))
		batch = self.exported()
		self.assertEqual(self.vouchers(batch), [("Payment Entry", good.name)])
		reasons = {row.voucher_no: row.reason for row in batch.exclusions}
		self.assertEqual(set(reasons), {no_code.name, no_bank.name, no_ifsc.name})
		self.assertIn("PFMS vendor code", reasons[no_code.name])
		self.assertIn("bank", reasons[no_bank.name])
		self.assertIn("bank", reasons[no_ifsc.name])
		self.assertEqual(batch.excluded_count, 3)
		lines = self.file_rows(batch)
		self.assertEqual(len(lines), 2)  # header + the good payment only
		self.assertIn(good.name, lines[1])

	def test_an_excluded_payment_is_exported_once_the_vendor_is_fixed(self):
		vendor = self.supplier("PFMS Later Code")
		payment = self.pay(self.invoice(vendor, 200))
		self.assertFalse(self.batch().rows)
		frappe.db.set_value("Supplier", vendor, VENDOR_CODE_FIELD, "V0009")
		self.assertEqual(self.vouchers(self.batch()), [("Payment Entry", payment.name)])

	# acceptance 2: idempotency
	def test_reexport_includes_only_rows_not_exported_successfully(self):
		first = self.pay(self.invoice(self.vendor, 1000))
		second = self.pay(self.invoice(self.vendor, 500))
		batch = self.exported()
		self.assertEqual(batch.row_count, 2)
		again = self.batch()
		self.assertFalse(again.rows)
		self.assertEqual(again.already_exported_count, 2)
		with self.assertRaises(frappe.ValidationError):
			again.submit()
		third = self.pay(self.invoice(self.vendor, 250))
		self.assertEqual(self.vouchers(self.batch()), [("Payment Entry", third.name)])
		ref = {row.voucher_no: row.row_reference for row in batch.rows}
		batch.import_status(self.status_file(batch, [(ref[first.name], "Success", "PF1", ""), (ref[second.name], "Rejected", "", "Bad IFSC")]))
		self.assertEqual(self.vouchers(self.batch()), sorted([("Payment Entry", second.name), ("Payment Entry", third.name)]))

	def test_an_advance_reconciled_to_an_invoice_is_not_exported_again(self):
		payment = self.advance(self.vendor, 300)
		self.assertEqual(self.exported("Advance").row_count, 1)
		self.invoice(
			self.vendor, 300,
			advances=[{"reference_type": "Payment Entry", "reference_name": payment.name, "advance_amount": 300, "allocated_amount": 300}],
		)  # fmt: skip
		self.assertTrue(frappe.get_all("Payment Entry Reference", {"parent": payment.name, "reference_doctype": "Purchase Invoice"}))
		batch = self.batch()
		self.assertFalse(batch.rows)  # the same money, now allocated to the invoice
		self.assertEqual(batch.already_exported_count, 1)

	def test_an_amended_payment_is_not_exported_again(self):
		payment = self.pay(self.invoice(self.vendor, 1000))
		self.exported()
		with patch("campus.research.pfms.refuse_exported_cancel"):
			payment.cancel()
		amended = self.amend(payment)
		batch = self.batch()
		self.assertFalse(batch.rows)
		self.assertEqual(batch.already_exported_count, 1)
		self.assertTrue(amended.name.startswith(payment.name))

	def test_an_exported_payment_cannot_be_cancelled_until_pfms_failed_it(self):
		payment = self.pay(self.invoice(self.vendor, 1000))
		cash = self.paid_invoice(self.vendor, 400)
		batch = self.exported()
		for voucher in (payment, cash):
			with self.assertRaisesRegex(frappe.ValidationError, batch.name):
				frappe.get_doc(voucher.doctype, voucher.name).cancel()
		ref = {row.voucher_no: row.row_reference for row in batch.rows}
		batch.import_status(self.status_file(batch, [(ref[payment.name], "Failed", "", "Bad account")]))
		frappe.get_doc("Payment Entry", payment.name).cancel()
		amended = self.amend(payment)
		self.assertEqual(self.vouchers(self.batch()), [("Payment Entry", amended.name)])  # re-exported once fixed

	def test_two_drafts_of_a_period_export_a_payment_once(self):
		self.pay(self.invoice(self.vendor, 1000))
		first, second = self.batch(), self.batch()
		first.submit()
		with self.assertRaises(frappe.ValidationError):
			second.submit()  # re-selected under the sanction lock: nothing left
		self.assertEqual(second.reload().docstatus, 0)

	def test_the_export_key_is_unique_in_the_database(self):
		payment = self.pay(self.invoice(self.vendor, 1000))
		batch = self.exported()
		row = batch.rows[0]
		self.assertEqual(row.export_key, export_key("Payment Entry", payment.name, "Purchase Invoice", row.reference_name))
		self.pay(self.invoice(self.vendor, 500))
		other = self.exported().rows[0]
		with self.assertRaises(Exception) as caught:
			frappe.db.set_value("PFMS Export Batch Row", other.name, "export_key", row.export_key)
		self.assertTrue(frappe.db.is_unique_key_violation(caught.exception))

	def test_selection_reads_exported_keys_with_a_locking_read_under_the_sanction_lock(self):
		self.pay(self.invoice(self.vendor, 1000))
		batch = self.batch()
		with patch("frappe.db.sql", wraps=frappe.db.sql) as sql:
			batch.submit()
		queries = [str(c.args[0]) for c in sql.call_args_list]
		sanction_lock = next(i for i, q in enumerate(queries) if "`tabSanction`" in q and "FOR UPDATE" in q.upper())
		key_reads = [i for i, q in enumerate(queries) if "`tabPFMS Export Batch Row`" in q and "export_key" in q and q.lstrip().upper().startswith("SELECT")]
		self.assertTrue(key_reads)
		self.assertTrue(any(i > sanction_lock and "FOR UPDATE" in queries[i].upper() for i in key_reads))

	def test_cancelling_frees_the_rows_but_not_after_pfms_accepted_one(self):
		payment = self.pay(self.invoice(self.vendor, 1000))
		batch = self.exported()
		batch.cancel()
		self.assertFalse(frappe.db.get_value("PFMS Export Batch Row", batch.rows[0].name, "export_key"))
		self.assertEqual(self.vouchers(self.batch()), [("Payment Entry", payment.name)])
		accepted = self.exported()
		accepted.import_status(self.status_file(accepted, [(accepted.rows[0].row_reference, "Success", "PF2", "")]))
		with self.assertRaises(frappe.ValidationError):
			accepted.reload().cancel()

	# status import
	def test_status_import_updates_rows(self):
		first = self.pay(self.invoice(self.vendor, 1000))
		second = self.pay(self.invoice(self.vendor, 500))
		batch = self.exported()
		ref = {row.voucher_no: row.row_reference for row in batch.rows}
		result = batch.import_status(
			self.status_file(batch, [(ref[first.name], "Accepted", "PFMS-123", "ok"), (ref[second.name], "Failed", "", "Vendor inactive"), ("NOPE-9", "Success", "", "")])
		)
		batch.reload()
		rows = {row.voucher_no: row for row in batch.rows}
		self.assertEqual((rows[first.name].status, rows[first.name].pfms_reference), ("Success", "PFMS-123"))
		self.assertEqual((rows[second.name].status, rows[second.name].status_message), ("Failed", "Vendor inactive"))
		self.assertFalse(rows[second.name].export_key)
		self.assertEqual((batch.success_count, batch.failed_count, batch.status), (1, 1, "Processed"))
		self.assertEqual(result["updated"], 2)
		self.assertIn("NOPE-9", " ".join(result["skipped"]))
		# a later file can't turn an accepted row into a failed one
		again = batch.import_status(self.status_file(batch, [(ref[first.name], "Failed", "", "")]))
		self.assertEqual(again["updated"], 0)
		self.assertEqual(frappe.db.get_value("PFMS Export Batch Row", rows[first.name].name, "status"), "Success")

	def test_status_import_on_a_batch_cancelled_meanwhile_is_refused(self):
		self.pay(self.invoice(self.vendor, 1000))
		batch = self.exported()
		stale = frappe.get_doc(BATCH, batch.name)
		batch.cancel()
		with self.assertRaisesRegex(frappe.ValidationError, "submitted"):
			stale.import_status(self.status_file(stale, [(stale.rows[0].row_reference, "Success", "P1", "")]))
		self.assertEqual(frappe.db.get_value("PFMS Export Batch Row", stale.rows[0].name, "status"), "Exported")

	def test_status_import_keeps_the_batch_exported_while_rows_are_pending(self):
		self.pay(self.invoice(self.vendor, 1000))
		self.pay(self.invoice(self.vendor, 500))
		batch = self.exported()
		batch.import_status(self.status_file(batch, [(batch.rows[0].row_reference, "Success", "P1", "")]))
		self.assertEqual(batch.reload().status, "Exported")

	def test_status_import_needs_a_submitted_batch_and_the_layout_columns(self):
		self.pay(self.invoice(self.vendor, 1000))
		draft = self.batch()
		with self.assertRaises(frappe.ValidationError):
			draft.import_status(self.status_file(draft, []))
		batch = self.exported()
		with self.assertRaises(frappe.ValidationError):
			batch.import_status(self.status_file(batch, [("x", "Success")], header=("Ref", "State")))

	# acceptance 3: the column mapping is a record
	def test_the_column_mapping_can_be_changed_without_code(self):
		payment = self.pay(self.invoice(self.vendor, 1234.5, disable_rounded_total=1))
		layout = frappe.get_doc("PFMS Export Layout", DEFAULT_LAYOUTS["Expenditure"])
		self.assertTrue(layout.is_placeholder)
		layout.set("columns", [
			{"column_header": "Vendor", "source": "PFMS Vendor Code"},
			{"column_header": "Net", "source": "Amount"},
			{"column_header": "Ref", "source": "Row Reference"},
			{"column_header": "Scheme", "source": "Fixed Value", "fixed_value": "SCH-9"},
			{"column_header": "Agency", "source": "Agency Unique Code"},
			{"column_header": "Paid On", "source": "Payment Date"},
		])  # fmt: skip
		layout.date_format = "yyyy-mm-dd"
		layout.save()
		batch = self.exported()
		lines = self.file_rows(batch)
		self.assertEqual(lines[0], ["Vendor", "Net", "Ref", "Scheme", "Agency", "Paid On"])
		self.assertEqual(lines[1], ["V0001", "1234.50", batch.rows[0].row_reference, "SCH-9", "RSAT0001", str(payment.posting_date)])

	def test_a_layout_must_carry_the_row_reference_and_match_the_export_type(self):
		layout = frappe.get_doc("PFMS Export Layout", DEFAULT_LAYOUTS["Expenditure"])
		layout.set("columns", [{"column_header": "Amount", "source": "Amount"}])
		with self.assertRaises(frappe.ValidationError):
			layout.save()
		layout.reload()
		layout.append("columns", {"column_header": "Scheme", "source": "Fixed Value"})
		with self.assertRaises(frappe.ValidationError):
			layout.save()
		with self.assertRaises(frappe.ValidationError):
			self.batch("Advance", layout=DEFAULT_LAYOUTS["Expenditure"])

	def test_a_user_of_another_college_cannot_build_a_batch_of_this_sanction(self):
		self.pay(self.invoice(self.vendor, 1000))
		frappe.set_user(OTHER_COLLEGE_USER)
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.PermissionError):
			self.batch()

	def test_success_and_failure_values_must_not_overlap(self):
		layout = frappe.get_doc("PFMS Export Layout", DEFAULT_LAYOUTS["Expenditure"])
		self.assertEqual(layout.status_reference_column, "Unique Reference")  # the export's reference header
		layout.failure_values = "Failed\naccepted"
		with self.assertRaisesRegex(frappe.ValidationError, "accepted"):
			layout.save()

	def test_the_college_agency_code_is_required(self):
		frappe.db.set_value("Research Settings", COLLEGE, "pfms_unique_agency_code", None)
		frappe.clear_document_cache("Research Settings", COLLEGE)
		with self.assertRaises(frappe.ValidationError):
			self.batch()

	# CSV safety
	def test_csv_cells_starting_a_formula_are_neutralised(self):
		for value in ("=1+1", "+cmd", "-2+3", "@SUM(A1)", "\t=x", "\r=x", "  =x"):
			self.assertTrue(neutralise(value).startswith("'"), value)
		self.assertEqual(neutralise("ACME Ltd"), "ACME Ltd")
		self.assertEqual(neutralise(""), "")
		vendor = self.supplier("PFMS Bad", code='=HYPERLINK("http://x")')
		self.pay(self.invoice(vendor, 100))
		lines = self.file_rows(self.exported())
		self.assertIn("'=HYPERLINK(\"http://x\")", lines[1])
		self.assertFalse([cell for line in lines for cell in line if cell[:1] in "=+@"])

	# adapters
	def test_the_file_adapter_is_the_only_adapter_and_others_can_be_plugged(self):
		self.assertIsInstance(adapter_for("File"), FileAdapter)
		with self.assertRaises(frappe.ValidationError):
			adapter_for("PFMS API")
		with patch("frappe.get_hooks", return_value={"Mock": ["campus.research.pfms_adapter.FileAdapter"]}):
			self.assertIsInstance(adapter_for("Mock"), FileAdapter)
		for name in ("export_expenditure", "export_advance", "export_transfer", "import_status"):
			with self.assertRaises(NotImplementedError):
				getattr(pfms_adapter.PFMSAdapter(), name)(None, [] if name != "import_status" else "")

	def test_each_export_type_calls_its_adapter_method(self):
		self.advance(self.vendor, 300)
		with patch.object(FileAdapter, "export_advance", autospec=True, side_effect=FileAdapter.export_advance) as method:
			batch = self.exported("Advance")
		method.assert_called_once()
		self.assertTrue(batch.export_file)
		self.assertEqual(batch.status, "Exported")
		self.assertEqual({row.status for row in batch.rows}, {"Exported"})
