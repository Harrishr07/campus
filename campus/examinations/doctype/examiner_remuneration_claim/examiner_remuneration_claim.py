"""M06-04 Examiner Remuneration Claim: an examiner's pay for one Exam Session, computed on every save from the source
records (campus.examinations.remuneration): scripts valued per round, papers set or scrutinised, invigilation duties,
each times the Remuneration Rate in force on the work date. Posted lines are ignored. Each source is claimed once: the
lines' source keys are unique in the database (cleared when a claim is cancelled) and re-read under a lock on the
examiner. On submit the lines are recomputed and must not have changed since approval.

Needs an approved approval request (Accounts Manager of the company by default; the requester, the owner and the
examiner never approve). The final approval submits the claim, which pays it (campus.examinations.remuneration_payment):
an internal examiner by an Additional Salary on the next payroll, an external examiner (an External Member with a
Supplier) by a draft Purchase Invoice with TDS per the Supplier's Tax Withholding Category.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from campus.campus_platform.api import ApprovableDocument
from campus.examinations import remuneration, remuneration_payment

INTERNAL = "Internal"
LINE_FIELDS = (
	"source_key", "activity", "source_doctype", "source_name", "details", "work_date", "quantity", "rate", "amount", "remuneration_rate", "item",
)  # fmt: skip


class ExaminerRemunerationClaim(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		session = frappe.db.get_value("Exam Session", self.exam_session, "company")
		if not session:
			frappe.throw(_("Exam Session {0} does not exist.").format(self.exam_session))
		self.company = session
		self.currency = frappe.get_cached_value("Company", self.company, "default_currency")
		self.set_examiner()
		self.set_lines()
		if self.examiner_type != INTERNAL:
			remuneration_payment.invoice_lines(self)

	def on_submit(self):
		if self.examiner_type == INTERNAL:
			additional = remuneration_payment.post_additional_salary(self)
			self.db_set({"additional_salary": additional.name, "payroll_date": additional.payroll_date})
		else:
			invoice = remuneration_payment.draft_purchase_invoice(self)
			self.db_set({"purchase_invoice": invoice.name, **remuneration_payment.payable_figures(invoice)})

	def before_cancel(self):
		if self.examiner_type != INTERNAL:
			remuneration_payment.refuse_cancel_after_invoice(self)

	def on_cancel(self):
		if self.examiner_type == INTERNAL:
			remuneration_payment.cancel_additional_salary(self)
		else:
			remuneration_payment.delete_draft_invoice(self)
		frappe.db.set_value(remuneration.CLAIM_ITEM, {"parenttype": self.doctype, "parent": self.name}, "source_key", None)

	def approval_excluded_users(self):
		return [self.examiner_user]

	def set_examiner(self):
		"""Name, user, and for an external examiner the Supplier and its TDS section, from the masters."""
		if self.examiner_type == INTERNAL:
			self.external_member = self.supplier = self.tds_section = None
			employee = frappe.db.get_value("Employee", self.employee, ["employee_name", "user_id", "company"], as_dict=True)
			if not employee:
				frappe.throw(_("Employee {0} does not exist.").format(self.employee))
			if employee.company != self.company:
				frappe.throw(_("{0} is not an employee of {1}.").format(employee.employee_name, self.company))
			self.examiner_name, self.examiner_user = employee.employee_name, employee.user_id
			return
		self.employee = None
		member = frappe.db.get_value("External Member", self.external_member, ["member_name", "email", "supplier"], as_dict=True)
		if not member:
			frappe.throw(_("External Member {0} does not exist.").format(self.external_member))
		self.examiner_name, self.supplier = member.member_name, member.supplier
		self.examiner_user = member.email and frappe.db.get_value("User", {"email": member.email})
		if not self.supplier:
			frappe.throw(_("{0} has no Supplier; create one from the External Member first.").format(self.examiner_name))
		self.tds_section = frappe.db.get_value("Supplier", self.supplier, "tax_withholding_category")
		if not self.tds_section:
			frappe.throw(_("Ask Accounts to set the TDS category on Supplier {0}.").format(self.supplier))

	def set_lines(self):
		lines, held_by = remuneration.work_lines(self)
		if not lines:
			if held_by:
				frappe.throw(_("The work of {0} in {1} is already claimed in {2}.").format(self.examiner_name, self.exam_session, ", ".join(held_by)))
			frappe.throw(_("{0} has no completed work in {1} to claim.").format(self.examiner_name, self.exam_session))
		if self.line_values(lines) != self.line_values(self.items):
			if self._action == "submit":
				frappe.throw(_("The work or rates of this claim changed after it was approved. Cancel and amend it."))
			self.set("items", lines)  # unchanged rows are kept, so a save while pending changes nothing
		self.total_amount = flt(sum(flt(row.amount) for row in self.items), 2)

	@staticmethod
	def line_values(rows):
		numeric = ("quantity", "rate", "amount")
		return sorted(tuple(str(flt(row.get(f)) if f in numeric else row.get(f) or "") for f in LINE_FIELDS) for row in rows)
