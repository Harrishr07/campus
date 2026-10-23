"""PR-03 Services around the students: class advisor and mentors with a mentoring note and a parent interaction, one scholarship
(sanctioned through the approval engine and disbursed), a placement drive with registrations, the Official Documents and
Degree Awarding Authorities that let completion work, and the AQAR cycle computed from the data above."""

import frappe
from frappe.utils import add_days, getdate, now_datetime

from campus.campus_platform.approvals import request_approval
from campus.iqac import compute
from campus.iqac.setup import FRAMEWORK, seed_framework
from campus.setup import people
from campus.setup.demo_data.batch import BATCH_YEAR, class_group_name
from campus.setup.records import upsert
from campus.student_services.api import allocate_mentors


def load(ctx):
	cohort = ctx.cohort
	cse = next(p for p in ctx.profile["programmes"] if p["abbr"] == "CSE")
	group = class_group_name(ctx, cse)
	students = [s for s in cohort.students(ctx, cse) if s]
	positions(ctx, group)
	mentoring(ctx, group, students)
	scholarship(ctx, students[0])
	authorities(ctx)
	placement(ctx, cohort)
	accreditation(ctx)


def position_user(ctx, key):
	return people.user_email(ctx.profile, key)


def positions(ctx, group):
	"""The class advisor advises the CSE 2025 class too; two faculty and the class advisor mentor it (so My students lists mentees for each)."""
	for code, key in (("CLASS-ADVISOR", "class_advisor"), ("MENTOR", "faculty"), ("MENTOR", "hod"), ("MENTOR", "class_advisor")):
		user = position_user(ctx, key)
		employee = frappe.db.get_value("Employee", {"user_id": user})
		upsert(
			ctx.out, "Position Holder", {"position": code, "scope_value": group, "user": user},
			{"employee": employee, "from_date": ctx.profile["people_defaults"]["positions_from"]},
		)


def mentoring(ctx, group, students):
	"""Mentors allocated through the HOD's allocation service; one non-confidential Counselling Note and one Parent Interaction."""
	if not frappe.db.get_value("Student", students[0], "oc_mentor"):
		allocate_mentors(student_group=group)
		ctx.out.updated["Student"] += len(students)
	student = students[1]
	mentor = frappe.db.get_value("Student", student, "oc_mentor")
	user = frappe.db.get_value("Employee", mentor, "user_id")
	if not frappe.db.exists("Counselling Note", {"student": student}):
		frappe.get_doc(
			{
				"doctype": "Counselling Note", "student": student, "note_date": add_days(getdate(), -40), "category": "Academic", "mentor": mentor,
				"author": user, "notes": "Discussed the semester 3 timetable and study plan. Student is regular and confident.",
				"is_confidential": 0, "follow_up_date": add_days(getdate(), 14),
			}
		).insert(ignore_permissions=True)
		ctx.out.created["Counselling Note"] += 1
	guardian = frappe.db.get_value("Student Guardian", {"parent": student}, "guardian")
	if guardian and not frappe.db.exists("Parent Interaction", {"student": student}):
		frappe.get_doc(
			{
				"doctype": "Parent Interaction", "student": student, "guardian": guardian, "interaction_date": add_days(getdate(), -30),
				"mode": "Phone", "recorded_by": user, "outcome": "Informed the parent about the CIA schedule and attendance so far.",
			}
		).insert(ignore_permissions=True)
		ctx.out.created["Parent Interaction"] += 1


def scholarship(ctx, student):
	"""An institutional merit scholarship, sent to the Principal for sanction through the approval engine (left pending: the
	presenter sanctions it from the approval inbox)."""
	abbr = frappe.db.get_value("Company", ctx.college, "abbr")
	account = f"Scholarship Expense - {abbr}"
	if not frappe.db.exists("Account", account):
		was_ignoring, frappe.flags.ignore_root_company_validation = frappe.flags.ignore_root_company_validation, True  # the college is a child of the trust
		try:
			frappe.get_doc(
				{
					"doctype": "Account", "account_name": "Scholarship Expense", "company": ctx.college, "root_type": "Expense",
					"parent_account": f"Indirect Expenses - {abbr}",
				}
			).insert(ignore_permissions=True)
		finally:
			frappe.flags.ignore_root_company_validation = was_ignoring
		ctx.out.created["Account"] += 1
	scheme = upsert(
		ctx.out, "Scholarship Scheme", {"scheme_name": "Institutional Merit Scholarship"},
		{"company": ctx.college, "scheme_type": "Institutional", "account": account, "amount_type": "Fixed", "amount": 20000},
	)
	if frappe.db.exists("Scholarship Application", {"student": student, "scheme": scheme}):
		return
	application = frappe.get_doc(
		{"doctype": "Scholarship Application", "student": student, "scheme": scheme, "academic_year": BATCH_YEAR}
	).insert(ignore_permissions=True)
	request_approval("Scholarship Application", application.name)  # waits for the Principal in the approval inbox
	ctx.out.created["Scholarship Application"] += 1


def authorities(ctx):
	"""An Affiliation Official Document and a Degree Awarding Authority per programme (the affiliating university awards the degree)."""
	university = ctx.profile["college"]["institution"]["affiliating_university"]
	for programme in ctx.profile["programmes"]:
		upsert(
			ctx.out, "Official Document", {"company": ctx.college, "reference_no": f"AU-AFF-{programme['abbr']}-2022"},
			{
				"program": programme["name"], "authority": "University", "document_type": "Affiliation",
				"valid_from": "2022-06-01", "valid_to": "2030-05-31",
			},
		)
		upsert(
			ctx.out, "Degree Awarding Authority", {"company": ctx.college, "program": programme["name"]},
			{
				"awarding_body": "Affiliating University", "authority_name": university, "document_type": "Affiliation",
				"document_authority": "University",
			},
		)


def placement(ctx, cohort):
	"""A campus drive by a synthetic recruiter, open to CSE and IT of the 2025 batch; eligible students register."""
	recruiter = upsert(ctx.out, "Recruiter", {"recruiter_name": "Example Software Services", "company": ctx.college})
	title = "Example Software Campus Drive 2026"
	drive = frappe.db.get_value("Placement Drive", {"drive_title": title, "company": ctx.college})
	if not drive:
		drive = frappe.get_doc(
			{
				"doctype": "Placement Drive", "drive_title": title, "company": ctx.college, "academic_year": "2026-27",
				"recruiter": recruiter, "drive_date": add_days(getdate(), 60), "status": "Open", "venue": "Seminar Hall",
				"registration_deadline": add_days(now_datetime(), 45), "min_cgpa": 6.5, "max_standing_arrears": 1,
				"allow_arrear_history": 1, "roles": [{"role_title": "Software Engineer", "openings": 10, "ctc": 450000}],
				"programs": [{"program": "B.E. CSE"}, {"program": "B.Tech IT"}], "batches": [{"batch": BATCH_YEAR}],
				"rounds": [{"round_no": 1, "round_name": "Aptitude"}, {"round_no": 2, "round_name": "Interview"}],
			}
		).insert(ignore_permissions=True).name
		ctx.out.created["Placement Drive"] += 1
	for programme in ctx.profile["programmes"]:
		if programme["abbr"] in ("CSE", "IT"):
			register_for_drive(ctx, drive, [s for s in cohort.students(ctx, programme) if s][:8])


def register_for_drive(ctx, drive, students):
	for student in students:
		if frappe.db.exists("Drive Registration", {"drive": drive, "student": student}):
			continue
		try:
			frappe.get_doc({"doctype": "Drive Registration", "drive": drive, "student": student}).insert(ignore_permissions=True)
			ctx.out.created["Drive Registration"] += 1
		except frappe.ValidationError:
			continue  # not eligible (CGPA or arrears): a student the drive turns away


def accreditation(ctx):
	seed_framework()
	cycle = upsert(
		ctx.out, "Accreditation Cycle", {"framework": FRAMEWORK, "company": ctx.college, "academic_year": BATCH_YEAR}
	)
	compute.compute_cycle(cycle)
