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
		self.validate_attendance()
		self.refresh_quorum()
		if self.resolutions and self.quorum_status != "Met":
			frappe.throw(_("Resolutions cannot be recorded: quorum is not met. {0}").format(self.quorum_note or ""))
		self.number_resolutions()

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

	def number_resolutions(self):
		new = [row for row in self.resolutions if not row.resolution_no]
		year = getdate(self.meeting_date).year
		if any(row.resolution_no and not row.resolution_no.startswith(f"{self.body}/{year}/") for row in self.resolutions):
			frappe.throw(_("The meeting date cannot move to another year once resolutions are numbered"))
		if not new:
			return
		serial = last_serial(self.body, year)
		for row in new:
			serial += 1
			row.serial = serial
			row.resolution_no = f"{self.body}/{year}/{serial:03d}"

	@frappe.whitelist()
	def send_notice(self, override_reason=None):
		self.check_permission("write")
		if self.notice_sent_on:
			frappe.throw(_("The notice has already been sent"))
		if self.status != "Scheduled" or getdate(self.meeting_date) < getdate(today()):
			frappe.throw(_("A notice can only be sent for a scheduled meeting that has not happened yet"))
		days = frappe.db.get_single_value("Governance Settings", "notice_days")
		late = notice_is_late(self.meeting_date, today(), cint(days))
		if late and not override_reason:
			frappe.throw(_("The notice must go out at least {0} days before the meeting. Give a reason to send it late.").format(days))
		self.db_set({"notice_sent_on": now_datetime(), "notice_override_reason": override_reason if late else None})
		members = [f"Employee:{row.employee}" if row.employee else f"External Member:{row.external_member}" for row in self.attendance]
		send(NOTICE_EVENT, self, members)


def last_serial(body, year):
	"""Highest resolution serial of the body in the year. Taken under a lock on the Body so that two meetings of
	one body saving at once cannot both read the same value (the read after the lock is a locking read)."""
	frappe.db.get_value("Body", body, "name", for_update=True)
	(row,) = frappe.db.sql(
		"""select max(r.serial) from `tabMeeting Resolution` r join `tabBody Meeting` m on r.parent = m.name
		where m.body = %s and year(m.meeting_date) = %s for update""",
		(body, year),
	)
	return row[0] or 0
