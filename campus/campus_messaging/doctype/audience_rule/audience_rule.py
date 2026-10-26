"""M16-02 Audience Rule: a saved definition of who a broadcast or circular is addressed to.

Resolution lives in campus.campus_messaging.audience; this controller validates the filters and
offers the pre-send recipient count.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.campus_messaging import audience

# rule type (or the "Guardians of" basis) -> (filter fields it needs, doctype each is checked against)
REQUIRED_FILTERS = {
	audience.ROLE: [("role", None)],
	audience.STUDENT_GROUP: [("student_group", "Student Group")],
	audience.PROGRAM_SEMESTER: [("program", "Program")],
	audience.DEPARTMENT: [("department", "Department")],
	audience.HOSTEL: [],
	audience.ROUTE: [],
}
COMPANY_FIELD = {"Student Group": "oc_company", "Program": "oc_company", "Department": "company"}


class AudienceRule(Document):
	def validate(self):
		basis = self.guardians_of if self.rule_type == audience.GUARDIANS_OF else self.rule_type
		if self.rule_type == audience.GUARDIANS_OF and not basis:
			frappe.throw(_("Choose whose guardians this rule addresses."))
		for fieldname, doctype in REQUIRED_FILTERS[basis]:
			self.check_filter(fieldname, doctype)

	def check_filter(self, fieldname, doctype):
		value = self.get(fieldname)
		if not value:
			frappe.throw(_("{0} is required for this rule type.").format(_(self.meta.get_label(fieldname))))
		if doctype and frappe.db.get_value(doctype, value, COMPANY_FIELD[doctype]) != self.company:
			frappe.throw(
				_("{0} {1} does not belong to {2}.").format(
					_(doctype), frappe.bold(value), frappe.bold(self.company)
				)
			)

	def resolve(self):
		return audience.resolve(self)

	def count(self):
		return audience.count(self)


@frappe.whitelist()
def preview_count(audience_rule):
	"""Number of recipients the rule addresses right now (shown before sending)."""
	rule = frappe.get_doc("Audience Rule", audience_rule)
	rule.check_permission("read")
	return rule.count()
