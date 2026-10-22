"""M09-02 Bank Collection Import: match a bank's collection file to challans and post Payment Entries.

CSV columns: challan_no, amount, date, reference (extra columns are ignored). One Bank Collection Row is kept
per file row with its outcome: Matched (a Payment Entry was made), Unmatched (unknown challan, wrong company,
settled invoice or amount above the outstanding), Duplicate (bank reference already collected) or Invalid.

Concurrency (MariaDB REPEATABLE READ)
- The import runs as a bulk run with chunk=1: every row is its own transaction. Everything the runner does
  before the handler in a chunk is a locking read (Bulk Run row, processed keys) and the runner ends the
  snapshot of its initial key read with a commit, so the handler's invoice FOR UPDATE is the first
  snapshot-establishing statement of the transaction. That matters because ERPNext's own outstanding
  recomputation when the Payment Entry is submitted (update_voucher_outstanding) uses plain reads: they are
  only current if the snapshot starts after we hold the invoice lock. (With larger chunks a snapshot taken
  for an earlier row could be stale.) The post-submit negative-outstanding check below catches an
  overpayment visible to a locking read; it does NOT detect staleness inside ERPNext's recomputation, which
  chunk=1 prevents.
- Facts the handler decides on (outstanding amount, existing bank reference) are re-read with locking reads.
  Items are sorted by challan number so two imports lock invoices in the same order.
- Known limit: two imports that carry the same bank reference for different challans can deadlock on the gap
  lock of the unique reference lookup; MariaDB aborts one transaction, its run fails and can be resumed
  (resume_bulk), the committed rows being skipped.
- Every outcome of a row, errors and lock-wait timeouts included, is recorded as a Bank Collection Row so the
  import always completes.

Re-import safety: a Matched row stores `reference_key` = company + bank reference, a unique column, so a bank
reference can create at most one Payment Entry however often (or concurrently) a file is imported. The Payment
Entry also carries the reference as its `reference_no`. A reference whose Payment Entry was later cancelled stays
blocked: the entry must be re-made by hand.
"""

import csv
import io
import math

import frappe
from frappe import _
from frappe.utils import cstr, flt, getdate
from frappe.utils.file_manager import get_file

from campus.campus_platform.bulk import run_bulk

HANDLER = "campus.campus_finance.bank_import.process_row"
KEY = "campus.campus_finance.bank_import.row_key"
COLUMNS = ("challan_no", "amount", "date", "reference")
SAVEPOINT = "bank_collection_row"
ROW_SAVEPOINT = "bank_collection_item"
COUNTER = {"Matched": "matched_rows", "Unmatched": "unmatched_rows", "Duplicate": "duplicate_rows", "Invalid": "invalid_rows"}


@frappe.whitelist()
def start_import(name):
	"""Parse the attached CSV and queue the bulk run that matches its rows; returns the Bulk Run name."""
	frappe.has_permission("Bank Collection Import", "write", name, throw=True)
	status = frappe.db.get_value("Bank Collection Import", name, "status", for_update=True)  # a double click waits here
	if status != "Draft":
		frappe.throw(_("This import has already been started."))
	doc = frappe.get_doc("Bank Collection Import", name)
	rows = parse_rows(read_file(doc.collection_file))
	doc.db_set({"total_rows": len(rows), "status": "Processing"})
	items = [{"import": name, "company": doc.company, "row_no": no, **row} for no, row in enumerate(rows, start=1)]
	items.sort(key=lambda i: (i["challan_no"], i["row_no"]))  # consistent invoice lock order across imports
	run = run_bulk("Bank Collection Import", items, HANDLER, chunk=1, key=KEY, parameters={"import": name})
	doc.db_set("bulk_run", run)
	return run


def read_file(file_url):
	"""The attached file's content, after checking the user may read that File."""
	file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not file_name:
		frappe.throw(_("The bank file {0} was not found.").format(file_url))
	frappe.get_doc("File", file_name).check_permission("read")
	return get_file(file_url)[1]


def parse_rows(content):
	"""Rows of the CSV as dicts of text; raises when a required column is missing."""
	text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
	reader = csv.DictReader(io.StringIO(text))
	header = [cstr(h).strip().lower() for h in reader.fieldnames or []]
	missing = [c for c in COLUMNS if c not in header]
	if missing:
		frappe.throw(_("The bank file is missing the columns: {0}").format(", ".join(missing)))
	rows = []
	for raw in reader:
		row = {cstr(k).strip().lower(): cstr(v).strip() for k, v in raw.items() if k}
		if any(row.values()):
			rows.append({c: row.get(c, "") for c in COLUMNS})
	return rows


def row_key(item):
	return f"{item['import']}::{item['row_no']}"


def process_row(item, run):
	"""Bulk handler: record the row's outcome and, for a match, its Payment Entry. DB-only, no commit.

	Whatever goes wrong inside the row (lock wait, insert error, posting failure) is rolled back to a savepoint
	and recorded as an Invalid row with the message, so the import never stalls on a row.
	"""
	invalid = invalid_reason(item)  # pure checks: no database access before the lock
	if invalid:
		return record(item, "Invalid", invalid)
	frappe.db.savepoint(ROW_SAVEPOINT)
	invoice = None
	try:
		invoice = frappe.db.get_value(
			"Sales Invoice",
			{"oc_challan_no": item["challan_no"], "docstatus": 1},
			["name", "company", "customer", "currency", "outstanding_amount"],
			as_dict=True,
			for_update=True,  # first read: lock, and see the latest outstanding amount
		)
		match_row(item, invoice)
	except Exception as e:
		frappe.db.rollback(save_point=ROW_SAVEPOINT)
		record(item, "Invalid", _("Error: {0}").format(str(e)[:300]), invoice and invoice.name)


def match_row(item, invoice):
	if frappe.db.get_value("Bank Collection Row", {"reference_key": reference_key(item)}, "name", for_update=True):
		return record(item, "Duplicate", _("Bank reference already collected."))
	problem = unmatched_reason(invoice, item)
	if problem:
		return record(item, "Unmatched", problem)
	if frappe.db.get_value(
		"Payment Entry", {"company": item["company"], "reference_no": item["reference"], "docstatus": ("<", 2)}, "name", for_update=True
	):
		return record(item, "Duplicate", _("Bank reference already has a Payment Entry."), invoice.name)
	post_collection(item, invoice)


def reference_key(item):
	return f"{item['company']}::{item['reference']}"


def invalid_reason(item):
	if not (item["challan_no"] and item["reference"]):
		return _("Challan number and bank reference are required.")
	try:
		getdate(item["date"])
		if not math.isfinite(flt(item["amount"])) or flt(item["amount"]) <= 0:
			raise ValueError
	except Exception:
		return _("Amount must be positive and the date valid.")


def unmatched_reason(invoice, item):
	if not invoice or invoice.company != item["company"]:
		return _("No submitted invoice has this challan number.")
	if invoice.currency != frappe.get_cached_value("Company", item["company"], "default_currency"):
		return _("The invoice is not in the company currency.")
	if not flt(invoice.outstanding_amount):
		return _("The invoice is already paid.")
	if flt(item["amount"]) > flt(invoice.outstanding_amount):
		return _("The amount exceeds the outstanding {0}.").format(invoice.outstanding_amount)


def post_collection(item, invoice):
	"""Claim the bank reference (unique key) then make the Payment Entry; a lost claim is a Duplicate."""
	try:
		row = insert_row(item, "Matched", "", invoice.name, reference_key=reference_key(item))
	except frappe.UniqueValidationError:
		return record(item, "Duplicate", _("Bank reference already collected."), invoice.name)
	frappe.db.savepoint(SAVEPOINT)
	try:
		payment = make_payment_entry(item, invoice)
	except Exception as e:
		frappe.db.rollback(save_point=SAVEPOINT)
		frappe.db.delete("Bank Collection Row", {"name": row.name})
		return record(item, "Invalid", _("Payment Entry failed: {0}").format(str(e)[:300]), invoice.name)
	frappe.db.set_value("Bank Collection Row", row.name, "payment_entry", payment.name)
	bump(item["import"], "Matched")


def make_payment_entry(item, invoice):
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	account = frappe.db.get_value("Challan Format", item["company"], "receiving_account")
	if not account:
		frappe.throw(_("{0} has no Challan Format with a receiving account.").format(item["company"]))
	payment = get_payment_entry("Sales Invoice", invoice.name, party_amount=flt(item["amount"]), bank_account=None)
	payment.paid_to = account
	payment.paid_to_account_currency = frappe.get_cached_value("Account", account, "account_currency")
	payment.reference_no = item["reference"]
	payment.reference_date = payment.posting_date = getdate(item["date"])
	payment.insert(ignore_permissions=True)
	payment.submit()
	if flt(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount", for_update=True)) < 0:
		frappe.throw(_("The collection would overpay {0}.").format(invoice.name))
	return payment


def record(item, status, message, invoice=None):
	insert_row(item, status, message, invoice)
	bump(item["import"], status)


def insert_row(item, status, message, invoice=None, **extra):
	return frappe.get_doc(
		{
			"doctype": "Bank Collection Row", "bank_collection_import": item["import"], "row_no": item["row_no"],
			"challan_no": item["challan_no"], "amount": flt(item["amount"]) if _is_number(item["amount"]) else 0,
			"collection_date": getdate(item["date"]) if _is_date(item["date"]) else None,
			"bank_reference": item["reference"], "company": item["company"], "status": status, "message": message, "sales_invoice": invoice, **extra,
		}
	).insert(ignore_permissions=True)


def bump(import_name, status):
	"""Count one more row with `status`; the import is Completed once every file row has an outcome."""
	column = COUNTER[status]
	frappe.db.sql(f"update `tabBank Collection Import` set `{column}` = `{column}` + 1 where name = %s", import_name)
	counts = frappe.db.get_value("Bank Collection Import", import_name, ["total_rows", *COUNTER.values()], as_dict=True)
	if sum(counts[c] or 0 for c in COUNTER.values()) >= counts.total_rows:
		with_errors = counts.invalid_rows or counts.unmatched_rows
		frappe.db.set_value(
			"Bank Collection Import", import_name, "status", "Completed with errors" if with_errors else "Completed"
		)


def _is_number(value):
	try:
		return math.isfinite(float(value))
	except (TypeError, ValueError):
		return False


def _is_date(value):
	try:
		getdate(value)
		return bool(value)
	except Exception:
		return False
