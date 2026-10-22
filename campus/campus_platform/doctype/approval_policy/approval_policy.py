"""M17-03 Approval Policy: which documents need approval, by whom, level by level."""

import frappe
from frappe import _
from frappe.model.base_document import get_controller
from frappe.model.document import Document
from frappe.utils.safe_exec import _compile_code, _validate_safe_eval_syntax

from campus.campus_platform.approval_engine import registered_final_action
from campus.campus_platform.approval_rules import PENDING, parse_fieldnames
from campus.campus_platform.approvals import ApprovableDocument

NAMED_APPROVER_DOCTYPES = {"Role": "Role", "Position": "Position", "User": "User"}
LEVEL_FIELDS = (
	"approver_type", "approver", "scope_field", "limit_to_company", "min_approvals",
	"sla_hours", "escalate_to_type", "escalate_to", "escalate_scope_field", "can_edit_fields",
)  # fmt: skip


class ApprovalPolicy(Document):
	def validate(self):
		self.validate_document_type()
		self.validate_condition()
		for level in self.levels:
			self.validate_level(level)
		self.validate_final_action()
		self.validate_levels_frozen()

	def validate_document_type(self):
		if not frappe.get_meta(self.document_type).is_submittable:
			frappe.throw(_("Approval applies only to submittable document types."))
		if not issubclass(get_controller(self.document_type), ApprovableDocument):
			frappe.throw(_("{0} does not use the approval engine.").format(frappe.bold(self.document_type)))

	def validate_condition(self):
		if not (self.condition or "").strip():
			return
		try:
			_validate_safe_eval_syntax(self.condition)
			_compile_code(self.condition, filename="<condition>", mode="eval")  # rejects unsafe names
		except SyntaxError as e:
			frappe.throw(_("Condition is not a valid expression: {0}").format(e.msg or e))

	def validate_level(self, level):
		label = _("Level {0}").format(level.idx)
		if level.approver_type in NAMED_APPROVER_DOCTYPES or level.approver_type == "Field":
			if not level.approver:
				frappe.throw(
					_("{0}: Approver is required for type {1}.").format(label, _(level.approver_type))
				)
		self.validate_named(label, level.approver_type, level.approver)
		self.validate_named(label, level.escalate_to_type, level.escalate_to)
		if level.approver_type in ("Field", "Reporting Manager"):
			self.validate_fields(label, [level.approver])
		self.validate_fields(label, [level.scope_field, level.escalate_scope_field])
		self.validate_fields(label, parse_fieldnames(level.can_edit_fields))
		if (level.min_approvals or 0) < 1:
			level.min_approvals = 1

	def validate_named(self, label, approver_type, value):
		doctype = NAMED_APPROVER_DOCTYPES.get(approver_type)
		if doctype and value and not frappe.db.exists(doctype, value):
			frappe.throw(_("{0}: {1} {2} does not exist.").format(label, _(doctype), frappe.bold(value)))

	def validate_fields(self, label, fieldnames):
		meta = frappe.get_meta(self.document_type)
		for fieldname in filter(None, fieldnames):
			if not meta.has_field(fieldname) and fieldname != "owner":
				frappe.throw(
					_("{0}: {1} has no field {2}.").format(
						label, _(self.document_type), frappe.bold(fieldname)
					)
				)

	def validate_final_action(self):
		if self.on_final_action == "Set Field":
			self.validate_fields(_("On Final Approval"), [self.final_field])
		elif self.on_final_action == "Call Service":
			registered_final_action(self.final_method)

	def validate_levels_frozen(self):
		"""Running requests index into the levels; changing them mid-flight would misroute approvals."""
		before = self.get_doc_before_save()
		if not before or _levels(before) == _levels(self):
			return
		if frappe.db.exists("Approval Request", {"policy": self.name, "status": PENDING}):
			frappe.throw(_("Levels cannot change while requests under this policy are pending."))


def _levels(policy):
	return [tuple(str(level.get(f) or "") for f in LEVEL_FIELDS) for level in policy.levels]
