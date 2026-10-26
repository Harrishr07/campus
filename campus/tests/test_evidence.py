"""M01-01 (P3-T04) Evidence registry, filled/missing evidence slots per cycle and the public /disclosure pages."""

import frappe

from campus.iqac import api, evidence
from campus.iqac.setup import FRAMEWORK
from campus.tests.factories import make_user
from campus.tests.test_iqac import COORDINATOR, FACULTY_USER, IqacFixture
from campus.tests.test_regulation import make_year, year_name
from campus.tests.test_results import COLLEGE

NODE = f"{FRAMEWORK}-2.6.3"
OTHER_NODE = f"{FRAMEWORK}-2.1.1"
SLOT, URL_SLOT = "Data Template", "Link to the relevant document"
OWNER = "evidence-owner@example.com"


class EvidenceFixture(IqacFixture):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_user(OWNER, [COLLEGE])
		frappe.get_doc("User", OWNER).add_roles("IQAC Criterion Owner")
		cls.files = []

	@classmethod
	def tearDownClass(cls):
		for name in cls.files:
			if frappe.db.exists("File", name):
				frappe.delete_doc("File", name, force=True)
		super().tearDownClass()

	def make_file(self, private=False, content="x"):
		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"ev-{frappe.generate_hash(length=8)}.txt",
				"content": content,
				"is_private": int(private),
			}
		).insert()
		self.files.append(doc.name)
		return doc.file_url

	def make(self, title="Minutes 2022", **values):
		doc = {
			"doctype": "Evidence",
			"title": title,
			"evidence_type": "IQAC Minutes",
			"company": COLLEGE,
			"academic_year": year_name("2022"),
			"kind": "File",
		}
		if "url" not in values and "source_field" not in values:
			doc["file"] = self.make_file()
		return frappe.get_doc({**doc, **values})


class TestEvidenceRecord(EvidenceFixture):
	def test_the_slug_is_the_name_unique_and_stable(self):
		first, second = self.make("IQAC Minutes 2022").insert(), self.make("IQAC Minutes 2022").insert()
		self.assertEqual(first.name, first.slug)
		self.assertEqual(first.slug, "iqac-minutes-2022")
		self.assertNotEqual(first.slug, second.slug)
		self.assertEqual(first.public_url, "/disclosure/iqac-minutes-2022")
		first.title = "Renamed"
		first.save()
		self.assertEqual(frappe.db.get_value("Evidence", first.name, "slug"), "iqac-minutes-2022")

	def test_a_file_evidence_needs_its_file_and_a_url_evidence_a_web_address(self):
		with self.assertRaises(frappe.ValidationError):
			self.make(file=None).insert()
		with self.assertRaises(frappe.ValidationError):
			self.make(kind="URL", url="javascript:alert(1)").insert()
		self.assertTrue(self.make(kind="URL", url="https://example.com/aqar.pdf").insert().name)

	def test_a_public_evidence_must_have_a_public_file(self):
		with self.assertRaisesRegex(frappe.ValidationError, "private"):
			self.make(file=self.make_file(private=True), is_public=1).insert()
		self.assertTrue(self.make(file=self.make_file(), is_public=1).insert().is_public)

	def test_only_iqac_staff_can_make_an_evidence_public(self):
		frappe.set_user(OWNER)
		with self.assertRaises(frappe.PermissionError):
			self.make(is_public=1).insert()
		self.assertFalse(self.make().insert().is_public)
		frappe.set_user(COORDINATOR)
		self.assertTrue(self.make(is_public=1).insert().is_public)

	def test_a_node_row_names_a_slot_of_that_node_of_the_same_kind(self):
		with self.assertRaisesRegex(frappe.ValidationError, "slot"):
			self.make(nodes=[{"node": NODE, "slot_name": "No such slot"}]).insert()
		with self.assertRaisesRegex(frappe.ValidationError, "URL"):  # a file cannot fill a URL slot
			self.make(nodes=[{"node": NODE, "slot_name": URL_SLOT}]).insert()
		self.assertTrue(self.make(nodes=[{"node": NODE, "slot_name": SLOT}]).insert().name)


class TestSourceLink(EvidenceFixture):
	def setUp(self):
		super().setUp()
		self.old = self.make_file()
		frappe.db.set_value("Company", COLLEGE, "company_logo", self.old)
		frappe.get_doc("Campus Settings").update(
			{"evidence_sources": [{"document_type": "Company", "file_field": "company_logo"}]}
		).save()

	def attach(self, **values):
		return api.attach_as_evidence(
			"Company", COLLEGE, "College logo", "Other", year_name("2022"), **values
		)

	def test_attach_as_evidence_links_the_source_record_and_its_file_field(self):
		name = self.attach()
		doc = frappe.get_doc("Evidence", name)
		self.assertEqual(
			(doc.source_doctype, doc.source_name, doc.source_field), ("Company", COLLEGE, "company_logo")
		)
		self.assertEqual((doc.company, doc.kind), (COLLEGE, "File"))
		self.assertEqual(evidence.current_file(doc), self.old)

	def test_replacing_the_source_file_keeps_the_evidence_and_its_public_url(self):
		name = self.attach(is_public=1)
		url = frappe.db.get_value("Evidence", name, "public_url")
		new = self.make_file(content="newer")
		frappe.db.set_value("Company", COLLEGE, "company_logo", new)
		self.assertEqual(frappe.db.get_value("Evidence", name, "public_url"), url)
		self.assertEqual(evidence.public_target(name), new)

	def test_a_source_file_turned_private_or_removed_is_no_longer_served(self):
		name = self.attach(is_public=1)
		frappe.db.set_value("Company", COLLEGE, "company_logo", self.make_file(private=True))
		self.assertIsNone(evidence.public_target(name))
		frappe.db.set_value("Company", COLLEGE, "company_logo", None)
		self.assertIsNone(evidence.public_target(name))

	def test_a_doctype_outside_the_campus_settings_list_is_refused(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Campus Settings"):
			api.attach_as_evidence("Department", "x", "t", "Other", year_name("2022"))

	def test_the_caller_needs_read_access_to_the_source(self):
		frappe.set_user(FACULTY_USER)
		with self.assertRaises(frappe.PermissionError):
			self.attach()

	def test_an_evidence_keeps_saving_after_its_source_type_is_delisted(self):
		doc = frappe.get_doc("Evidence", self.attach())
		frappe.get_doc("Campus Settings").update({"evidence_sources": []}).save()
		doc.title = "College logo (renamed)"
		doc.save()  # the source fields did not change, so the list is not checked again
		doc.source_name = "Iqac Other College"
		with self.assertRaisesRegex(frappe.ValidationError, "Campus Settings"):
			doc.save()


class TestFixRound2(EvidenceFixture):
	def test_a_source_field_without_a_source_doctype_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.make(source_field="company_logo", file=None).insert()

	def test_an_evidence_without_a_source_counts_only_for_a_college_the_user_may_see(self):
		frappe.set_user(OWNER)  # holds the Company permission for COLLEGE only
		with self.assertRaises(frappe.PermissionError):
			self.make("Other college minutes", company="Iqac Other College").insert()
		self.assertTrue(self.make("Own college minutes").insert().name)


class TestPublicServing(EvidenceFixture):
	def test_only_a_public_evidence_with_a_public_file_has_a_target(self):
		public_url = self.make_file()
		pub = self.make("Public one", file=public_url, is_public=1).insert()
		hidden = self.make("Hidden one").insert()
		self.assertEqual(evidence.public_target(pub.name), public_url)
		self.assertIsNone(evidence.public_target(hidden.name))
		self.assertIsNone(evidence.public_target("no-such-slug"))

	def test_a_file_made_private_after_publishing_is_never_served(self):
		pub = self.make("Went private", is_public=1).insert()
		frappe.db.set_value("File", {"file_url": pub.file}, "is_private", 1)
		self.assertIsNone(evidence.public_target(pub.name))

	def test_a_private_looking_or_traversing_path_is_never_served(self):
		pub = self.make("Path games", is_public=1).insert()
		for bad in (
			"/private/files/x.pdf",
			"/files/../private/files/x.pdf",
			"/app/secret",
			"javascript:alert(1)",
		):
			frappe.db.set_value("Evidence", pub.name, "file", bad)
			self.assertIsNone(evidence.public_target(pub.name), bad)

	def test_a_public_url_evidence_redirects_to_its_address(self):
		pub = self.make("External", kind="URL", url="https://example.com/a.pdf", is_public=1).insert()
		self.assertEqual(evidence.public_target(pub.name), "https://example.com/a.pdf")

	def test_the_page_redirects_a_public_slug_and_gives_the_same_404_for_unknown_and_non_public(self):
		from campus.www import disclosure

		pub = self.make("Redirected", is_public=1).insert()
		hidden = self.make("Not public").insert()
		frappe.form_dict.slug = pub.name
		with self.assertRaises(frappe.Redirect) as raised:
			disclosure.get_context(frappe._dict())
		self.assertEqual(raised.exception.http_status_code, 302)
		self.assertEqual(frappe.local.flags.redirect_location, pub.file)
		from frappe.website.page_renderers.redirect_page import RedirectPage

		self.assertEqual(
			RedirectPage("disclosure", raised.exception.http_status_code).render().status_code, 302
		)
		for slug in (hidden.name, "no-such-slug"):
			frappe.form_dict.slug = slug
			with self.assertRaises(frappe.PageDoesNotExistError):
				disclosure.get_context(frappe._dict())
		frappe.form_dict.pop("slug", None)

	def test_the_index_groups_public_rows_by_year_and_type_and_escapes_titles(self):
		from campus.www import disclosure

		self.make("<script>alert(1)</script> minutes", is_public=1).insert()
		self.make("Calendar", evidence_type="Academic Calendar", is_public=1).insert()
		self.make("Secret minutes").insert()
		frappe.form_dict.pop("slug", None)
		context = frappe._dict()
		disclosure.get_context(context)
		years = {year: dict(types) for _company, year, types in context.groups}
		titles = [row.title for types in years.values() for rows in types.values() for row in rows]
		self.assertIn("Calendar", titles)
		self.assertNotIn("Secret minutes", titles)
		self.assertEqual(set(years[year_name("2022")]), {"IQAC Minutes", "Academic Calendar"})
		# Frappe strips tags from Data on save; the template must escape whatever it is given all the same
		hostile = frappe._dict(
			title="<script>alert(1)</script>", slug='x"><b>', description="<img src=x onerror=1>"
		)
		html = frappe.render_template(
			disclosure.GROUPS_TEMPLATE, {"groups": [("<u>Co</u>", "<i>2022</i>", [("Other", [hostile])])]}
		)
		for raw in ("<script>", "<img", "<b>", "<i>", "<u>"):
			self.assertNotIn(raw, html)
		self.assertIn("&lt;script&gt;", html)


class TestSlotStatus(EvidenceFixture):
	def rows(self, node=NODE, cycle=None):
		return {row.slot_name: row for row in evidence.slot_status((cycle or self.cycle).name, node)}

	def test_every_slot_of_the_node_is_listed_missing_until_evidence_fills_it(self):
		rows = self.rows()
		self.assertEqual(set(rows), {SLOT, "Any additional information", URL_SLOT})
		self.assertFalse(any(row.filled for row in rows.values()))

	def test_evidence_of_the_cycles_college_and_year_fills_the_slot_it_names(self):
		doc = self.make(nodes=[{"node": NODE, "slot_name": SLOT}]).insert()
		rows = self.rows()
		self.assertTrue(rows[SLOT].filled)
		self.assertEqual(rows[SLOT].evidence, [doc.name])
		self.assertFalse(rows["Any additional information"].filled)
		self.assertFalse(self.rows(OTHER_NODE)[SLOT].filled)

	def test_another_year_or_a_url_for_a_file_slot_does_not_fill(self):
		make_year("2021")
		self.make(academic_year=year_name("2021"), nodes=[{"node": NODE, "slot_name": SLOT}]).insert()
		self.assertFalse(self.rows()[SLOT].filled)

	def test_a_url_slot_is_filled_by_a_url_evidence(self):
		self.make(
			kind="URL", url="https://example.com/x", nodes=[{"node": NODE, "slot_name": URL_SLOT}]
		).insert()
		self.assertTrue(self.rows()[URL_SLOT].filled)

	def test_a_slot_goes_back_to_missing_when_its_source_file_is_removed(self):
		frappe.db.set_value("Company", COLLEGE, "company_logo", self.make_file())
		frappe.get_doc("Campus Settings").update(
			{"evidence_sources": [{"document_type": "Company", "file_field": "company_logo"}]}
		).save()
		self.make(
			file=None,
			source_doctype="Company",
			source_name=COLLEGE,
			source_field="company_logo",
			nodes=[{"node": NODE, "slot_name": SLOT}],
		).insert()
		self.assertTrue(self.rows()[SLOT].filled)
		frappe.db.set_value("Company", COLLEGE, "company_logo", None)
		self.assertFalse(self.rows()[SLOT].filled)

	def test_the_api_returns_the_same_rows_and_needs_read_access_to_the_cycle(self):
		self.make(nodes=[{"node": NODE, "slot_name": SLOT}]).insert()
		rows = api.evidence_slot_status(self.cycle.name, NODE)
		self.assertEqual({row["slot_name"]: row["filled"] for row in rows}[SLOT], True)
		frappe.set_user(FACULTY_USER)
		with self.assertRaises(frappe.PermissionError):
			api.evidence_slot_status(self.cycle.name, NODE)


class TestFixRound1(EvidenceFixture):
	def test_a_criterion_owner_cannot_change_a_public_evidence_in_any_way(self):
		pub = self.make("Published minutes", is_public=1).insert()
		frappe.set_user(OWNER)
		doc = frappe.get_doc("Evidence", pub.name)
		doc.file = self.make_file(content="swapped")
		with self.assertRaises(frappe.PermissionError):
			doc.save()
		doc = frappe.get_doc("Evidence", pub.name)
		doc.is_public = 0  # unpublishing is a change of the public state too
		with self.assertRaises(frappe.PermissionError):
			doc.save()

	def test_a_criterion_owner_still_edits_a_private_evidence_and_iqac_edits_a_public_one(self):
		private = self.make("Private notes").insert()
		frappe.set_user(OWNER)
		doc = frappe.get_doc("Evidence", private.name)
		doc.description = "edited"
		doc.save()
		frappe.set_user(COORDINATOR)
		pub = self.make("Coordinator public", is_public=1).insert()
		pub.description = "edited too"
		pub.save()

	def test_a_url_slug_never_redirects_off_the_site_it_shows_an_escaped_link_page(self):
		from campus.www import disclosure

		pub = self.make("Offsite", kind="URL", url="https://example.com/a.pdf?x=1&y=2", is_public=1).insert()
		frappe.form_dict.slug = pub.name
		context = frappe._dict()
		disclosure.get_context(context)  # no Redirect
		self.assertEqual(context.external_url, "https://example.com/a.pdf?x=1&y=2")
		self.assertFalse(frappe.local.flags.get("redirect_location"))
		html = frappe.render_template(
			disclosure.EXTERNAL_TEMPLATE, {"title": "<b>t</b>", "external_url": 'https://e.com/"><script>'}
		)
		self.assertNotIn("<script>", html)
		self.assertNotIn("<b>", html)
		self.assertIn("noopener noreferrer nofollow", html)
		frappe.form_dict.pop("slug", None)

	def test_the_index_links_a_url_evidence_directly_with_a_safe_rel(self):
		from campus.www import disclosure

		row = frappe._dict(title="Ext", slug="ext", description="", kind="URL", url="https://example.com/x")
		html = frappe.render_template(
			disclosure.GROUPS_TEMPLATE, {"groups": [("Co", "2022", [("Other", [row])])]}
		)
		self.assertIn('href="https://example.com/x"', html)
		self.assertIn("noopener noreferrer nofollow", html)

	def test_an_address_with_a_trailing_newline_is_not_a_web_address(self):
		self.assertFalse(evidence.is_web_url("https://example.com/a\n"))
		self.assertTrue(evidence.is_web_url("https://example.com/a"))

	def test_the_controller_refuses_an_unlisted_source_whatever_the_write_path(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Campus Settings"):
			self.make(
				source_doctype="Department",
				source_name=frappe.db.get_value("Department", {}),
				source_field="department_name",
				file=None,
			).insert()

	def test_the_controller_refuses_a_source_the_user_cannot_read(self):
		frappe.get_doc("Campus Settings").update(
			{"evidence_sources": [{"document_type": "Company", "file_field": "company_logo"}]}
		).save()
		frappe.set_user(OWNER)  # may create evidence, but holds no permission for the other college
		with self.assertRaises(frappe.PermissionError):
			self.make(
				source_doctype="Company",
				source_name="Iqac Other College",
				source_field="company_logo",
				file=None,
				company="Iqac Other College",
			).insert()

	def test_the_controller_takes_the_company_from_the_source(self):
		frappe.get_doc("Campus Settings").update(
			{"evidence_sources": [{"document_type": "Company", "file_field": "company_logo"}]}
		).save()
		doc = self.make(
			source_doctype="Company",
			source_name=COLLEGE,
			source_field="company_logo",
			file=None,
			company="Iqac Other College",
		)
		with self.assertRaisesRegex(frappe.ValidationError, "company"):
			doc.insert()

	def test_the_source_list_is_for_iqac_roles_only(self):
		frappe.set_user(FACULTY_USER)
		with self.assertRaises(frappe.PermissionError):
			api.evidence_source_doctypes()
		frappe.set_user(COORDINATOR)
		self.assertIsInstance(api.evidence_source_doctypes(), dict)

	def test_a_file_field_that_is_not_an_attach_field_is_refused_in_campus_settings(self):
		settings = frappe.get_doc("Campus Settings")
		settings.evidence_sources = []
		settings.append("evidence_sources", {"document_type": "Company", "file_field": "company_name"})
		with self.assertRaisesRegex(frappe.ValidationError, "Attach"):
			settings.save()

	def test_seeding_adds_a_missing_source_without_touching_the_college_list(self):
		from campus.iqac import setup

		settings = frappe.get_doc("Campus Settings")
		settings.evidence_sources = []
		settings.append("evidence_sources", {"document_type": "Circular"})
		settings.save()
		setup.seed_evidence_sources()
		listed = frappe.get_all(
			"Evidence Source Doctype", {"parent": "Campus Settings"}, pluck="document_type"
		)
		self.assertEqual(listed.count("Circular"), 1)
		self.assertIn("Body Meeting", listed)

	def test_the_public_listing_is_grouped_by_company(self):
		self.make("Group me", is_public=1).insert()
		self.assertTrue(all(len(group) == 3 for group in evidence.public_listing()))
		self.assertEqual(evidence.public_listing()[0][0], COLLEGE)
