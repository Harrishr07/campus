"""M08-07 PFMS Export Batch: the payments of a sanction for a period, of one export type (expenditure, advance or
transfer), sent to PFMS through an adapter (campus.research.pfms_adapter; the file adapter writes the EAT bulk-upload
file from the batch's PFMS Export Layout).

A draft lists the payments (campus.research.pfms.PaymentSelection) and the excluded ones with their reasons (no PFMS
vendor code, no bank details, an invoice only partly on the sanction). Submitting re-selects them under a lock on the
sanction with a locking read of the exported keys, gives each row its reference and export key (unique in the
database, so a payment sits in one live batch only) and attaches the export file. Import Status reads PFMS's status
file: accepted rows are final, failed rows free their key so the next batch of the period exports them again. A batch
with a row PFMS accepted can't be cancelled; cancelling any other frees its rows. Release After Review lets an
Accounts Manager send a line held for review in the next batch (logged as a PFMS Export Release)."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

from campus.research.grant_recognition import lock_sanction
from campus.research.pfms import PaymentSelection, default_layout, export_key, release_after_review
from campus.research.pfms_adapter import DEFAULT_ADAPTER, adapter_for

ROW_DOCTYPE = "PFMS Export Batch Row"
EXPORT_METHODS = {"Expenditure": "export_expenditure", "Advance": "export_advance", "Transfer": "export_transfer"}
ROW_FIELDS = (
	"voucher_type", "voucher_no", "reference_doctype", "reference_name", "posting_date", "supplier", "supplier_name",
	"pfms_vendor_code", "bank_account", "bank_account_no", "ifsc", "budget_head", "amount", "payment_key",
)  # fmt: skip


class PFMSExportBatch(Document):
	def validate(self):
		sanction = self.set_from_sanction()
		self.check_sanction_access()
		if getdate(self.from_date) > getdate(self.to_date):
			frappe.throw(_("The From Date can't be after the To Date."))
		self.adapter = self.adapter or DEFAULT_ADAPTER
		adapter_for(self.adapter)
		self.check_layout()
		if self.docstatus == 0:
			self.status = "Draft"
			self.set_rows(self.selection(sanction))

	def before_submit(self):
		sanction = lock_sanction(self.sanction)
		if sanction.docstatus != 1:
			frappe.throw(_("Sanction {0} must be submitted.").format(self.sanction))
		self.set_rows(self.selection(sanction, lock=True))
		if not self.rows:
			frappe.throw(
				_("Nothing to export: every {0} payment of Sanction {1} in the period is already exported or excluded.").format(
					_(self.export_type).lower(), self.sanction
				)
			)
		for row in self.rows:
			row.row_reference = f"{self.name}-{row.idx}"
			row.export_key = export_key(row.voucher_type, row.voucher_no, row.reference_doctype, row.reference_name)
			row.status = "Exported"
		self.status = "Exported"

	def on_submit(self):
		adapter = adapter_for(self.adapter)
		export = getattr(adapter, EXPORT_METHODS[self.export_type])(self, self.rows)
		file = frappe.get_doc(
			{
				"doctype": "File", "file_name": export.file_name, "content": export.content, "is_private": 1,
				"attached_to_doctype": self.doctype, "attached_to_name": self.name, "attached_to_field": "export_file",
			}  # fmt: skip
		).insert(ignore_permissions=True)
		self.db_set("export_file", file.file_url)

	def before_cancel(self):
		row = frappe.qb.DocType(ROW_DOCTYPE)
		accepted = (
			frappe.qb.from_(row).select(row.row_reference)
			.where((row.parent == self.name) & (row.parenttype == self.doctype) & (row.status == "Success"))
			.for_update().run(pluck=True)
		)  # fmt: skip
		if accepted:
			frappe.throw(
				_("{0} can't be cancelled: PFMS accepted rows {1}.").format(self.name, ", ".join(accepted[:5]))
			)

	def on_cancel(self):
		row = frappe.qb.DocType(ROW_DOCTYPE)
		frappe.qb.update(row).set(row.export_key, None).where((row.parent == self.name) & (row.parenttype == self.doctype)).run()
		self.db_set("status", "Cancelled")

	@frappe.whitelist()
	def import_status(self, file_url):
		"""Apply PFMS's status file (an uploaded File) to the rows; returns {updated, skipped}."""
		self.check_permission("submit")
		if self.docstatus != 1:
			frappe.throw(_("Import the status of a submitted batch."))
		file = frappe.get_doc("File", {"file_url": file_url})
		if not file.has_permission("read"):
			frappe.throw(_("You can't read {0}.").format(file_url), frappe.PermissionError)
		content = file.get_content()
		if isinstance(content, bytes):
			content = content.decode("utf-8-sig")
		return self.apply_status(adapter_for(self.adapter).import_status(self, content))

	@frappe.whitelist()
	def release_after_review(self, exclusion: str, reason: str):
		"""Release the excluded line `exclusion` (held for review) to the next batch; returns the PFMS Export Release."""
		return release_after_review(self, exclusion, reason)

	def apply_status(self, updates):
		# one import at a time, and never into a batch cancelled since this one was loaded
		if frappe.db.get_value(self.doctype, self.name, "docstatus", for_update=True) != 1:
			frappe.throw(_("{0} is no longer submitted: its status can't be imported.").format(self.name))
		rows = {row.row_reference: row for row in self.locked_rows()}
		updated, skipped = 0, []
		for update in updates:
			row = rows.get(update.row_reference)
			problem = self.status_problem(update, row)
			if problem:
				skipped.append(problem)
				continue
			values = {"status": update.status, "pfms_reference": update.pfms_reference, "status_message": update.message}
			if update.status == "Failed":
				values["export_key"] = None  # the next batch of the period exports it again
			frappe.db.set_value(ROW_DOCTYPE, row.name, values)
			row.status = update.status
			updated += 1
		self.set_status_counts(rows.values())
		self.add_comment("Info", _("PFMS status imported: {0} rows updated, {1} skipped.").format(updated, len(skipped)))
		return {"updated": updated, "skipped": skipped}

	def status_problem(self, update, row):
		if not row:
			return _("{0}: not a row of {1}.").format(update.row_reference or _("(blank)"), self.name)
		if update.status == "Unknown":
			return _("{0}: status not recognised.").format(update.row_reference)
		if row.status != "Exported":
			return _("{0}: already {1}.").format(update.row_reference, _(row.status))
		return None

	def locked_rows(self):
		row = frappe.qb.DocType(ROW_DOCTYPE)
		return (
			frappe.qb.from_(row).select(row.name, row.row_reference, row.status)
			.where((row.parent == self.name) & (row.parenttype == self.doctype))
			.for_update().run(as_dict=True)
		)  # fmt: skip

	def set_status_counts(self, rows):
		statuses = [row.status for row in rows]
		self.db_set(
			{
				"success_count": statuses.count("Success"), "failed_count": statuses.count("Failed"),
				"status": "Exported" if "Exported" in statuses else "Processed",
			}  # fmt: skip
		)

	# set-up
	def set_from_sanction(self):
		sanction = frappe.db.get_value(
			"Sanction", self.sanction,
			["name", "docstatus", "company", "funding_agency", "sanction_order_no", "project", "cost_center"], as_dict=True,
		)  # fmt: skip
		if not sanction or sanction.docstatus != 1:
			frappe.throw(_("Sanction {0} must be submitted.").format(self.sanction))
		for field in ("company", "funding_agency", "sanction_order_no", "project", "cost_center"):
			self.set(field, sanction[field])
		self.currency = frappe.get_cached_value("Company", self.company, "default_currency")
		self.agency_code = frappe.db.get_value("Research Settings", self.company, "pfms_unique_agency_code")
		if not self.agency_code:
			frappe.throw(_("Set the PFMS Unique Agency Code in {0}'s Research Settings.").format(self.company))
		self.funding_agency_code = frappe.db.get_value("Funding Agency", self.funding_agency, "pfms_agency_code")
		return sanction

	def check_sanction_access(self):
		"""Rows carry suppliers' bank details: build them only for a user who may read the sanction and create a
		batch of its college (the create check at insert ran before the college was set)."""
		if self.flags.ignore_permissions:
			return
		frappe.has_permission("Sanction", "read", self.sanction, throw=True)
		if self.is_new():
			self.check_permission("create")

	def check_layout(self):
		self.layout = self.layout or default_layout(self.export_type)
		if not self.layout:
			frappe.throw(_("Set up a PFMS Export Layout for {0} exports.").format(_(self.export_type)))
		layout_type = frappe.db.get_value("PFMS Export Layout", self.layout, "export_type")
		if layout_type != self.export_type:
			frappe.throw(_("PFMS Export Layout {0} is for {1} exports, not {2}.").format(self.layout, _(layout_type), _(self.export_type)))

	def selection(self, sanction, lock=False):
		return PaymentSelection(sanction, self.export_type, self.from_date, self.to_date, lock).run()

	def set_rows(self, selection):
		self.set("rows", [{field: payment.get(field) for field in ROW_FIELDS} | {"status": "Pending"} for payment in selection.rows])
		self.set("exclusions", selection.exclusions)
		self.row_count = len(self.rows)
		self.total_amount = flt(sum(flt(row.amount) for row in self.rows), 2)
		self.excluded_count = len(self.exclusions)
		self.already_exported_count = selection.already_exported
