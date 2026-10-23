"""M05-03 Rejoin Application: a student returns from an approved Break of Study.

The student joins the cohort now where they left off (coordinator ruling, fix round 1): the cohort admitted in
the rejoin year less the years completed when the break started (withdrawal_rules.rejoin_cohort_year). Its batch
becomes the student's batch, and its regulation (campus_platform resolve_regulation for that batch) the student's
regulation, through the P1-T05 regulation history. The rejoin date falls in the rejoin academic year. The
regulations and batches are recomputed at submit, and a mismatch with the saved values is refused.

Bridge courses listed here are registered, kind Bridge, once offered in a term; until then they stay pending
(student_services.api.pending_bridge_courses). One rejoin per break. Approval runs through the approval engine
(seeded policy: HOD recommendation, then Principal approval); with no policy it is never submitted (fail
closed). Final approval submits it, which changes the regulation when it differs from the student's current one
and moves the student back to the lifecycle status from before the break, from the rejoin date (M05-09). A rejoin
after a break is not a readmission (Readmitted follows a discontinuation or withdrawal). A rejoin is not
cancelled: the Dean Academics corrects a regulation with Change Regulation.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.permissions import has_user_permission
from frappe.utils import getdate

from campus.campus_platform.api import ApprovableDocument, apply_regulation_change, get_regulation, resolve_regulation
from campus.student_services import lifecycle, student_records, withdrawal_rules
from campus.student_services.lifecycle_rules import migrated_status

DOCTYPE, BREAK = "Rejoin Application", "Break of Study"
PLACEMENT_FIELDS = ("from_regulation", "to_regulation", "from_batch", "to_batch")


class RejoinApplication(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		study_break = frappe.get_doc(BREAK, self.break_of_study)
		if study_break.docstatus != 1:
			frappe.throw(_("Break of Study {0} is not approved.").format(frappe.bold(study_break.name)))
		self.set_context(study_break)
		self.check_rejoin_date(study_break)
		if self.docstatus == 0:  # the approved values stand; before_submit re-checks them
			self.update(self.placement(study_break))
		if self.other_rejoins():
			frappe.throw(_("Break of Study {0} already has a rejoin.").format(frappe.bold(self.break_of_study)))
		self.check_bridge_courses()

	def before_submit(self):
		super().before_submit()
		student_records.require_policy(self)
		study_break = frappe.get_doc(BREAK, self.break_of_study, for_update=True)  # one rejoin submit per break
		if self.other_rejoins(lock=True):
			frappe.throw(_("Break of Study {0} already has a rejoin.").format(frappe.bold(self.break_of_study)))
		now = self.placement(study_break)
		if any(now[field] != self.get(field) for field in PLACEMENT_FIELDS):
			frappe.throw(
				_("The regulation or batch of this rejoin has changed since it was saved: return the approval and restart it (save, then request approval again).")
			)

	def on_submit(self):
		if self.to_regulation != get_regulation(self.student):
			apply_regulation_change(
				self.student,
				self.to_regulation,
				_("Rejoin {0} after break of study {1}").format(self.name, self.break_of_study),
				", ".join(row.course for row in self.bridge_courses) or None,
			)
		frappe.db.set_value("Student", self.student, "oc_batch", self.to_batch)
		# a break from before L-01 may keep an old academic status (Long Absent, Detained): map it
		status = migrated_status(frappe.db.get_value(BREAK, self.break_of_study, "previous_status"))
		reason = _("Rejoined after break of study {0}").format(self.break_of_study)
		lifecycle.transition(self.student, status, self.rejoin_date, reason, self)

	def before_cancel(self):
		frappe.throw(_("A rejoin cannot be cancelled; the Dean Academics corrects the regulation with Change Regulation."))

	def set_context(self, study_break):
		student = frappe.get_doc("Student", study_break.student)
		if not has_user_permission(student):  # Company User Permissions
			frappe.throw(_("You are not permitted to act for {0}.").format(frappe.bold(student.name)), frappe.PermissionError)
		self.student, self.student_name = student.name, student.student_name
		self.company, self.program, self.department = study_break.company, study_break.program, study_break.department

	def check_rejoin_date(self, study_break):
		start, end = frappe.db.get_value("Academic Year", self.academic_year, ["year_start_date", "year_end_date"])
		if not getdate(start) <= getdate(self.rejoin_date) <= getdate(end):
			frappe.throw(_("The rejoin date must fall in the academic year {0}.").format(frappe.bold(self.academic_year)))
		if getdate(self.rejoin_date) < getdate(study_break.from_date):
			frappe.throw(_("The rejoin date cannot be before the break starts ({0}).").format(frappe.format(study_break.from_date, "Date")))

	def placement(self, study_break):
		"""{from_regulation, to_regulation, from_batch, to_batch} computed from the records now."""
		from_batch = frappe.db.get_value("Student", self.student, "oc_batch")
		if not from_batch:
			frappe.throw(_("{0} has no batch (admission year).").format(frappe.bold(self.student)))
		break_year = student_records.academic_year_of(study_break.from_date)
		if not break_year:
			frappe.throw(_("No Academic Year holds the start of the break ({0}).").format(frappe.format(study_break.from_date, "Date")))
		batch_start = year_start(from_batch)
		cohort = withdrawal_rules.rejoin_cohort_year(
			batch_start.year, getdate(break_year.year_start_date).year, year_start(self.academic_year).year
		)
		if cohort is None:
			frappe.throw(_("The break starts before the admission of {0}.").format(frappe.bold(self.student)))
		to_batch = student_records.cohort_academic_year(from_batch, batch_start, cohort)
		to_regulation = resolve_regulation(self.company, self.program, to_batch)
		if not to_regulation:
			frappe.throw(_("No Effective regulation covers {0} for the {1} batch.").format(frappe.bold(self.program), frappe.bold(to_batch)))
		return {
			"from_regulation": get_regulation(self.student), "to_regulation": to_regulation,
			"from_batch": from_batch, "to_batch": to_batch,
		}  # fmt: skip

	def check_bridge_courses(self):
		seen = set()
		for row in self.bridge_courses:
			if row.course in seen:
				frappe.throw(_("Row {0}: {1} is listed twice.").format(row.idx, frappe.bold(row.course)))
			seen.add(row.course)

	def other_rejoins(self, lock=False):
		"""Other live (draft or submitted) rejoins of the break (a locking read of submitted ones when `lock`)."""
		other = frappe.qb.DocType(DOCTYPE)
		query = (
			frappe.qb.from_(other)
			.select(other.name)
			.where((other.break_of_study == self.break_of_study) & (other.name != (self.name or "")))
		)
		query = query.where(other.docstatus == 1).for_update() if lock else query.where(other.docstatus < 2)
		return query.run()


def year_start(academic_year):
	return getdate(frappe.db.get_value("Academic Year", academic_year, "year_start_date"))
