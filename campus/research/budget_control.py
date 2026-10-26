"""M08-04, M08-05 Expenditure tagging and budget control for sanctioned projects (P3-T15, blueprint D9).

Purchase Order, Purchase Invoice, Journal Entry and Expense Claim lines carry `oc_budget_head`. A line belongs to a
sanction when its project or cost centre is a submitted sanction's. Such a line must name a head of that sanction, post
to one of the head's accounts for the college, use the sanction's cost centre and project, and fall inside the sanction
period. A head can't be named on a line outside a sanction. Journal Entry rows are checked only when they post spending
(an expense or fixed asset account), so a Grant Receipt's bank and liability rows need no head.

Revenue heads are controlled by the sanction's ERPNext Budgets (grant_setup / budget_sync). A revenue line is refused
in a year no Budget covers. Capital heads have no ERPNext Budget (ERPNext budgets only income and expense), so their
limits are enforced here when a Purchase Order, Purchase Invoice or Journal Entry is submitted, when a submitted order's
items are updated (counting only an order line's unbilled part, its billed part being its invoice) and when a credit to the head (a debit note, a crediting journal) is cancelled, under a lock on the
sanction. A capital head's spending up to the end of each fiscal year can't pass what was sanctioned for it up to that
year, nor its total. Spending is the submitted invoice lines and journal rows tagged to the head, plus the unbilled
part of its open Purchase Orders, all net of taxes (non-recoverable tax capitalised on an asset is not counted). The
scheme's Budget Action decides Stop or Warn.

A payroll accrual's salary rows on a sanction (project staff, P3-T19) take the head their account maps to. A closed
sanction (Project Closure) takes no further lines: none are submitted or cancelled on it, and a Payment Entry
deduction on its project or cost centre is refused too. On submit and cancel the sanctions a document touches are
locked in name order before their closure is read."""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.query_builder.functions import Sum
from frappe.utils import flt, get_datetime, getdate

from campus.research.accounts import NON_SPENDING_EXPENSE_TYPES
from campus.research.api import check_sanction_open, head_accounts

BUDGET_HEAD_FIELD = "oc_budget_head"
LINE_TABLES = {
	"Purchase Order": "items",
	"Purchase Invoice": "items",
	"Journal Entry": "accounts",
	"Expense Claim": "expenses",
}
SANCTION_FIELDS = [
	"name",
	"company",
	"funding_scheme",
	"project",
	"cost_center",
	"start_date",
	"end_date",
	"project_closure",
]


def budget_head_fields():
	field = {
		"fieldname": BUDGET_HEAD_FIELD, "label": "Grant Budget Head", "fieldtype": "Link", "options": "Grant Budget Head",
		"insert_after": "project", "search_index": 1,  # the capital-limit locking reads go through it
		"description": "Required on lines of a sanctioned research project: the sanction head the line is spent from.",
	}  # fmt: skip
	return {
		doctype: [dict(field)]
		for doctype in (
			"Purchase Order Item",
			"Purchase Invoice Item",
			"Journal Entry Account",
			"Expense Claim Detail",
		)
	}


def setup_budget_head_fields():
	create_custom_fields(budget_head_fields(), update=True)


# line validation (validate of the four doctypes)
def validate_lines(doc, method=None):
	sanctions = {}
	if (
		doc.docstatus == 1
	):  # submitting: lock every sanction the lines touch, in one order, before reading closures
		for name, closure in locked_closures(doc, sanction_rows(doc)).items():
			sanctions[("closure", name)] = closure
	for row in doc.get(LINE_TABLES[doc.doctype]):
		Line(doc, row, sanctions).validate()


def sanction_rows(doc):
	"""The rows the line rules apply to: Journal Entry rows only when they post spending or name a head."""
	rows = doc.get(LINE_TABLES[doc.doctype]) or []
	if doc.doctype != "Journal Entry":
		return rows
	return [row for row in rows if row.get(BUDGET_HEAD_FIELD) or is_spending_account(row.account)]


def touched_sanctions(doc, rows):
	"""Names of the submitted sanctions whose project or cost centre the rows (or the document's project) are on."""
	names = set()
	for row in rows:
		for field, value in (
			("project", row.get("project") or doc.get("project")),
			("cost_center", row.get("cost_center")),
		):
			name = value and frappe.db.get_value("Sanction", {field: value, "docstatus": 1})
			if name:
				names.add(name)
	return sorted(names)


def locked_closures(doc, rows):
	"""{sanction: its Project Closure or None}, each sanction row locked, in name order (one lock order everywhere)."""
	return {
		name: frappe.db.get_value("Sanction", name, "project_closure", for_update=True)
		for name in touched_sanctions(doc, rows)
	}


def refuse_cancel_on_closed(doc, method=None):
	"""before_cancel of Purchase Order, Purchase Invoice, Journal Entry and Expense Claim: a closed sanction's ledger
	doesn't change, so its lines can't be cancelled either."""
	for name, closure in locked_closures(doc, sanction_rows(doc)).items():
		check_sanction_open(name, closure)


def validate_payment_deductions(doc, method=None):
	"""validate of Payment Entry: a deduction (write-off, charges) on a closed sanction's project or cost centre is
	refused; on submit the sanctions are locked first."""
	rows = doc.get("deductions") or []
	if doc.docstatus == 1:
		closures = locked_closures(doc, rows)
	else:
		closures = {
			name: frappe.db.get_value("Sanction", name, "project_closure")
			for name in touched_sanctions(doc, rows)
		}
	for name, closure in closures.items():
		check_sanction_open(name, closure)


def refuse_payment_cancel_on_closed(doc, method=None):
	"""before_cancel of Payment Entry: its deductions on a closed sanction's project or cost centre stay (the sanctions
	locked in name order first)."""
	for name, closure in locked_closures(doc, doc.get("deductions") or []).items():
		check_sanction_open(name, closure)


class Line:
	def __init__(self, doc, row, sanctions):
		self.doc, self.row, self.sanctions = doc, row, sanctions
		self.account = row.get(
			{"Journal Entry": "account", "Expense Claim": "default_account"}.get(
				doc.doctype, "expense_account"
			)
		)
		self.label = _("Row {0}").format(row.idx)

	def validate(self):
		row, head = self.row, self.row.get(BUDGET_HEAD_FIELD)
		if self.doc.doctype == "Journal Entry" and not head and not is_spending_account(self.account):
			return
		sanction = self.find_sanction()
		if not sanction:
			if head:
				frappe.throw(
					_("{0}: a Grant Budget Head goes only on lines of a sanctioned project.").format(
						self.label
					)
				)
			return
		self.check_open(sanction)
		row.project = sanction.project
		head = head or self.item_group_head(sanction) or self.payroll_head(sanction)
		if not head:
			frappe.throw(
				_("{0}: select the Grant Budget Head; the line is spent on Sanction {1}.").format(
					self.label, sanction.name
				)
			)
		row.set(BUDGET_HEAD_FIELD, head)
		self.check_date(sanction)
		self.check_head(sanction, head)

	def find_sanction(self):
		project = self.row.get("project") or self.doc.get("project")
		by_project = self.sanction_by("project", project)
		by_cost_center = self.sanction_by("cost_center", self.row.get("cost_center"))
		if by_project and by_project != by_cost_center:
			frappe.throw(
				_("{0}: project {1} is Sanction {2}'s, so the line must use its cost centre {3}.").format(
					self.label, project, by_project.name, by_project.cost_center
				)
			)
		if by_cost_center and project and not by_project:
			frappe.throw(
				_("{0}: cost centre {1} is Sanction {2}'s, so the line must use its project {3}.").format(
					self.label, self.row.cost_center, by_cost_center.name, by_cost_center.project
				)
			)
		return by_project or by_cost_center

	def sanction_by(self, field, value):
		if not value:
			return None
		key = (field, value)
		if key not in self.sanctions:
			self.sanctions[key] = frappe.db.get_value(
				"Sanction", {field: value, "docstatus": 1}, SANCTION_FIELDS, as_dict=True
			)
		return self.sanctions[key]

	def check_open(self, sanction):
		"""A closed sanction takes no more spending. On submit the closure is re-read with a locking read of the sanction
		row, which the Project Closure holds while it checks the ledger, so spending and closure never pass each other."""
		key = ("closure", sanction.name)
		if key not in self.sanctions:
			closure = sanction.project_closure
			if self.doc.docstatus == 1:
				closure = frappe.db.get_value("Sanction", sanction.name, "project_closure", for_update=True)
			self.sanctions[key] = closure
		check_sanction_open(sanction.name, self.sanctions[key])

	def payroll_head(self, sanction):
		"""A payroll accrual's salary row (P3-T19, project staff): the sanction head its account maps to; a sanction's
		heads never share an account."""
		if self.doc.doctype != "Journal Entry" or not any(
			r.reference_type == "Payroll Entry" for r in self.doc.accounts
		):
			return None
		heads = frappe.get_all(
			"Sanction Head", {"parent": sanction.name, "parenttype": "Sanction"}, pluck="budget_head"
		)
		return frappe.db.get_value(
			"Grant Budget Head Account",
			{
				"parent": ["in", heads or [""]],
				"parenttype": "Grant Budget Head",
				"company": sanction.company,
				"account": self.account,
			},
			"parent",
		)

	def item_group_head(self, sanction):
		group = self.row.get("item_group")
		return scheme_head_of_item_group(sanction.funding_scheme, group) if group else None

	def check_head(self, sanction, head):
		on_sanction = frappe.db.get_value(
			"Sanction Head",
			{"parent": sanction.name, "parenttype": "Sanction", "budget_head": head},
			"is_capital",
		)
		if on_sanction is None:
			frappe.throw(_("{0}: {1} is not a head of Sanction {2}.").format(self.label, head, sanction.name))
		if not self.account:
			frappe.throw(_("{0}: set the account the line posts to.").format(self.label))
		if self.account not in head_accounts(head, sanction.company):
			frappe.throw(
				_("{0}: account {1} is not an account of budget head {2}.").format(
					self.label, self.account, head
				)
			)
		group = self.row.get("item_group")
		group_head = scheme_head_of_item_group(sanction.funding_scheme, group) if group else None
		if group_head and group_head != head:
			frappe.throw(
				_("{0}: item group {1} belongs to budget head {2}, not {3}.").format(
					self.label, group, group_head, head
				)
			)
		if on_sanction and self.doc.doctype == "Expense Claim":
			frappe.throw(
				_("{0}: {1} is a capital head; buy it through a Purchase Invoice.").format(self.label, head)
			)
		if not on_sanction:
			self.check_budgeted(sanction, head)

	def check_date(self, sanction):
		date = getdate(line_date(self.doc))
		if not getdate(sanction.start_date) <= date <= getdate(sanction.end_date):
			frappe.throw(
				_("{0}: {1} is outside the sanction period of {2} ({3} to {4}).").format(
					self.label, frappe.format(date, "Date"), sanction.name,
					frappe.format(sanction.start_date, "Date"), frappe.format(sanction.end_date, "Date"),
				)
			)  # fmt: skip

	def check_budgeted(self, sanction, head):
		"""A revenue line is controlled by ERPNext Budget only inside a Budget's years: refuse it elsewhere."""
		date = getdate(line_date(self.doc))
		budget = frappe.db.exists(
			"Budget",
			{"cost_center": sanction.cost_center, "account": self.account, "docstatus": 1,
			 "budget_start_date": ["<=", date], "budget_end_date": [">=", date]},
		)  # fmt: skip
		if not budget:
			frappe.throw(
				_("{0}: budget head {1} of Sanction {2} has no budget for {3}.").format(
					self.label, head, sanction.name, frappe.format(date, "Date")
				)
			)


def line_date(doc):
	return doc.transaction_date if doc.doctype == "Purchase Order" else doc.posting_date


def is_spending_account(account):
	if not account:
		return False
	root_type, account_type = frappe.get_cached_value("Account", account, ["root_type", "account_type"])
	return account_type == "Fixed Asset" or (
		root_type == "Expense" and account_type not in NON_SPENDING_EXPENSE_TYPES
	)


def scheme_head_of_item_group(scheme, item_group):
	"""The scheme's head the item group is mapped under (at most one, checked on the scheme)."""
	heads = frappe.get_all(
		"Funding Scheme Head", {"parent": scheme, "parenttype": "Funding Scheme"}, pluck="budget_head"
	)
	return frappe.db.get_value(
		"Grant Budget Head Item Group",
		{"parent": ["in", heads or [""]], "parenttype": "Grant Budget Head", "item_group": item_group},
		"parent",
	)


# capital head limits: before_submit of Purchase Order, Purchase Invoice and Journal Entry, and a submitted Purchase
# Order's Update Items (before_update_after_submit). The document's own submitted rows are left out of the spending
# read and counted from the document, so an updated order counts once.
def check_capital_limits(doc, method=None):
	for (sanction, head), lines in sorted(capital_lines(doc).items()):
		if flt(sum(amount for _date, amount in lines), 2) > 0:
			check_head_limit(sanction, head, lines, billing=current_billing(doc), exclude=doc.name)


def validate_updated_order(doc, method=None):
	"""Update Items on a submitted Purchase Order: no new rows on a sanction's order (the dialog can't set their head,
	project or account), then the line rules and the capital limit, as at submit."""
	refuse_added_rows(doc)
	validate_lines(doc)
	check_capital_limits(doc)


def refuse_added_rows(doc):
	"""Update Items saves its new rows before the order, so they are the rows created after the order last changed."""
	if not any(row.get(BUDGET_HEAD_FIELD) for row in doc.items):
		return
	last_saved = frappe.db.get_value(doc.doctype, doc.name, "modified")
	for row in doc.items:
		if row.creation and get_datetime(row.creation) > get_datetime(last_saved):
			frappe.throw(
				_(
					"Row {0}: items can't be added to an order of a sanctioned project; raise a new Purchase Order for {1}."
				).format(row.idx, row.item_code)
			)


def check_capital_credit_cancel(doc, method=None):
	"""before_cancel of Purchase Invoice and Journal Entry: cancelling a credit to a capital head (a debit note, a
	journal crediting it) gives that spending back, so the head must still be within its limits without it."""
	for (sanction, head), lines in sorted(capital_lines(doc).items()):
		if flt(sum(amount for _date, amount in lines), 2) < 0:
			check_head_limit(sanction, head, [], exclude=doc.name)


def capital_lines(doc):
	"""{(sanction, head): [(date, amount in company currency)]} for the document's capital-head lines."""
	lines, sanctions = {}, {}
	for row in doc.get(LINE_TABLES[doc.doctype]):
		head = row.get(BUDGET_HEAD_FIELD)
		if not head or not frappe.get_cached_value("Grant Budget Head", head, "is_capital"):
			continue
		if row.project not in sanctions:
			sanctions[row.project] = frappe.db.get_value("Sanction", {"project": row.project, "docstatus": 1})
		lines.setdefault((sanctions[row.project], head), []).append((line_date(doc), line_amount(doc, row)))
	return lines


def line_amount(doc, row):
	if doc.doctype == "Journal Entry":
		return flt(row.debit) - flt(row.credit)
	if doc.doctype == "Purchase Order":  # the billed part is counted from its invoice
		return max(flt(row.amount) - flt(row.billed_amt), 0) * flt(doc.conversion_rate or 1)
	return flt(row.base_net_amount)


def current_billing(doc):
	"""{Purchase Order Item: amount} the invoice being submitted bills, not yet in the order's billed amount."""
	if doc.doctype != "Purchase Invoice":
		return {}
	billing = {}
	for row in doc.items:
		if row.get("po_detail"):
			billing[row.po_detail] = billing.get(row.po_detail, 0) + flt(row.amount)
	return billing


def check_head_limit(sanction, head, lines, billing=None, exclude=None):
	scheme = frappe.db.get_value(
		"Sanction", sanction, "funding_scheme", for_update=True
	)  # one check per sanction at a time
	spending = [*capital_spending(sanction, head, billing, exclude), *lines]
	breach = first_breach(head_limits(sanction, head), spending)
	if not breach:
		return
	message = _(
		"Budget head {0} of Sanction {1}: spending up to the end of {2} would be {3} against {4} sanctioned."
	).format(
		frappe.bold(head),
		sanction,
		breach.period,
		frappe.format(breach.spent, "Currency"),
		frappe.format(breach.limit, "Currency"),
	)
	if (frappe.db.get_value("Funding Scheme", scheme, "budget_action") or "Stop") == "Stop":
		frappe.throw(message, title=_("Budget Exceeded"))
	frappe.msgprint(message, indicator="orange", title=_("Budget Exceeded"))


def head_limits(sanction, head):
	"""[(fiscal year, year end, amount)] sanctioned for the head, read with a locking read, in year order."""
	row, year = frappe.qb.DocType("Sanction Head"), frappe.qb.DocType("Fiscal Year")
	return (
		frappe.qb.from_(row)
		.join(year).on(year.name == row.fiscal_year)
		.select(row.fiscal_year, year.year_end_date, row.amount)
		.where((row.parent == sanction) & (row.parenttype == "Sanction") & (row.budget_head == head))
		.orderby(year.year_start_date)
		.for_update()
		.run()
	)  # fmt: skip


def first_breach(limits, spending):
	"""The first year whose cumulative spending passes its cumulative limit, else the total; None when within."""
	sanctioned = 0
	for fiscal_year, year_end, amount in limits:
		sanctioned += flt(amount)
		spent = sum(flt(a) for date, a in spending if getdate(date) <= getdate(year_end))
		if flt(spent, 2) > flt(sanctioned, 2):
			return frappe._dict(period=fiscal_year, spent=spent, limit=sanctioned)
	spent = sum(flt(a) for _date, a in spending)
	if flt(spent, 2) > flt(sanctioned, 2):
		return frappe._dict(period=_("the sanction"), spent=spent, limit=sanctioned)
	return None


def capital_spending(sanction, head, billing=None, exclude=None):
	"""[(date, amount)] of submitted lines tagged to the head of the sanction's project, by locking reads, leaving out
	the document `exclude`."""
	project = frappe.db.get_value("Sanction", sanction, "project")
	exclude = exclude or ""
	return [
		*invoiced(project, head, exclude),
		*journalled(project, head, exclude),
		*ordered(project, head, billing or {}, exclude),
	]


def invoiced(project, head, exclude=""):
	item, invoice = frappe.qb.DocType("Purchase Invoice Item"), frappe.qb.DocType("Purchase Invoice")
	return (
		frappe.qb.from_(item).join(invoice).on(invoice.name == item.parent)
		.select(invoice.posting_date, item.base_net_amount)
		.where((invoice.docstatus == 1) & (item.project == project) & (item[BUDGET_HEAD_FIELD] == head) & (invoice.name != exclude))
		.for_update().run()
	)  # fmt: skip


def journalled(project, head, exclude=""):
	row, entry = frappe.qb.DocType("Journal Entry Account"), frappe.qb.DocType("Journal Entry")
	return (
		frappe.qb.from_(row).join(entry).on(entry.name == row.parent)
		.select(entry.posting_date, row.debit - row.credit)
		.where((entry.docstatus == 1) & (row.project == project) & (row[BUDGET_HEAD_FIELD] == head) & (entry.name != exclude))
		.for_update().run()
	)  # fmt: skip


def ordered(project, head, billing, exclude=""):
	"""The unbilled part of open orders, less what the invoice being submitted bills (as ERPNext Budget counts it)."""
	item, order = frappe.qb.DocType("Purchase Order Item"), frappe.qb.DocType("Purchase Order")
	rows = (
		frappe.qb.from_(item).join(order).on(order.name == item.parent)
		.select(order.transaction_date, item.name, item.amount, item.billed_amt, order.conversion_rate)
		.where(
			(order.docstatus == 1) & (order.status != "Closed") & (item.project == project) & (item[BUDGET_HEAD_FIELD] == head)
			& (order.name != exclude)
		)
		.for_update().run(as_dict=True)
	)  # fmt: skip
	unbilled = []
	for row in rows:
		left = flt(row.amount) - flt(row.billed_amt) - flt(billing.get(row.name))
		if left > 0:
			unbilled.append((row.transaction_date, left * flt(row.conversion_rate or 1)))
	return unbilled


def posted(cost_center, account):
	"""[(date, amount)] of GL on the account and cost centre (both indexed), by a locking read."""
	gl = frappe.qb.DocType("GL Entry")
	return (
		frappe.qb.from_(gl)
		.select(gl.posting_date, Sum(gl.debit - gl.credit))
		.where((gl.is_cancelled == 0) & (gl.account == account) & (gl.cost_center == cost_center))
		.groupby(gl.posting_date)
		.for_update().run()
	)  # fmt: skip


def head_overspend(sanction, head):
	"""The breach (period, spent, limit) of a head's current limits by its spending so far, else None. The caller holds
	the sanction lock."""
	values = frappe.db.get_value("Sanction", sanction, ["company", "cost_center", "project"], as_dict=True)
	if frappe.get_cached_value("Grant Budget Head", head, "is_capital"):
		spending = capital_spending(sanction, head)
	else:  # as ERPNext Budget counts it: posted GL plus unbilled orders (every order line here carries the head)
		spending = list(ordered(values.project, head, {}))
		for account in head_accounts(head, values.company):
			spending.extend(posted(values.cost_center, account))
	return first_breach(head_limits(sanction, head), spending)
