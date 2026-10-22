"""PR-02 Pilot setup kit: one idempotent run that configures a fresh site for a college from a profile file.

    bench --site <site> execute campus.setup.pilot.setup_college --kwargs '{"profile": "sxcce"}'

Builds, in order: ERPNext's wizard fixtures if the site has none, trust and college companies, academic calendar, a holiday list, the site's default company (when unset), departments, programmes, the regulation with its
rule records (exam rules from `campus.examinations.seed`), student categories, quotas and seat matrices, fee
structures, the selling price list, approval policies, the shared service agreements, and one user per role with its company permission.
Re-running changes nothing: records are found by natural key and only differing values are updated (locked records
-- an Effective regulation, a submitted fee structure -- are never edited). Returns what was created and updated.

Run `bench --site <site> migrate` first: roles, positions and DocTypes come from the app install. The commit is left
to the caller (`bench execute` commits). See docs/usage/pilot-setup.md.
"""

import frappe
from frappe import _

from campus.campus_platform.positions import ensure_seed_positions
from campus.setup import admission, fees, people, policies, structure
from campus.setup.profile import load_profile
from campus.setup.records import Outcome


def setup_college(profile="sxcce", test_passwords=None):
	"""Configure the site for the college of `profile` (a profile name, or a profile dict). See the module docstring.

	`test_passwords`: None uses the fixed test password on developer-mode and demo sites only; True forces it and is
	refused elsewhere; False never stores a password (reset links are returned instead)."""
	profile = load_profile(profile)
	use_test_passwords = decide_passwords(test_passwords)
	missing = people.missing_roles(profile)
	if missing:
		frappe.throw(_("Roles missing on this site: {0}. Run bench migrate first.").format(", ".join(missing)))
	out = Outcome()
	result = {"reset_links": {}}
	ensure_seed_positions()
	structure.ensure_erpnext_fixtures(out)
	trust, college = structure.ensure_companies(profile, out)
	structure.ensure_calendar(profile, out)
	structure.ensure_holiday_list(profile, [c for c in (trust, college) if c], out)
	structure.ensure_default_company(college, out)
	structure.ensure_departments(profile, college, out)
	structure.ensure_programmes(profile, college, out)
	structure.ensure_regulation(profile, college, out)
	admission.ensure_admission(profile, college, out)
	fees.ensure_selling_defaults()
	fees.ensure_fees(profile, college, out)
	employees = people.ensure_people(profile, {"college": college, "trust": trust}, out, use_test_passwords, result)
	structure.ensure_institution_profile(profile, college, employees, out)
	if trust:
		structure.ensure_service_agreements(profile, trust, college, out)
	policies.ensure_policies(profile, out)
	return {**out.as_dict(), "profile": profile["name"], "college": college, **result}


TRUE_WORDS, FALSE_WORDS = ("1", "true", "yes"), ("0", "false", "no")


def parse_flag(value):
	"""None, a bool or a plain word like "true"/"no"; anything else is refused (a quoted "false" must not read as True)."""
	if value is None or isinstance(value, bool):
		return value
	word = str(value).strip().lower()
	if word in TRUE_WORDS:
		return True
	if word in FALSE_WORDS:
		return False
	frappe.throw(_("test_passwords must be true or false, not {0}.").format(frappe.as_json(value)))


def decide_passwords(test_passwords):
	test_passwords = parse_flag(test_passwords)
	allowed = people.test_passwords_allowed()
	if test_passwords and not allowed:
		frappe.throw(
			_("Test passwords are for developer-mode or demo sites only: turn on developer_mode or set campus_demo_site in the site config.")
		)
	return allowed if test_passwords is None else test_passwords
