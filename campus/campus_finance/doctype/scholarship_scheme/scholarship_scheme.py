"""M05-05 Scholarship Scheme: government (AQAR 5.1.1) or institutional (AQAR 5.1.2), its eligibility, amount rule,
renewal criteria and the account its disbursements post to."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from campus.campus_finance.scholarships import FIXED, GOVERNMENT


class ScholarshipScheme(Document):
	def validate(self):
		self.validate_account()
		self.validate_amount_rule()
		if not self.renewable:
			self.renewal_min_attendance_pct, self.renewal_max_arrears = 0, 0
		elif not 0 <= flt(self.renewal_min_attendance_pct) <= 100 or (self.renewal_max_arrears or 0) < 0:
			frappe.throw(_("Renewal attendance must be between 0 and 100 and arrears cannot be negative."))

	def validate_account(self):
		account = frappe.db.get_value(
			"Account", self.account, ["company", "account_type", "root_type", "is_group"], as_dict=True
		)
		if account.company != self.company or account.is_group:
			frappe.throw(
				_("Account {0} must be a ledger account of {1}.").format(
					frappe.bold(self.account), self.company
				)
			)
		if self.scheme_type == GOVERNMENT and account.account_type not in ("Bank", "Cash"):
			frappe.throw(_("A government scheme is received into a Bank or Cash account."))
		if self.scheme_type != GOVERNMENT and account.root_type != "Expense":
			frappe.throw(_("An institutional scheme is booked to an Expense account."))

	def validate_amount_rule(self):
		if self.amount_type == FIXED:
			self.percent = 0
			if flt(self.amount) <= 0:
				frappe.throw(_("Give the fixed amount of the scheme."))
		else:
			self.amount = 0
			if not 0 < flt(self.percent) <= 100:
				frappe.throw(_("The percent of fee must be above 0 and at most 100."))
		if flt(self.max_amount) < 0:
			frappe.throw(_("The maximum amount cannot be negative."))
