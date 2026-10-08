"""M07-04 Appraisal Review: the HOD's review of an HRMS Appraisal made from a faculty self-appraisal.

The HRMS Appraisal stays the appraisal; this document only carries it through the approval engine. The department's HOD
approves; the requester and owner never can (engine), nor the appraisee. Final approval submits the Appraisal, after
which nobody can change it. The Appraisal cannot be submitted any other way (campus.faculty.self_appraisal).
"""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.campus_platform.api import ApprovableDocument
from campus.faculty import self_appraisal


class AppraisalReview(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		self_appraisal.check_reviewable(self)

	def before_submit(self):
		self_appraisal.check_not_appraisee(self)
		super().before_submit()

	def on_submit(self):
		self_appraisal.submit_appraisal(self)
