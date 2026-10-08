"""M02-03 Body Meeting: a meeting of a Body. The notice goes out through the messaging bus no later than the
Governance Settings notice days before the date (or with an override reason); attendance starts from the members
in office on the meeting date; quorum follows the Body Type rule; resolutions need quorum and are numbered per
body and year."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, getdate, now_datetime, today

from campus.academic_governance import api, quorum
from campus.academic_governance.notice import notice_is_late
from campus.campus_messaging.api import send

NOTICE_EVENT = "body_meeting.notice"


class BodyMeeting(Document):
	def before_validate(self):
		self.company, self.body_type = frappe.db.get_value("Body", self.body, ["company", "body_type"])
		if not self.attendance:
			self.fill_attendance()

	def validate(self):
		saved = self.get_doc_before_save()
		if is_frozen(saved):
			self.keep_frozen_meeting(saved)
		else:
			self.follow_date_change(saved)
			self.validate_attendance()
			self.refresh_quorum()
		self.validate_resolutions(saved)

	def on_trash(self):
		if frappe.db.exists("Meeting Resolution", {"parent": self.name, "resolution_no": ["is", "set"]}):
			frappe.throw(_("A meeting with numbered resolutions cannot be deleted. Cancel it instead; the resolutions are kept as void."))

	def fill_attendance(self):
		for member in api.members_in_office(self.body, self.meeting_date):
			self.append(
				"attendance",
				{
					"category": member.category,
					"employee": member.employee,
					"external_member": member.external_member,
					"member_name": member.member_name,
					"present": 0,
				},
			)

	def follow_date_change(self, saved):
		"""Until someone is marked present the attendance is just the members in office, so a new date refreshes it."""
		if saved and self.has_value_changed("meeting_date") and not any(row.present for row in self.attendance):
			self.set("attendance", [])
			self.fill_attendance()

	def validate_attendance(self):
		keys = [quorum.member_key(row) for row in self.attendance]
		if len(keys) != len(set(keys)):
			frappe.throw(_("Each member can appear once in the attendance"))

	def refresh_quorum(self):
		in_office = [frappe._dict(m) for m in api.members_in_office(self.body, self.meeting_date)]
		percent, mandatory = api.quorum_rule(self.body_type)
		present = [quorum.member_key(row) for row in self.attendance if row.present]
		result = quorum.quorum_status(percent, mandatory, in_office, present)
		self.quorum_status = "Met" if result.met else "Not met"
		self.in_office_count, self.quorum_required, self.present_count = result.in_office, result.required, result.present
		self.quorum_note = (
			_("A member of each of these categories must attend: {0}").format(", ".join(map(_, result.missing_categories)))
			if result.missing_categories
			else ""
		)

	def keep_frozen_meeting(self, saved):
		"""A Held meeting, or one with numbered resolutions, keeps the date, attendance and quorum it was recorded with."""
		attendance = lambda doc: sorted((quorum.member_key(r), cint(r.present)) for r in doc.attendance)
		if getdate(self.meeting_date) != getdate(saved.meeting_date) or attendance(self) != attendance(saved):
			frappe.throw(_("The date and attendance of a held meeting, or one with resolutions, cannot change"))
		for field in ("quorum_status", "in_office_count", "quorum_required", "present_count", "quorum_note"):
			self.set(field, saved.get(field))

	def validate_resolutions(self, saved):
		old = {row.name: row for row in saved.resolutions} if saved else {}
		self.keep_numbered_rows(old)
		new = [row for row in self.resolutions if row.name not in old or not old[row.name].resolution_no]
		for row in new:
			row.resolution_no = row.serial = None  # numbers are the server's
		if new:
			self.validate_can_resolve()
			self.number_resolutions(new)
		if self.status == "Cancelled":
			for row in self.resolutions:
				row.void = 1

	def keep_numbered_rows(self, old):
		current = {row.name: row for row in self.resolutions}
		for name, saved_row in old.items():
			if not saved_row.resolution_no:
				continue
			row = current.get(name)
			if not row:
				frappe.throw(_("Resolution {0} cannot be removed. Cancel the meeting to void it.").format(saved_row.resolution_no))
			if (row.resolution_text, row.decision) != (saved_row.resolution_text, saved_row.decision):
				frappe.throw(_("Resolution {0} cannot be edited once numbered").format(saved_row.resolution_no))
			row.resolution_no, row.serial = saved_row.resolution_no, saved_row.serial

	def validate_can_resolve(self):
		if self.status == "Cancelled" or getdate(self.meeting_date) > getdate(today()):
			frappe.throw(_("Resolutions can only be recorded for a meeting that has taken place and was not cancelled"))
		if self.quorum_status != "Met":
			frappe.throw(_("Resolutions cannot be recorded: quorum is not met. {0}").format(self.quorum_note or ""))

	def number_resolutions(self, rows):
		year = getdate(self.meeting_date).year
		serial = last_serial(self.body, year)
		for row in rows:
			serial += 1
			row.serial = serial
			row.resolution_no = f"{self.body}/{year}/{serial:03d}"

	@frappe.whitelist()
	def send_notice(self, override_reason=None):
		"""Send the notice. Everything the rules depend on is re-read from the database under a lock; the posted copy is ignored."""
		self.check_permission("write")
		stored = frappe.db.get_value("Body Meeting", self.name, ["meeting_date", "status", "notice_sent_on"], for_update=True, as_dict=True)
		if stored.notice_sent_on:
			frappe.throw(_("The notice has already been sent"))
		if stored.status != "Scheduled" or getdate(stored.meeting_date) < getdate(today()):
			frappe.throw(_("A notice can only be sent for a scheduled meeting that has not happened yet"))
		days = frappe.db.get_single_value("Governance Settings", "notice_days")
		late = notice_is_late(stored.meeting_date, today(), cint(days))
		reason = (override_reason or "").strip()
		if late and not reason:
			frappe.throw(_("The notice must go out at least {0} days before the meeting. Give a reason to send it late.").format(days))
		meeting = frappe.get_doc("Body Meeting", self.name)
		row = frappe.qb.DocType("Meeting Attendance")
		attendance = frappe.qb.from_(row).select(row.employee, row.external_member).where(row.parent == self.name).for_update().run(as_dict=True)
		send(NOTICE_EVENT, meeting, [f"Employee:{r.employee}" if r.employee else f"External Member:{r.external_member}" for r in attendance])
		meeting.db_set({"notice_sent_on": now_datetime(), "notice_override_reason": reason if late else None})
		self.notice_sent_on, self.notice_override_reason = meeting.notice_sent_on, meeting.notice_override_reason


def is_frozen(saved):
	return bool(saved) and (saved.status == "Held" or any(row.resolution_no for row in saved.resolutions))


def last_serial(body, year):
	"""Highest resolution serial of the body in the year. Taken under a lock on the Body so that two meetings of
	one body saving at once cannot both read the same value (the read after the lock is a locking read)."""
	frappe.db.get_value("Body", body, "name", for_update=True)
	(row,) = frappe.db.sql(
		"""select max(r.serial) from `tabMeeting Resolution` r join `tabBody Meeting` m on r.parent = m.name
		where m.body = %s and m.meeting_date >= %s and m.meeting_date < %s for update""",
		(body, f"{year}-01-01", f"{year + 1}-01-01"),
	)
	return row[0] or 0
