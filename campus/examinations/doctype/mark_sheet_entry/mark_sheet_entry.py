"""M12-02 Mark Sheet Entry: CIA and ESE marks of the students of one course offering in an Exam Session.

Editable only while the session is in Marks Entry (who: campus.examinations.access).
"""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.examinations.courses import offering_course, student_limits


class MarkSheetEntry(Document):
	def before_validate(self):
		if self.is_new() and not self.marks and self.course_offering:
			members = frappe.get_all(
				"Student Group Student",
				{"parent": self.course_offering, "active": 1},
				pluck="student",
				order_by="group_roll_number, student",
			)
			for student in members:
				self.append("marks", {"student": student})

	def validate(self):
		session = frappe.db.get_value(
			"Exam Session", self.exam_session, ["company", "academic_term", "status"], as_dict=True
		)
		if session.status != "Marks Entry":
			frappe.throw(_("Marks can only be entered while the Exam Session is in Marks Entry."))
		self.validate_offering(session)
		course = offering_course(self.course_offering)
		if not course["course_type"]:
			frappe.throw(_("Internal Only courses are not graded by the Result Run."))
		self.validate_marks(course)

	def validate_offering(self, session):
		group = frappe.db.get_value(
			"Student Group", self.course_offering, ["group_based_on", "oc_company", "academic_term"], as_dict=True
		)
		if group.group_based_on != "Course" or group.oc_company != session.company or group.academic_term != session.academic_term:
			frappe.throw(_("The offering must be a course of the session's company and academic term."))
		if frappe.db.exists(
			"Mark Sheet Entry",
			{"exam_session": self.exam_session, "course_offering": self.course_offering, "name": ["!=", self.name]},
		):
			frappe.throw(_("A Mark Sheet Entry already exists for this session and offering."))

	def validate_marks(self, course):
		members = set(student_group_students(self.course_offering))
		seen = set()
		for row in self.marks:
			if row.student not in members or row.student in seen:
				frappe.throw(_("Row {0}: {1} is not a member of the offering, or is listed twice.").format(row.idx, row.student))
			seen.add(row.student)
			if row.absent:
				row.cia = row.ese = 0
				continue
			limits = student_limits(row.student, course)
			if not (0 <= row.cia <= limits["cia_max"] and 0 <= row.ese <= limits["ese_max"]):
				frappe.throw(
					_("Row {0}: CIA must lie within 0-{1} and ESE within 0-{2}.").format(
						row.idx, limits["cia_max"], limits["ese_max"]
					)
				)


def student_group_students(offering):
	return frappe.get_all("Student Group Student", {"parent": offering, "active": 1}, pluck="student")
