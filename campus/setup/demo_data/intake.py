"""PR-03 The 2026 intake: 18 enquiries (12 converted), 60 applicants across the six programmes, admitted and joined.

Every applicant goes through the college's own paths: a Lead converted by `convert_lead_to_applicant` (2 per programme),
an Applicant Upload file validated and imported by the bulk runner (4 per programme), or an applicant typed in (4 per
programme). Eligibility is evaluated, then Admit and Confirm Joining (L-02) are the Admission Officer's own calls. Seven
per programme join; the eighth is admitted and has not joined (a no-show so far), the ninth is Approved, the tenth is
still Applied.
"""

import csv
import io
from unittest.mock import patch

import frappe

from campus.admissions import allotment_import, applicant_upload, eligibility
from campus.admissions.api import admit, confirm_joining
from campus.admissions.enquiry import convert_lead_to_applicant
from campus.campus_platform import bulk
from campus.setup import fees
from campus.setup.records import upsert

QUALIFYING_EXAM = "HSC (Class XII)"
SUBJECTS = ("Mathematics", "Physics", "Chemistry")
MINIMUMS = {"OC": 50, "BC": 45, "MBC": 45, "SC": 40, "ST": 40}
APPLICANTS_PER_PROGRAMME = 10

# ordinal -> (quota, category, how it arrives, where it ends)
ORDINALS = {
	1: ("GQ", "OC", "lead", "Joined"), 2: ("GQ", "BC", "lead", "Joined"), 3: ("MQ", "OC", "upload", "Joined"),
	4: ("GQ", "MBC", "upload", "Joined"), 5: ("GQ", "SC", "upload", "Joined"), 6: ("GQ", "BC", "upload", "Joined"),
	7: ("MQ", "OC", "direct", "Joined"), 8: ("GQ", "OC", "direct", "Admitted"), 9: ("GQ", "MBC", "direct", "Approved"),
	10: ("GQ", "SC", "direct", "Applied"),
}  # fmt: skip
UPLOAD_HEADER = [
	"First Name", "Middle Name", "Last Name", "Date of Birth", "Gender", "Email", "Mobile", "Program", "Student Category",
	"Admission Quota", "Qualifying Exam", "Qualifying Register No",
]  # fmt: skip


class Applicant:
	"""One planned applicant: who, for which programme, and the path and end state its ordinal gives."""

	def __init__(self, person, programme, ordinal, number):
		self.person, self.programme, self.ordinal = person, programme["name"], ordinal
		self.quota, self.category, self.path, self.end = ORDINALS[ordinal]
		self.register_no = f"TNHSC26{number:06d}"
		self.marks = [(subject, 100, 62 + (number * (index + 3)) % 36) for index, subject in enumerate(SUBJECTS)]


def plan(ctx):
	applicants, number = [], 0
	for programme in ctx.profile["programmes"]:
		for ordinal in ORDINALS:
			number += 1
			person = ctx.people.make(f"applicant-{programme['abbr'].lower()}-{ordinal:02d}", 2008, 2007)
			applicants.append(Applicant(person, programme, ordinal, number))
	return applicants


def load(ctx):
	fees.ensure_selling_defaults()
	prepare_eligibility(ctx)
	applicants = plan(ctx)
	make_enquiries(ctx, applicants)
	upsert(ctx.out, "Admission Document Rule", {"document_type": "Transfer Certificate"}, {"mandatory": 1, "verification_needed": 0})
	upload_missing(ctx, [a for a in applicants if a.path == "upload"])
	for applicant in applicants:
		name = applicant_of(applicant.person.email) or make_applicant(ctx, applicant)
		complete(ctx, applicant, name)
		process(ctx, applicant, name)
	return applicants


def applicant_of(email):
	return frappe.db.get_value("Student Applicant", {"student_email_id": email})


def prepare_eligibility(ctx):
	"""An Eligibility Rule per programme (the pilot kit leaves the college to set them)."""
	for programme in ctx.profile["programmes"]:
		if frappe.db.exists("Eligibility Rule", {"program": programme["name"], "enabled": 1}):
			continue
		frappe.get_doc(
			{
				"doctype": "Eligibility Rule", "program": programme["name"], "enabled": 1, "qualifying_exam": QUALIFYING_EXAM,
				"required_subjects": "\n".join(SUBJECTS),
				"category_marks": [{"student_category": c, "min_percent": p} for c, p in MINIMUMS.items()],
			}
		).insert(ignore_permissions=True)
		ctx.out.created["Eligibility Rule"] += 1


# --- Arrival paths -----------------------------------------------------------------------------


def make_enquiries(ctx, applicants):
	"""A Lead per lead-path applicant and one more per programme that stays an enquiry (nobody converted it yet)."""
	for applicant in applicants:
		if applicant.path == "lead":
			ensure_lead(ctx, applicant.person, applicant.programme)
	for programme in ctx.profile["programmes"]:
		person = ctx.people.make(f"enquiry-{programme['abbr'].lower()}", 2008, 2007)
		ensure_lead(ctx, person, programme["name"])


def ensure_lead(ctx, person, programme):
	if frappe.db.exists("Lead", {"email_id": person.email}):
		return
	frappe.get_doc(
		{
			"doctype": "Lead", "first_name": person.first_name, "last_name": person.last_name, "email_id": person.email,
			"mobile_no": person.mobile, "company": ctx.college, "oc_program_interest": programme, "status": "Open",
		}
	).insert(ignore_permissions=True)
	ctx.out.created["Lead"] += 1


def make_applicant(ctx, applicant):
	"""The Student Applicant of a lead conversion or of a typed-in application (upload rows are made by `upload_missing`)."""
	person = applicant.person
	if applicant.path == "lead":
		lead = frappe.db.get_value("Lead", {"email_id": person.email})
		ctx.out.created["Student Applicant"] += 1
		return convert_lead_to_applicant(lead, ctx.year)
	doc = frappe.get_doc({"doctype": "Student Applicant", **applicant_values(ctx, applicant)}).insert(ignore_permissions=True)
	ctx.out.created["Student Applicant"] += 1
	return doc.name


def applicant_values(ctx, applicant):
	person = applicant.person
	return {
		"first_name": person.first_name, "last_name": person.last_name, "program": applicant.programme, "academic_year": ctx.year,
		"student_email_id": person.email, "student_mobile_number": person.mobile, "oc_company": ctx.college,
		"application_status": "Applied", "gender": person.gender, "date_of_birth": person.date_of_birth, "state": "Tamil Nadu",
		"student_category": applicant.category, "oc_admission_quota": applicant.quota, "oc_qualifying_exam": QUALIFYING_EXAM,
		"oc_qualifying_register_no": applicant.register_no,
	}  # fmt: skip


def upload_missing(ctx, applicants):
	"""The upload-path applicants not imported yet go in one Applicant Upload file: validated, then imported by the bulk runner."""
	missing = [a for a in applicants if not applicant_of(a.person.email)]
	if not missing:
		return
	rows = [UPLOAD_HEADER] + [upload_row(a) for a in missing]
	out = io.StringIO()
	csv.writer(out).writerows(rows)
	content = out.getvalue().encode()
	file = frappe.get_doc(
		{"doctype": "File", "file_name": f"sxcce-applicants-{ctx.seed}.csv", "content": content, "is_private": 1}
	).insert(ignore_permissions=True)
	upload = frappe.get_doc(
		{"doctype": "Applicant Upload", "company": ctx.college, "academic_year": ctx.year, "upload_file": file.file_url}
	).insert(ignore_permissions=True)
	file.db_set({"attached_to_doctype": "Applicant Upload", "attached_to_name": upload.name, "attached_to_field": "upload_file"})
	summary = applicant_upload.validate_upload(upload.name)
	if summary.get("Valid") != len(missing):
		problems = frappe.get_all("Applicant Upload Row", {"applicant_upload": upload.name, "status": ["!=", "Valid"]}, ["row_no", "status", "message"], limit=3)
		frappe.throw(f"Applicant Upload preview: expected {len(missing)} valid rows, got {summary}: {problems}")
	with patch.object(bulk, "enqueue_run"), patch.object(frappe.db, "commit"):  # run the queued import here, in this process
		run = applicant_upload.start_import(upload.name)
		bulk.process_bulk_run(run)
	ctx.out.created["Applicant Upload"] += 1
	ctx.out.created["Student Applicant"] += len(missing)


def upload_row(applicant):
	person = applicant.person
	return [
		person.first_name, "", person.last_name, person.date_of_birth, person.gender, person.email, person.mobile,
		applicant.programme, applicant.category, applicant.quota, QUALIFYING_EXAM, applicant.register_no,
	]


# --- Completion and the admission desk ---------------------------------------------------------


def complete(ctx, applicant, name):
	"""Fill what a lead conversion or a file does not carry (marks, documents, status) for an applicant who goes beyond Applied."""
	if applicant.end == "Applied":
		return
	doc = frappe.get_doc("Student Applicant", name)
	if doc.application_status != "Applied":
		return
	values = applicant_values(ctx, applicant)
	doc.update({k: v for k, v in values.items() if k != "application_status"})
	doc.set("oc_qualifying_marks", [{"subject": s, "max_marks": m, "obtained_marks": o} for s, m, o in applicant.marks])
	doc.set("oc_documents", [{"document_type": "Transfer Certificate", "status": "Submitted"}])
	doc.application_status = "Approved"
	doc.save(ignore_permissions=True)
	if not eligibility.evaluate(name)["eligible"]:
		frappe.throw(f"Demo applicant {name} should be eligible.")


def process(ctx, applicant, name):
	if applicant.end in ("Applied", "Approved"):
		return
	status = frappe.db.get_value("Student Applicant", name, "application_status")
	if status == "Approved":
		admit(name)
		ctx.out.created["Student"] += 1
	if applicant.end == "Joined" and frappe.db.get_value("Student", {"student_applicant": name}, "oc_academic_status") == "Admitted":
		confirm_joining(name)
		ctx.out.created["Program Enrollment"] += 1
