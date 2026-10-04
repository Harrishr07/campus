"""M03-01 Elective Group: a basket of electives of one curriculum semester (choose N, seat cap)."""

import frappe
from frappe import _
from frappe.model.document import Document


class ElectiveGroup(Document):
	def validate(self):
		if self.choose_n < 1:
			frappe.throw(_("Choose N must be at least 1."))
		if frappe.db.get_value("Curriculum", self.curriculum, "status") in ("Effective", "Superseded"):
			frappe.throw(_("Curriculum {0} is locked; create a new version to change its elective groups.").format(
				frappe.bold(self.curriculum)
			))

	def on_trash(self):
		self.validate()
