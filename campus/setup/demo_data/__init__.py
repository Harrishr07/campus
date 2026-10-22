"""PR-03 SXCCE synthetic demo dataset: one command loads a realistic, fully synthetic college on a site the PR-02 pilot
setup kit already configured.

    bench --site <site> execute campus.setup.demo_data.load --kwargs '{"profile": "sxcce", "seed": 2026}'

The same seed gives the same people and marks; running it again creates nothing new (every record is found by its natural
key first). Refuses to run unless the site is in developer mode or has `campus_demo_site` in its site config (the logins it
creates carry the profile's published test password). All data is generated: names from a seeded generator, phone
numbers that start with 0 (never dialable), e-mail addresses at the profile's example domain, Aadhaar numbers never.
Records go through the services a college uses (enquiry conversion, Applicant Upload, Admit and Confirm Joining,
legacy-style import of the 2025 batch, course registration, Mark Sheet Entry and the Result Run, Payment Entry, the
approval engine); see docs/usage/demo-data.md.
"""

import time

import frappe
from frappe import _

from campus.setup import people as pilot_people
from campus.setup.demo_data.names import People
from campus.setup.profile import load_profile
from campus.setup.records import Outcome

STEPS = ("staff", "intake", "fees", "curriculum", "batch", "term", "services")


class Context:
	"""What every step shares: the profile, the seed, the college, the year of the intake and the outcome being counted."""

	def __init__(self, profile, seed):
		self.profile, self.seed = profile, seed
		self.college = profile["college"]["name"]
		self.year = profile["seats"]["academic_year"]
		self.out = Outcome()
		self.people = People(seed, profile["user_domain"])
		self.timings = {}


def load(profile="sxcce", seed=2026, steps=None):
	"""Load the dataset of `profile` for `seed`; returns {created, updated, notes, seconds}. `steps` limits the run to some of STEPS."""
	if not pilot_people.test_passwords_allowed():
		frappe.throw(_("The demo data is for developer-mode or demo sites only: turn on developer_mode or set campus_demo_site in the site config."))
	ctx = Context(load_profile(profile), int(seed))
	if not frappe.db.exists("Company", ctx.college):
		frappe.throw(_("Run the pilot setup kit first: company {0} does not exist (campus.setup.pilot.setup_college).").format(ctx.college))
	run_steps(ctx, steps or STEPS)
	return {**ctx.out.as_dict(), "seconds": ctx.timings}


def run_steps(ctx, steps):
	from campus.setup.demo_data import batch, curriculum, fees, intake, services, staff, term

	modules = {
		"staff": staff, "intake": intake, "fees": fees, "curriculum": curriculum, "batch": batch, "term": term, "services": services,
	}
	was_importing, frappe.flags.in_import = frappe.flags.in_import, False  # import mode would skip DocType defaults
	frappe.set_user("Administrator")
	try:
		for step in steps:
			started = time.time()
			modules[step].load(ctx)
			ctx.timings[step] = round(time.time() - started)
	finally:
		frappe.flags.in_import = was_importing
