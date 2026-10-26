"""PR-02 Pilot structure: companies, institution profile, academic calendar, departments, programmes, regulation
with its rule records, and the trust's shared service agreements. All idempotent: see `records.upsert`."""

import frappe
from frappe import _

from campus.campus_platform.doctype.regulation.regulation import regulation_name
from campus.curriculum.rule_seed import RULES
from campus.examinations.seed import seed_regulation
from campus.setup.records import same_value, upsert

DEFAULT_CURRENCY = "INR"


def ensure_erpnext_fixtures(out):
	"""A site made without the setup wizard lacks the masters a Company needs (the Transit warehouse type, UOMs, customer and
	item groups, modes of payment): install ERPNext's own wizard fixtures, which skip whatever exists."""
	if frappe.db.exists("Warehouse Type", "Transit"):
		return
	from erpnext.setup.setup_wizard.operations.install_fixtures import install

	install("India")
	out.created["ERPNext fixtures"] += 1


def ensure_companies(profile, out):
	"""(trust, college) company names; the trust is None when the profile has none."""
	trust = profile.get("trust")
	trust_name = trust and ensure_company(out, trust["name"], trust["abbr"], is_group=1)
	college = profile["college"]
	return trust_name, ensure_company(out, college["name"], college["abbr"], parent=trust_name)


def ensure_company(out, name, abbr, is_group=0, parent=None):
	if frappe.db.exists("Company", name):
		return name
	was_importing, frappe.flags.in_import = (
		frappe.flags.in_import,
		False,
	)  # import mode skips the defaults a set-up site requires
	chart_flag = frappe.local.flags.ignore_chart_of_accounts
	frappe.local.flags.ignore_chart_of_accounts = False  # a college needs its chart of accounts for fees
	try:
		frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": name,
				"abbr": abbr,
				"default_currency": DEFAULT_CURRENCY,
				"country": "India",
				"is_group": is_group,
				"parent_company": parent,
			}
		).insert(ignore_permissions=True)
	finally:
		frappe.flags.in_import = was_importing
		frappe.local.flags.ignore_chart_of_accounts = chart_flag
	out.created["Company"] += 1
	return name


def ensure_calendar(profile, out):
	for year in profile.get("academic_years", []):
		upsert(
			out,
			"Academic Year",
			{"academic_year_name": year["name"]},
			{"year_start_date": year["start"], "year_end_date": year["end"]},
		)
		for term in year.get("terms", []):
			upsert(
				out,
				"Academic Term",
				{"academic_year": year["name"], "term_name": term["name"]},
				{"term_start_date": term["start"], "term_end_date": term["end"]},
			)


def ensure_holiday_list(profile, companies, out):
	"""A Holiday List over the profile's academic years (Sundays off), the default of every company of the kit. Education's
	attendance and leave validation read the default company's list, which is the trust when the site has one."""
	years = profile.get("academic_years") or []
	if not years:
		return
	abbr = frappe.db.get_value("Company", companies[-1], "abbr")
	name = f"{abbr} Holidays"
	if not frappe.db.exists("Holiday List", name):
		holidays = frappe.get_doc(
			{
				"doctype": "Holiday List",
				"holiday_list_name": name,
				"weekly_off": "Sunday",
				"from_date": min(y["start"] for y in years),
				"to_date": max(y["end"] for y in years),
			}
		)
		holidays.get_weekly_off_dates()
		holidays.insert(ignore_permissions=True)
		out.created["Holiday List"] += 1
	for company in companies:
		if not frappe.db.get_value("Company", company, "default_holiday_list"):
			frappe.db.set_value("Company", company, "default_holiday_list", name)
			out.updated["Company"] += 1


def site_default_company():
	"""The site's default company from either store (Global Defaults' single value or the DefaultValue row), or None."""
	return frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_default(
		"company"
	)


def ensure_default_company(company, out):
	"""Make `company` (the college) the site's default company when neither store has one, as ERPNext's setup wizard does:
	Education's attendance and leave validation read the default company's Holiday List, and without a default they take
	whichever company the database lists first. The college, not the trust, so that company_scope.before_validate stamps
	academic records with it. An existing default is never changed."""
	if site_default_company():
		return
	frappe.db.set_single_value("Global Defaults", "default_company", company)
	frappe.db.set_default("company", company)
	out.updated["Global Defaults"] += 1


def department_name(department, company):
	return f"{department} - {frappe.db.get_value('Company', company, 'abbr')}"


def ensure_departments(profile, college, out):
	for department in profile.get("departments", []):
		upsert(
			out,
			"Department",
			{"department_name": department, "company": college},
			{"parent_department": "All Departments"},
		)


def ensure_programmes(profile, college, out):
	"""Programme names are global in Education: one already owned by another company is refused, never taken over."""
	for programme in profile["programmes"]:
		owner = frappe.db.get_value("Program", programme["name"], "oc_company")
		if owner and owner != college:
			frappe.throw(
				_("Programme {0} belongs to {1}; give the programme of {2} a different name.").format(
					programme["name"], owner, college
				)
			)
		upsert(
			out,
			"Program",
			{"program_name": programme["name"]},
			{
				"oc_company": college,
				"program_abbreviation": programme.get("abbr"),
				"department": department_name(programme["department"], college),
				"oc_level": programme.get("level"),
				"oc_degree": programme.get("degree"),
				"oc_discipline": programme.get("discipline"),
				"oc_duration_years": programme.get("duration_years"),
				"oc_total_semesters": programme.get("total_semesters"),
				"oc_sanctioned_intake": programme.get("intake"),
			},
		)


def ensure_regulation(profile, college, out):
	"""The regulation (Effective, locked once saved) and, when absent, its credit, registration, attendance and exam
	rules. Exam rules come from `campus.examinations.seed`, keyed by the regulation code."""
	spec = profile.get("regulation")
	if not spec:
		return
	name = regulation_name(spec["code"], college)
	if not frappe.db.exists("Regulation", name):
		frappe.get_doc(
			{
				"doctype": "Regulation",
				"code": spec["code"],
				"company": college,
				"status": "Effective",
				"effective_from_year": spec["effective_from_year"],
				"programs": [{"program": program} for program in spec["programmes"]],
			}
		).insert(ignore_permissions=True)
		out.created["Regulation"] += 1
	for doctype, key in (
		("Curriculum Rule", "curriculum_rule"),
		("Registration Rule", "registration_rule"),
		("Attendance Rule", "attendance_rule"),
	):
		values = RULES[spec["code"]][key]
		existing = frappe.db.get_value(doctype, {"regulation": name}, list(values), as_dict=True)
		if not existing:
			frappe.get_doc({"doctype": doctype, "regulation": name, **values}).insert(ignore_permissions=True)
			out.created[doctype] += 1
		elif any(not same_value(existing[field], value) for field, value in values.items()):
			out.notes.append(
				f"{doctype} of {name} differs from the seed values; the regulation is Effective and was left as it is."
			)
	exam_rules_before = frappe.db.exists("Exam Rule Set", {"regulation": name})
	seed_regulation(name, spec["code"])
	if not exam_rules_before:
		out.created["Exam Rule Set"] += 1


def ensure_institution_profile(profile, college, employees, out):
	spec = profile["college"]
	people = {field: employees.get(user_key) for field, user_key in spec.get("leaders", {}).items()}
	upsert(
		out,
		"Institution Profile",
		{"company": college},
		{**{k: v for k, v in spec.get("institution", {}).items()}, **{k: v for k, v in people.items() if v}},
	)


def ensure_service_agreements(profile, trust, college, out):
	"""The trust provides each listed service to the college (a Shared Service Agreement per service)."""
	for service in profile.get("shared_services", []):
		filters = {"provider_company": trust, "service": service["service"]}
		name = frappe.db.exists("Shared Service Agreement", filters)
		if not name:
			frappe.get_doc(
				{
					"doctype": "Shared Service Agreement",
					**filters,
					"invoicing_company": trust,
					"from_date": service["from_date"],
					"members": [{"company": college}],
				}
			).insert(ignore_permissions=True)
			out.created["Shared Service Agreement"] += 1
		elif not frappe.db.exists("Shared Service Member", {"parent": name, "company": college}):
			agreement = frappe.get_doc("Shared Service Agreement", name)
			agreement.append("members", {"company": college})
			agreement.save(ignore_permissions=True)
			out.updated["Shared Service Agreement"] += 1
