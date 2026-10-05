"""M09-02 Bank Collection Import: match a bank's collection file to challans and post Payment Entries.

CSV columns: challan_no, amount, date, reference (extra columns are ignored). One Bank Collection Row is kept
per file row with its outcome: Matched (a Payment Entry was made), Unmatched (unknown challan, wrong company,
settled invoice or amount above the outstanding), Duplicate (bank reference already collected) or Invalid.

Re-import safety: a Matched row stores `reference_key` = company + bank reference, a unique column, so a bank
reference can create at most one Payment Entry however often (or concurrently) a file is imported. The Payment
Entry also carries the reference as its `reference_no`. A reference whose Payment Entry was later cancelled stays
blocked: the entry must be re-made by hand.
"""

import csv
import io

import frappe
from frappe import _
from frappe.utils import cstr, flt, getdate
from frappe.utils.file_manager import get_file

from campus.campus_platform.bulk import run_bulk

HANDLER = "campus.campus_finance.bank_import.process_row"
KEY = "campus.campus_finance.bank_import.row_key"
COLUMNS = ("challan_no", "amount", "date", "reference")
SAVEPOINT = "bank_collection_row"
COUNTER = {"Matched": "matched_rows", "Unmatched": "unmatched_rows", "Duplicate": "duplicate_rows", "Invalid": "invalid_rows"}


@frappe.whitelist()
def start_import(name):
	"""Parse the attached CSV and queue the bulk run that matches its rows; returns the Bulk Run name."""
	doc = frappe.get_doc("Bank Collection Import", name)
	doc.check_permission("write")
	if doc.status != "Draft":
		frappe.throw(_("This import has already been started."))
	rows = parse_rows(read_file(doc.collection_file))
	doc.db_set({"total_rows": len(rows), "status": "Processing"})
	items = [{"import": name, "company": doc.company, "row_no": no, **row} for no, row in enumerate(rows, start=1)]
	run = run_bulk("Bank Collection Import", items, HANDLER, key=KEY, parameters={"import": name})
	doc.db_set("bulk_run", run)
	return run


def read_file(file_url):
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
	"""Bulk handler: record the row's outcome and, for a match, its Payment Entry. DB-only, no commit."""
	invalid = invalid_reason(item)
	if invalid:
		return record(item, "Invalid", invalid)
	if frappe.db.exists("Bank Collection Row", {"reference_key": reference_key(item)}):
		return record(item, "Duplicate", _("Bank reference already collected."))
	invoice = frappe.db.get_value(
		"Sales Invoice",
		{"oc_challan_no": item["challan_no"], "docstatus": 1},
		["name", "company", "customer", "outstanding_amount"],
		as_dict=True,
		for_update=True,  # latest outstanding, and serialises two files paying one challan
	)
	problem = unmatched_reason(invoice, item)
	if problem:
		return record(item, "Unmatched", problem)
	if frappe.db.exists("Payment Entry", {"company": item["company"], "reference_no": item["reference"], "docstatus": ("<", 2)}):
		return record(item, "Duplicate", _("Bank reference already has a Payment Entry."), invoice.name)
	post_collection(item, invoice)


def reference_key(item):
	return f"{item['company']}::{item['reference']}"


def invalid_reason(item):
	if not (item["challan_no"] and item["reference"]):
		return _("Challan number and bank reference are required.")
	try:
		getdate(item["date"])
		if flt(item["amount"]) <= 0:
			raise ValueError
	except Exception:
		return _("Amount must be positive and the date valid.")


def unmatched_reason(invoice, item):
	if not invoice or invoice.company != item["company"]:
		return _("No submitted invoice has this challan number.")
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
			"bank_reference": item["reference"], "status": status, "message": message, "sales_invoice": invoice, **extra,
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
		float(value)
		return True
	except (TypeError, ValueError):
		return False


def _is_date(value):
	try:
		getdate(value)
		return bool(value)
	except Exception:
		return False
