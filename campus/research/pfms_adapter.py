"""M08-07 PFMS adapters: how an export batch reaches PFMS and how PFMS's status comes back.

`PFMSAdapter` is the interface: export_expenditure, export_advance, export_transfer (rows -> an ExportFile) and
import_status (PFMS's status file -> StatusUpdates). Only the file adapter exists: it writes the EAT bulk-upload CSV
from a PFMS Export Layout record (the column mapping; the official EAT spec is not supplied yet, so the seeded layouts
are placeholders) and reads the status file by the layout's status columns. Nothing here calls PFMS.

Another app can plug in an adapter (e.g. an API adapter once the agency grants access) with the hook
`pfms_adapters = {"Name": "dotted.path.AdapterClass"}`; a batch names its adapter."""

import csv
import io
from dataclasses import dataclass

import frappe
from frappe import _
from frappe.utils import flt, getdate

DEFAULT_ADAPTER = "File"
FIXED_VALUE = "Fixed Value"
AMOUNT = "Amount"
ROW_REFERENCE = "Row Reference"
# layout source -> (where the value is read, field)
SOURCES = {
	ROW_REFERENCE: ("row", "row_reference"),
	"Agency Unique Code": ("batch", "agency_code"),
	"Funding Agency Code": ("batch", "funding_agency_code"),
	"Sanction Order No": ("batch", "sanction_order_no"),
	"Project": ("batch", "project"),
	"Payment Date": ("row", "posting_date"),
	"Voucher Type": ("row", "voucher_type"),
	"Voucher No": ("row", "voucher_no"),
	"Invoice or Order No": ("row", "reference_name"),
	AMOUNT: ("row", "amount"),
	"Vendor Name": ("row", "supplier_name"),
	"PFMS Vendor Code": ("row", "pfms_vendor_code"),
	"Bank Account No": ("row", "bank_account_no"),
	"IFSC": ("row", "ifsc"),
	"Budget Head": ("row", "budget_head"),
}
DATE_FORMATS = {"dd/mm/yyyy": "%d/%m/%Y", "dd-mm-yyyy": "%d-%m-%Y", "yyyy-mm-dd": "%Y-%m-%d"}
FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


@dataclass
class ExportFile:
	file_name: str
	content: str


@dataclass
class StatusUpdate:
	row_reference: str
	status: str  # "Success", "Failed" or "Unknown"
	pfms_reference: str = ""
	message: str = ""


class PFMSAdapter:
	"""The PFMS contract. `batch` is a PFMS Export Batch, `rows` its rows to send."""

	def export_expenditure(self, batch, rows) -> ExportFile:
		raise NotImplementedError

	def export_advance(self, batch, rows) -> ExportFile:
		raise NotImplementedError

	def export_transfer(self, batch, rows) -> ExportFile:
		raise NotImplementedError

	def import_status(self, batch, content: str) -> list[StatusUpdate]:
		raise NotImplementedError


class FileAdapter(PFMSAdapter):
	"""The EAT bulk-upload CSV, laid out by the batch's PFMS Export Layout, and its status file."""

	def export_expenditure(self, batch, rows):
		return self.write(batch, rows)

	def export_advance(self, batch, rows):
		return self.write(batch, rows)

	def export_transfer(self, batch, rows):
		return self.write(batch, rows)

	def write(self, batch, rows):
		layout = frappe.get_doc("PFMS Export Layout", batch.layout)
		buffer = io.StringIO()
		writer = csv.writer(buffer, lineterminator="\r\n")
		if layout.include_header:
			writer.writerow([neutralise(column.column_header) for column in layout.columns])
		for row in rows:
			writer.writerow([cell(layout, column, batch, row) for column in layout.columns])
		return ExportFile(f"{batch.name}-{layout.export_type.lower()}.csv", buffer.getvalue())

	def import_status(self, batch, content):
		layout = frappe.get_doc("PFMS Export Layout", batch.layout)
		reader = csv.DictReader(io.StringIO(content.lstrip("﻿")))
		columns = [layout.status_reference_column, layout.status_column, layout.status_pfms_reference_column, layout.status_message_column]
		missing = [c for c in columns[:2] if c not in (reader.fieldnames or [])]
		if missing:
			frappe.throw(_("The status file has no column {0} (PFMS Export Layout {1}).").format(", ".join(missing), layout.name))
		success, failure = value_set(layout.success_values), value_set(layout.failure_values)
		updates = []
		for line in reader:
			reported = (line.get(layout.status_column) or "").strip().lower()
			status = "Success" if reported in success else "Failed" if reported in failure else "Unknown"
			updates.append(
				StatusUpdate(
					(line.get(layout.status_reference_column) or "").strip(), status,
					(line.get(columns[2]) or "").strip() if columns[2] else "",
					(line.get(columns[3]) or "").strip() if columns[3] else "",
				)  # fmt: skip
			)
		return updates


ADAPTERS = {DEFAULT_ADAPTER: FileAdapter}


def adapter_for(name):
	"""An instance of the adapter called `name`: built in, or registered by an app's `pfms_adapters` hook."""
	adapter = ADAPTERS.get(name)
	if not adapter:
		paths = (frappe.get_hooks("pfms_adapters") or {}).get(name)
		adapter = frappe.get_attr(paths[-1]) if paths else None
	if not adapter:
		frappe.throw(_("PFMS adapter {0} is not available.").format(frappe.bold(name)))
	return adapter()


def cell(layout, column, batch, row):
	if column.source == FIXED_VALUE:
		return neutralise(column.fixed_value or "")
	owner, field = SOURCES[column.source]
	value = (row if owner == "row" else batch).get(field)
	if column.source == AMOUNT:
		return f"{flt(value, 2):.2f}"
	if field == "posting_date" and value:
		return getdate(value).strftime(DATE_FORMATS.get(layout.date_format) or DATE_FORMATS["dd/mm/yyyy"])
	return neutralise("" if value is None else str(value))


def neutralise(value):
	"""A CSV cell a spreadsheet won't run as a formula: text starting with = + - @ (or a tab / carriage return,
	ignoring leading spaces) gets a leading apostrophe."""
	value = value or ""
	stripped = value.lstrip(" ")
	if stripped[:1] in FORMULA_STARTS and stripped:
		return "'" + value
	return value


def value_set(text):
	return {line.strip().lower() for line in (text or "").replace(",", "\n").splitlines() if line.strip()}
