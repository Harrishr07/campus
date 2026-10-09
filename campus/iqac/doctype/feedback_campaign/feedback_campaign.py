"""M01-05 / M07-04 Feedback Campaign: a Feedback Form put to one audience (students of a course offering, students,
parents, teachers, alumni or employers) inside a window, anonymous by default, with reminders and an Action Taken note.

Once a response exists the form, audience, offering, instructor, college and anonymity are fixed: responses copy them,
and turning a named campaign anonymous later would not remove what was stored. A closed campaign with responses cannot
reopen (only closed campaigns are analysed, and late answers would show by difference).
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today

OFFERING_AUDIENCES = ("Course Offering Students", "Parents", "Teachers")
EXTERNAL_AUDIENCES = ("Alumni", "Employers")
LOCKED_ONCE_ANSWERED = ("form", "audience", "course_offering", "instructor", "audience_rule", "company", "is_anonymous")


class FeedbackCampaign(Document):
	def validate(self):
		if getdate(self.end_date) < getdate(self.start_date):
			frappe.throw(_("The campaign cannot close before it opens."))
		self.validate_audience()
		self.instructor = self.instructor or self.offering_instructor()
		self.validate_locked()

	def validate_audience(self):
		if self.audience in EXTERNAL_AUDIENCES or self.audience == OFFERING_AUDIENCES[0]:
			self.audience_rule = None  # offering students are the offering's own members (their CO scores count)
		if self.audience not in EXTERNAL_AUDIENCES and not (self.audience_rule or self.course_offering):
			frappe.throw(_("Audience {0} needs a course offering or an Audience Rule.").format(_(self.audience)))
		if self.course_offering and frappe.db.get_value("Student Group", self.course_offering, "oc_company") != self.company:
			frappe.throw(_("{0} is not a course offering of {1}.").format(frappe.bold(self.course_offering), frappe.bold(self.company)))
		if self.audience_rule and frappe.db.get_value("Audience Rule", self.audience_rule, "company") != self.company:
			frappe.throw(_("Audience Rule {0} is not of {1}.").format(frappe.bold(self.audience_rule), frappe.bold(self.company)))

	def offering_instructor(self):
		if not self.course_offering:
			return None
		return frappe.db.get_value(
			"Student Group Instructor", {"parent": self.course_offering, "parenttype": "Student Group"}, "instructor", order_by="idx"
		)

	def validate_locked(self):
		if self.is_new() or not frappe.db.exists("Feedback Response", {"campaign": self.name}):
			return
		changed = [self.meta.get_label(field) for field in LOCKED_ONCE_ANSWERED if self.has_value_changed(field)]
		if changed:
			frappe.throw(_("The campaign has responses; {0} can no longer change.").format(", ".join(changed)))
		closed_on = frappe.db.get_value("Feedback Campaign", self.name, "end_date")
		if getdate(closed_on) < getdate(today()) and getdate(self.end_date) >= getdate(today()):
			frappe.throw(_("A closed campaign with responses cannot reopen: answers added later would show by difference."))
