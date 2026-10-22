"""M09-01 Fee heads: the seeded Fee Categories, their per-company accounting defaults and the caution deposit rule.

A Fee Category is the fee head; Education gives each one an Item whose per-company Item Default carries the
income account and cost centre invoices post to. Caution deposits are refundable money held for the student, so
their account must be a liability: it is validated on the Fee Category, on Fee Structure and on every Sales Invoice,
and a caution deposit can therefore never post to income.
"""

import frappe
from frappe import _
from frappe.utils.caching import request_cache

TUITION, EXAM, DEVELOPMENT, LIBRARY, LAB = "Tuition", "Exam", "Development", "Library", "Lab"
HOSTEL, MESS, TRANSPORT = "Hostel", "Mess", "Transport"
CAUTION_DEPOSIT, FINE, CONDONATION, CERTIFICATE = "Caution Deposit", "Fine", "Condonation", "Certificate"

SAC_EDUCATION = "999294"

# Fee head -> (refundable, GST applicable). Each seeded category is named after its head.
FEE_HEADS = {
	TUITION: (0, 0), EXAM: (0, 0), DEVELOPMENT: (0, 0), LIBRARY: (0, 0), LAB: (0, 0),
	HOSTEL: (0, 1), MESS: (0, 1), TRANSPORT: (0, 1),
	CAUTION_DEPOSIT: (1, 0), FINE: (0, 0), CONDONATION: (0, 0), CERTIFICATE: (0, 0),
}  # fmt: skip


def seed_fee_categories():
	"""Create the 12 standard Fee Categories with their Items. Idempotent; existing ones are left as they are."""
	ensure_item_prerequisites()
	for head, (refundable, gst) in FEE_HEADS.items():
		name = frappe.db.exists("Fee Category", head)
		if not name:
			ensure_item(head)
			frappe.get_doc(
				{
					"doctype": "Fee Category", "category_name": head, "description": head, "oc_fee_head_type": head,
					"oc_refundable": refundable, "oc_gst_applicable": gst,
				}
			).insert(ignore_permissions=True)
		elif not frappe.db.get_value("Fee Category", name, "oc_fee_head_type"):
			frappe.db.set_value("Fee Category", name, "oc_fee_head_type", head)


def ensure_item_prerequisites():
	"""Fee Category makes an Item in the "Fee Component" group; a bare site may lack the group or the UOM."""
	if not frappe.db.exists("UOM", "Nos"):
		frappe.get_doc({"doctype": "UOM", "uom_name": "Nos"}).insert(ignore_permissions=True)
	if not frappe.db.exists("Item Group", "Fee Component"):
		parent = "All Item Groups"
		if not frappe.db.exists("Item Group", parent):
			frappe.get_doc({"doctype": "Item Group", "item_group_name": parent, "is_group": 1}).insert(ignore_permissions=True)
		frappe.get_doc({"doctype": "Item Group", "item_group_name": "Fee Component", "parent_item_group": parent}).insert(
			ignore_permissions=True
		)


def ensure_item(head):
	"""The service Item of a fee head, made before its Fee Category (which reuses an existing Item of the same name).

	Where India Compliance validates HSN/SAC on sales items the Item needs a SAC code, which Education's own
	item creation does not set; education services use SAC 999294.
	"""
	if frappe.db.exists("Item", head):
		return
	item = {
		"doctype": "Item", "item_code": head, "item_group": "Fee Component", "description": head,
		"is_sales_item": 1, "is_stock_item": 0, "stock_uom": "Nos",
	}
	if frappe.get_meta("Item").has_field("gst_hsn_code"):
		item["gst_hsn_code"] = ensure_sac_code()
	frappe.get_doc(item).insert(ignore_permissions=True)


def ensure_sac_code():
	if not frappe.db.exists("GST HSN Code", SAC_EDUCATION):
		frappe.get_doc(
			{"doctype": "GST HSN Code", "hsn_code": SAC_EDUCATION, "description": "Other education and training services"}
		).insert(ignore_permissions=True)
	return SAC_EDUCATION


def category_for_type(head_type):
	"""The Fee Category of a fee head type (the seeded one when several exist)."""
	name = frappe.db.get_value("Fee Category", {"oc_fee_head_type": head_type}, "name", order_by="creation")
	if not name:
		frappe.throw(_("No Fee Category of type {0}. Run the Campus Finance setup.").format(head_type))
	return name


def set_item_default(fee_category, company, income_account, cost_center):
	"""Set the income account and cost centre invoices of `fee_category` use in `company`."""
	category = frappe.get_doc("Fee Category", fee_category)
	row = next((d for d in category.item_defaults if d.company == company), None) or category.append(
		"item_defaults", {"company": company}
	)
	row.income_account, row.selling_cost_center = income_account, cost_center
	category.save(ignore_permissions=True)
	return category


def is_liability(account):
	return frappe.get_cached_value("Account", account, "root_type") == "Liability"


def validate_fee_category(doc, method=None):
	"""Caution deposits are refundable and may only default to a liability account."""
	if doc.oc_fee_head_type != CAUTION_DEPOSIT:
		return
	doc.oc_refundable = 1
	for row in doc.item_defaults:
		if row.income_account and not is_liability(row.income_account):
			frappe.throw(
				_("Row {0}: a Caution Deposit must post to a liability account; {1} is not one.").format(
					row.idx, row.income_account
				)
			)


@request_cache
def caution_items():
	"""Names of the Caution Deposit categories and of their Items (item codes on invoices)."""
	rows = frappe.get_all("Fee Category", {"oc_fee_head_type": CAUTION_DEPOSIT}, ["name", "item"], limit=0)
	return {value for row in rows for value in (row.name, row.item) if value}


def validate_invoice_accounts(doc, method=None):
	"""A caution deposit line on a Sales Invoice must credit a liability account, never income."""
	items = [row for row in doc.get("items") if row.item_code]
	if not items:
		return
	deposits = caution_items()
	for row in items:
		if row.item_code in deposits and not (row.income_account and is_liability(row.income_account)):
			frappe.throw(
				_("Row {0}: {1} is a Caution Deposit and must post to a liability account, not {2}.").format(
					row.idx, row.item_code, row.income_account or _("an income account")
				)
			)


def validate_fee_structure(doc, method=None):
	"""Warn early: a caution deposit component whose company default is missing or not a liability."""
	deposits = caution_items()
	for row in doc.get("components"):
		if row.fees_category not in deposits:
			continue
		account = frappe.db.get_value(
			"Fee Category Default", {"parent": row.fees_category, "company": doc.company}, "income_account"
		)
		if not account or not is_liability(account):
			frappe.throw(
				_("Row {0}: set a liability account as the {1} default for {2}.").format(row.idx, row.fees_category, doc.company)
			)
