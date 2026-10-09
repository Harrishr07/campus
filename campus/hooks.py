from campus.examinations.access import OFFERING_SCOPED, PORTAL_SCOPES

app_name = "campus"
app_title = "OneBook Campus"
app_publisher = "OneBook"
app_description = "Higher-education layer on Frappe Education and ERPNext"
app_email = "tools.zenpivot@gmail.com"
app_license = "gpl-3.0"

# Apps
# ------------------

required_apps = ["erpnext", "hrms", "education", "india_compliance", "frappe_whatsapp"]

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "campus",
# 		"logo": "/assets/campus/logo.png",
# 		"title": "OneBook Campus",
# 		"route": "/campus",
# 		"has_permission": "campus.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/campus/css/campus.css"
# app_include_js = "/assets/campus/js/campus.js"

# include js, css files in header of web template
# web_include_css = "/assets/campus/css/campus.css"
# web_include_js = "/assets/campus/js/campus.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "campus/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "campus/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
role_home_page = {"Student": "campus-portal", "Guardian": "campus-portal"}

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "campus.utils.jinja_methods",
# 	"filters": "campus.utils.jinja_filters"
# }

# Installation
# ------------

before_install = "campus.install.before_install"
before_migrate = "campus.install.before_migrate"
after_install = "campus.install.after_install"
after_migrate = "campus.install.after_migrate"

# Uninstallation
# ------------

# before_uninstall = "campus.uninstall.before_uninstall"
# after_uninstall = "campus.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "campus.utils.before_app_install"
# after_app_install = "campus.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "campus.utils.before_app_uninstall"
# after_app_uninstall = "campus.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "campus.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "campus.notifications.get_notification_config"

# Awesome Bar
# -----------
# Extra search results: list of dicts with label, description, route, index.
# route: ["List", "ToDo"], "/desk/docs/some/page", or "https://example.com"
# awesomebar_search = ["campus.search.awesomebar_results"]

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

_company_scope = "campus.campus_platform.company_scope"
doc_events = {
	dt: {"validate": f"{_company_scope}.validate_linked_companies"}
	for dt in [
		"Student Applicant",
		"Program",
		"Student Group",
		"Program Enrollment",
		"Course Schedule",
		"Student Admission",
		"Assessment Plan",
		"Fee Schedule",
		"Regulation",
	]
}
for _dt in [
	"Student",
	"Student Applicant",
	"Program",
	"Course",
	"Student Group",
	"Program Enrollment",
	"Course Schedule",
	"Instructor",
	"Room",
	"Student Admission",
	"Assessment Plan",
]:
	doc_events.setdefault(_dt, {})["before_validate"] = f"{_company_scope}.before_validate"

_regulation_rules = "campus.campus_platform.regulation_rules"
doc_events["Student"]["validate"] = f"{_regulation_rules}.validate_regulation_change"
_aadhaar = "campus.admissions.aadhaar.validate_aadhaar"
doc_events["Student"]["validate"] = [doc_events["Student"]["validate"], _aadhaar]
doc_events["Student Applicant"]["validate"] = [doc_events["Student Applicant"]["validate"], _aadhaar]
doc_events["Program Enrollment"]["validate"] = [
	doc_events["Program Enrollment"]["validate"],
	f"{_regulation_rules}.assign_regulation_on_enrollment",
]

doc_events["Student Applicant"]["validate"] += [
	"campus.admissions.allotment_import.set_allotment_key",
	"campus.admissions.documents.validate_applicant",
]
doc_events["Program Enrollment"]["on_submit"] = "campus.admissions.seat_matrix.refresh_cache_of"
doc_events["Program Enrollment"]["on_cancel"] = "campus.admissions.seat_matrix.refresh_cache_of"

doc_events["Lead"] = {
	"before_insert": "campus.admissions.enquiry.before_insert",
	"validate": "campus.admissions.enquiry.validate",
	"after_insert": "campus.admissions.enquiry.after_insert",
}
doc_events["User Permission"] = {
	"on_update": "campus.admissions.enquiry.user_permission_changed",
	"after_delete": "campus.admissions.enquiry.user_permission_changed",
}
doc_events["User"] = {"on_update": "campus.admissions.enquiry.user_changed"}

doc_events["Student Leave Application"] = {"before_submit": "campus.student_services.setup.require_certificate"}
doc_events["Fee Concession"] = {"on_cancel": "campus.campus_finance.concessions.clear_draft_tags"}
doc_events["Grievance Type"] = {"validate": "campus.student_services.grievances.validate_category"}
doc_events["Institution Profile"] = {"after_insert": "campus.student_services.onboarding.seed_template_for_profile"}
doc_events["Student"]["validate"].append("campus.student_services.mentors.set_class_advisor")
doc_events["Fee Category"] = {"validate": "campus.campus_finance.fee_heads.validate_fee_category"}
doc_events["Fee Structure"] = {"validate": "campus.campus_finance.fee_heads.validate_fee_structure"}
doc_events["Sales Invoice"] = {
	"before_validate": "campus.campus_finance.concessions.apply_to_invoice",
	"validate": "campus.campus_finance.fee_heads.validate_invoice_accounts",
	"before_submit": "campus.campus_finance.challan.assign_challan_no",
	"on_submit": "campus.campus_finance.concessions.mark_applied",
	"on_cancel": "campus.campus_finance.concessions.release",
}
doc_events["Payment Entry"] = {
	"validate": "campus.campus_finance.challan.set_payment_student",
	"before_submit": "campus.campus_finance.challan.assign_receipt_no",
	"on_cancel": [
		"campus.campus_finance.scholarships.refresh_after_voucher_cancel",
		"campus.campus_finance.fee_refunds.allow_payment_cancel",  # after ERPNext's own on_cancel, which sets the ignore list
	],
}
doc_events["Payment Entry"]["validate"] = [doc_events["Payment Entry"]["validate"], "campus.campus_finance.scholarships.block_amend"]
doc_events["Journal Entry"] = {
	"validate": "campus.campus_finance.scholarships.block_amend",
	"on_cancel": "campus.campus_finance.scholarships.refresh_after_voucher_cancel",
}
doc_events["Employee"] = {"validate": "campus.faculty.qualification.validate_employee", "on_update": "campus.faculty.setup.grant_employee_role"}
doc_events["Job Applicant"] = {"validate": "campus.faculty.qualification.validate_job_applicant"}
doc_events["Room"]["validate"] = "campus.examinations.exam_halls.validate_room"
doc_events["Leave Application"] = {"on_submit": "campus.faculty.substitution.on_leave_submit", "on_cancel": "campus.faculty.substitution.on_leave_cancel"}
doc_events["Employee Performance Feedback"] = {
	e: "campus.faculty.self_appraisal.block_feedback_on_self_appraisal" for e in ("validate", "before_submit", "before_cancel")
}
doc_events["Appraisal"] = {
	"before_validate": "campus.faculty.self_appraisal.before_validate",
	"before_submit": "campus.faculty.self_appraisal.before_submit",
}
doc_events["Purchase Invoice"] = {e: "campus.academic_governance.honorarium.refresh_claim" for e in ("on_submit", "on_cancel")}

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"campus.tasks.all"
# 	],
# 	"daily": [
# 		"campus.tasks.daily"
# 	],
# 	"hourly": [
# 		"campus.tasks.hourly"
# 	],
# 	"weekly": [
# 		"campus.tasks.weekly"
# 	],
# 	"monthly": [
# 		"campus.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "campus.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "campus.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
extend_doctype_class = {
	"Student": ["campus.admissions.aadhaar.AadhaarMixin"],
	"Student Applicant": ["campus.admissions.aadhaar.AadhaarMixin"],
	"Program Enrollment": ["campus.admissions.seat_matrix.EnrollmentSeatLockMixin"],
}
override_whitelisted_methods = {"frappe.client.get_password": "campus.admissions.aadhaar.get_password"}
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "campus.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "campus.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["campus.utils.before_request"]
# after_request = ["campus.utils.after_request"]

# Job Events
# ----------
# before_job = ["campus.utils.before_job"]
# after_job = ["campus.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"campus.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []


boot_session = "campus.campus_platform.pack_visibility.boot_session"

scheduler_events = {
	"daily": [
		"campus.campus_platform.positions.sync_all_roles",
		"campus.campus_finance.fines.daily_fine_run",
		"campus.admissions.documents.send_daily_reminders",
		"campus.admissions.enquiry_followup.create_due_todos",
		"campus.examinations.question_paper_files.sweep_plaintext",
	],
	"hourly": [
		"campus.campus_platform.approval_escalation.escalate_overdue",
		"campus.student_services.grievances.escalate_overdue",
		"campus.admissions.allotment_import.reconcile_finished_imports",
		"campus.examinations.cia.lock_due_schedules",
	],
	"weekly": [
		"campus.academic_governance.actions.notify_overdue",
	],
	"cron": {
		"*/15 * * * *": [
			"campus.campus_messaging.delivery.dispatch_due",
			"campus.campus_messaging.doctype.broadcast.broadcast.release_due",
			"campus.campus_messaging.doctype.circular.circular.publish_due",
		]
	},
}

# Delivery status webhooks (frappe_whatsapp updates WhatsApp Message) update the Message Log.
doc_events["Approval Request"] = {"on_update": "campus.campus_messaging.doctype.broadcast.broadcast.sync_approval_status"}
doc_events["WhatsApp Message"] = {"on_update": "campus.campus_messaging.delivery.sync_whatsapp_status"}

app_include_js = "/assets/campus/js/approvals.js"

doctype_js = {
	"Student Applicant": "public/js/student_applicant.js",
	"Student": "public/js/student.js",
	"Student Result": "public/js/student_result.js",
}

doctype_js["Employee"] = "public/js/employee_faculty.js"  # P2-T09 self-appraisal button
doctype_js["Appraisal"] = "public/js/appraisal_review.js"  # P2-T09 request HOD review
doctype_list_js = {"Student": "public/js/student_list.js"}

PORTAL_SCOPED = list(PORTAL_SCOPES)  # Student/Guardian roles are scoped to their own / linked students

permission_query_conditions = {
	"Circular": "campus.campus_messaging.circulars.get_permission_query_conditions",
	"Approval Request": "campus.campus_platform.approval_access.get_permission_query_conditions",
	"Lead": "campus.admissions.enquiry.get_permission_query_conditions",
	**{dt: "campus.examinations.access.portal_permission_query" for dt in PORTAL_SCOPED},
	**{dt: "campus.examinations.access.offering_permission_query" for dt in OFFERING_SCOPED},
	"Student Result": "campus.examinations.access.result_permission_query",
	**{dt: "campus.academic_governance.access.permission_query" for dt in ("Body Meeting", "Meeting Action Item")},
	"Hall Ticket": "campus.examinations.access.hall_ticket_permission_query",
	"Substitution": "campus.faculty.substitution_access.permission_query",
	"Question Paper": "campus.examinations.question_papers.permission_query",
	**{dt: "campus.examinations.question_papers.confidential_query" for dt in ("QP Setter Nomination", "QP Access Log")},
	"Question Bank Item": "campus.examinations.question_papers.bank_item_query",
}
has_permission = {
	"Circular": "campus.campus_messaging.circulars.has_permission",
	"Approval Request": "campus.campus_platform.approval_access.has_permission",
	"Lead": "campus.admissions.enquiry.has_permission",
	**{dt: "campus.examinations.access.portal_has_permission" for dt in PORTAL_SCOPED},
	**{dt: "campus.examinations.access.offering_has_permission" for dt in OFFERING_SCOPED},
	"Student Result": "campus.examinations.access.result_has_permission",
	**{dt: "campus.academic_governance.access.has_permission" for dt in ("Body Meeting", "Meeting Action Item")},
	"Hall Ticket": "campus.examinations.access.hall_ticket_has_permission",
	"Substitution": "campus.faculty.substitution_access.has_permission",
	"Question Paper": "campus.examinations.question_papers.has_permission",
	**{dt: "campus.examinations.question_papers.confidential_has_permission" for dt in ("QP Setter Nomination", "QP Access Log")},
	"Question Bank Item": "campus.examinations.question_papers.bank_item_has_permission",
	"File": "campus.examinations.question_papers.file_has_permission",
}
has_permission["Appraisal"] = "campus.faculty.self_appraisal.has_permission"
# Frappe lets a share grant what has_permission refuses: confidential exam documents are never shared.
doc_events["DocShare"] = {"validate": "campus.examinations.question_papers.block_confidential_share"}
_qp = "campus.examinations.question_papers"
doc_events["Version"] = {"before_insert": f"{_qp}.refuse_confidential_version"}
doc_events["Notification"] = {"validate": f"{_qp}.refuse_confidential_notification"}
doc_events["Webhook"] = {"validate": f"{_qp}.refuse_confidential_webhook"}
# P2-T18 valuation: the dummy-number map is Exam Confidential only; examiners reach only their own allocations.
_valuation = "campus.examinations.valuation_access"
permission_query_conditions["Dummy Number Map"] = f"{_valuation}.map_query"
has_permission["Dummy Number Map"] = f"{_valuation}.map_has_permission"
for _dt in ("Valuation Allocation", "Valuation Entry"):
	permission_query_conditions[_dt] = f"{_valuation}.examiner_query"
	has_permission[_dt] = f"{_valuation}.examiner_has_permission"
doc_events["DocShare"]["validate"] = [doc_events["DocShare"]["validate"], f"{_valuation}.block_map_share"]

# Dotted paths an Approval Policy may run as its "Call Service" final action: method(doc, request).
# Any app may add its own; nothing else can be called.
approval_final_actions = []

jinja = {
	"methods": [
		"campus.campus_platform.verification.oc_qr_block",
		"campus.curriculum.structure.curriculum_structure",
		"campus.campus_finance.challan.challan_details",
		"campus.faculty.cv.faculty_cv_sections",
	]
}

website_route_rules = [
	{"from_route": "/verify/<code>", "to_route": "verify"},
	{"from_route": "/campus-portal", "to_route": "campus_portal"},
	*(
		{"from_route": f"/campus-portal/{page}", "to_route": f"campus_portal/{page}"}
		for page in ("fees", "attendance", "results", "circulars", "certificates", "grievances", "leave", "valuation")
	),
]

# Message Logs are an audit trail: they must not block deleting the documents they refer to.
ignore_links_on_delete = ["Message Log"]
