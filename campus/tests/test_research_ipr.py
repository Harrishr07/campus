"""P3-T21 (M08-11, M08-12) tests: Invention Disclosure -> Patent lifecycle with costs and revenue share, Publication with the
Crossref fill (mocked), unique DOIs, the counting rules (once per institution, once per faculty) in the reports and data
points, and the faculty profile. Crossref is never called: `requests.get` is patched."""

from unittest.mock import MagicMock, patch

import frappe
import requests
from frappe.tests import UnitTestCase
from frappe.utils import add_days, today

from campus.campus_platform.approvals import approve, request_approval
from campus.iqac import registry
from campus.research import api as research
from campus.research import crossref, ipr, publications
from campus.research.report.patent_register import patent_register
from campus.research.report.publication_register import publication_register
from campus.research.report.publications_by_teacher import publications_by_teacher
from campus.research.setup import seed_research
from campus.tests.factories import make_user
from campus.tests.finance_factories import make_company_with_accounts
from campus.tests.utils import CampusTestCase

COLLEGE, ABBR = "Research IPR Test College", "RIPR"
OTHER, OTHER_ABBR = "Research IPR Other College", "RIPO"
YEAR = "IPR Test Year"
REVIEWER = "ipr-reviewer@example.com"
CROSSREF_WORK = {
	"title": ["Low-cost water sensors"],
	"container-title": ["Journal of Applied Sensing"],
	"publisher": "Example Press",
	"ISSN": ["1234-5679"],
	"type": "journal-article",
	"issued": {"date-parts": [[2031, 3]]},
	"is-referenced-by-count": 7,
	"author": [
		{"given": "Asha", "family": "Rao", "affiliation": [{"name": "Dummy College"}]},
		{"given": "Vikram", "family": "Shah"},
		{"name": "Sensing Consortium"},
	],
}


def crossref_response(message=None, status=200):
	response = MagicMock(status_code=status, ok=status < 400)
	response.json.return_value = {"message": CROSSREF_WORK if message is None else message}
	return response


class TestCrossrefParsing(UnitTestCase):
	def test_doi_is_normalised_from_url_and_prefix_forms(self):
		for text in ("10.1234/ABC.9", "https://doi.org/10.1234/ABC.9", "doi:10.1234/abc.9", " http://dx.doi.org/10.1234/Abc.9 "):
			self.assertEqual(crossref.normalise_doi(text), "10.1234/abc.9")

	def test_a_non_doi_is_refused(self):
		for text in ("", "abc", "10.12/x", "11.1234/x", "10.1234/"):
			with self.assertRaisesRegex(frappe.ValidationError, "not a valid DOI"):
				crossref.normalise_doi(text)

	def test_work_fields(self):
		work = crossref.parse_work(CROSSREF_WORK)
		self.assertEqual(
			(work["title"], work["container_title"], work["publisher"], work["issns"]),
			("Low-cost water sensors", "Journal of Applied Sensing", "Example Press", ["1234-5679"]),
		)
		self.assertEqual((work["publication_type"], work["publication_date"], work["citations"]), ("Journal Article", "2031-03-01", 7))
		self.assertEqual(
			[(a["author_name"], a["affiliation"]) for a in work["authors"]],
			[("Asha Rao", "Dummy College"), ("Vikram Shah", None), ("Sensing Consortium", None)],
		)

	def test_date_falls_back_to_other_dates_and_missing_parts_are_the_first(self):
		self.assertEqual(crossref.work_date({"published-online": {"date-parts": [[2030]]}}), "2030-01-01")
		self.assertEqual(crossref.work_date({"issued": {"date-parts": [[None]]}, "published-print": {"date-parts": [[2029, 5, 17]]}}), "2029-05-17")
		self.assertIsNone(crossref.work_date({}))

	def test_unknown_work_type_and_missing_parts_give_blanks(self):
		work = crossref.parse_work({"type": "dataset"})
		self.assertEqual((work["title"], work["publication_type"], work["authors"], work["citations"]), (None, None, [], None))


class TestIprRules(UnitTestCase):
	DATES = {"filed_date": "2030-01-10", "published_date": "2030-07-10", "examined_date": "2031-01-10", "granted_date": "2031-06-10"}

	def check(self, status, before=None, **dates):
		ipr.check_lifecycle(status, {**self.DATES, **dates}, before, "2031-12-31")

	def test_each_stage_needs_its_own_date(self):
		for status, field in (("Filed", "filed_date"), ("Published", "published_date"), ("Examined", "examined_date"), ("Granted", "granted_date")):
			with self.assertRaisesRegex(frappe.ValidationError, "Enter the"):
				self.check(status, **{field: None})

	def test_licensed_needs_the_grant_date(self):
		self.check("Licensed")
		with self.assertRaisesRegex(frappe.ValidationError, "Enter the granted"):
			self.check("Licensed", granted_date=None)

	def test_skipped_middle_stages_are_allowed(self):
		self.check("Granted", published_date=None, examined_date=None)

	def test_no_step_back(self):
		with self.assertRaisesRegex(frappe.ValidationError, "can't go back"):
			self.check("Examined", before="Granted", granted_date=None)
		self.check("Granted", before="Granted")

	def test_a_date_of_a_stage_not_reached_is_refused(self):
		with self.assertRaisesRegex(frappe.ValidationError, "can't be set while"):
			self.check("Published", examined_date="2031-01-10", granted_date=None)

	def test_dates_run_in_order_and_not_into_the_future(self):
		with self.assertRaisesRegex(frappe.ValidationError, "before an earlier stage"):
			self.check("Granted", granted_date="2030-12-31")
		with self.assertRaisesRegex(frappe.ValidationError, "in the future"):
			self.check("Granted", granted_date="2032-01-01")

	def test_revenue_split_puts_rounding_with_the_institution(self):
		self.assertEqual(ipr.split_revenue(1000, 60), (600, 400))
		self.assertEqual(ipr.split_revenue(100.01, 33.33), (33.33, 66.68))
		self.assertEqual(ipr.split_revenue(500, 100), (500, 0))

	def test_inventor_split_sums_to_the_total(self):
		self.assertEqual(ipr.split_among(400, [50, 30, 20]), [200, 120, 80])
		shares = ipr.split_among(100, [33.33, 33.33, 33.34])
		self.assertEqual(sum(shares), 100)
		self.assertEqual(ipr.split_among(0, []), [])

	def test_default_shares_are_equal_and_total_100(self):
		self.assertEqual(ipr.default_shares(4), [25, 25, 25, 25])
		self.assertEqual(sum(ipr.default_shares(3)), 100)
		self.assertEqual(ipr.default_shares(1), [100])


class TestHIndex(UnitTestCase):
	def test_h_index(self):
		self.assertEqual(publications.hindex([10, 8, 5, 4, 3]), 4)
		self.assertEqual(publications.hindex([25, 8, 5, 3, 3]), 3)
		self.assertEqual(publications.hindex([0, 0, None]), 0)
		self.assertEqual(publications.hindex([]), 0)
		self.assertEqual(publications.hindex(iter([1])), 1)


class IprFixtures(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_company_with_accounts(COLLEGE, ABBR)
		make_company_with_accounts(OTHER, OTHER_ABBR)
		if not frappe.db.exists("Gender", "Male"):
			frappe.get_doc({"doctype": "Gender", "gender": "Male"}).insert()
		make_user(REVIEWER, [COLLEGE])
		frappe.get_doc("User", REVIEWER).add_roles("Principal")

	def setUp(self):
		frappe.db.savepoint("research_ipr_test")
		self.addCleanup(frappe.db.rollback, save_point="research_ipr_test")
		self.addCleanup(frappe.set_user, "Administrator")
		seed_research()
		self.year = self.make_year()
		self.cse = self.make_department("IPR CSE")
		self.ece = self.make_department("IPR ECE")
		self.ugc = self.make_journal("IPR UGC Journal", "1234-5679", ugc_care=1)
		self.plain = self.make_journal("IPR Plain Journal", "0378-5955", ugc_care=0)
		self.teachers = [self.make_employee(name, self.cse) for name in ("Asha", "Bela", "Chitra")]
		self.ece_teacher = self.make_employee("Esha", self.ece)

	# fixtures
	def settings_values(self):
		from campus.tests.finance_factories import make_account

		return {
			"grant_liability_parent": f"Current Liabilities - {ABBR}",
			"grant_income_account": make_account(COLLEGE, ABBR, "IPR Grant Income", "Indirect Income"),
			"deferred_capital_grant_account": make_account(COLLEGE, ABBR, "IPR Deferred Capital Grant", "Non-Current Liabilities"),
		}

	def make_year(self):
		if not frappe.db.exists("Academic Year", YEAR):
			frappe.get_doc(
				{"doctype": "Academic Year", "academic_year_name": YEAR, "year_start_date": "2025-06-01", "year_end_date": "2026-05-31"}
			).insert()
		return YEAR

	def make_department(self, name):
		return frappe.get_doc({"doctype": "Department", "department_name": name, "company": COLLEGE}).insert().name

	def make_journal(self, title, issn, **flags):
		return frappe.get_doc({"doctype": "Indexed Journal", "journal_title": title, "issn": issn, **flags}).insert().name

	def make_employee(self, first_name, department, company=COLLEGE):
		return frappe.get_doc(
			{
				"doctype": "Employee", "first_name": first_name, "last_name": frappe.generate_hash(length=6), "gender": "Male",
				"date_of_birth": "1980-01-01", "date_of_joining": "2010-01-01", "company": company, "department": department,
				"personal_email": f"{first_name.lower()}-{frappe.generate_hash(length=6)}@example.com",
			}  # fmt: skip
		).insert().name

	def make_student(self, first_name):
		return frappe.get_doc(
			{"doctype": "Student", "enabled": 1, "first_name": first_name, "student_email_id": f"{first_name.lower()}@ipr.example.com", "oc_company": COLLEGE}
		).insert().name

	def publication(self, authors=None, **values):
		authors = authors if authors is not None else [{"author_type": "Employee", "employee": e} for e in self.teachers]
		return frappe.get_doc(
			{
				"doctype": "Publication", "company": COLLEGE, "title": f"Paper {frappe.generate_hash(length=6)}",
				"publication_type": "Journal Article", "publication_date": "2025-09-15", "journal": self.ugc,
				"authors": authors, **values,
			}  # fmt: skip
		).insert()

	def point(self, key, department=None):
		return registry.data_point(key, COLLEGE, YEAR, department)

	def register(self, **extra):
		return publication_register.execute({"company": COLLEGE, "academic_year": YEAR, **extra})[1]

	def by_teacher(self, **extra):
		return {r["employee"]: r for r in publications_by_teacher.execute({"company": COLLEGE, "academic_year": YEAR, **extra})[1]}


class TestPublication(IprFixtures):
	# acceptance 1: DOI fill (mocked) and unique DOIs
	def test_doi_fills_title_journal_date_type_and_authors_from_crossref(self):
		with patch("campus.research.crossref.requests.get", return_value=crossref_response()) as get:
			pub = frappe.get_doc({"doctype": "Publication", "company": COLLEGE, "doi": "https://doi.org/10.1234/ABC.9"}).insert()
		self.assertEqual(get.call_args.args[0], "https://api.crossref.org/works/10.1234%2Fabc.9")
		self.assertEqual(pub.doi, "10.1234/abc.9")
		self.assertEqual((pub.title, pub.publication_type, pub.publication_year), ("Low-cost water sensors", "Journal Article", 2031))
		self.assertEqual(str(pub.publication_date), "2031-03-01")
		self.assertEqual((pub.journal, pub.container_title, pub.publisher, pub.citations), (self.ugc, "Journal of Applied Sensing", "Example Press", 7))
		self.assertEqual([(a.author_name, a.author_type) for a in pub.authors], [("Asha Rao", "External"), ("Vikram Shah", "External"), ("Sensing Consortium", "External")])
		self.assertEqual(str(pub.citations_as_on), today())

	def test_entered_values_are_never_replaced_by_crossref(self):
		with patch("campus.research.crossref.requests.get", return_value=crossref_response()):
			pub = frappe.get_doc(
				{
					"doctype": "Publication", "company": COLLEGE, "doi": "10.1234/abc.9", "publication_date": "2025-10-01",
					"journal": self.plain, "authors": [{"author_type": "Employee", "employee": self.teachers[0]}],
					"publication_type": "Journal Article", "title": "",
				}
			).insert()
		self.assertEqual(pub.title, "Low-cost water sensors")
		self.assertEqual((str(pub.publication_date), pub.journal, len(pub.authors)), ("2025-10-01", self.plain, 1))

	def test_a_publication_with_a_title_does_not_call_crossref(self):
		with patch("campus.research.crossref.requests.get") as get:
			self.publication(doi="10.5555/own.1")
		get.assert_not_called()

	def test_doc_method_fills_a_form_that_has_only_a_doi(self):
		pub = frappe.new_doc("Publication")
		pub.doi = "10.1234/abc.9"
		with patch("campus.research.crossref.requests.get", return_value=crossref_response()):
			pub.fill_from_crossref()
		self.assertEqual((pub.title, len(pub.authors)), ("Low-cost water sensors", 3))

	def test_duplicate_doi_is_refused_however_it_is_written(self):
		first = self.publication(doi="10.5555/dup.1")
		for text in ("10.5555/DUP.1", "https://doi.org/10.5555/dup.1", "doi:10.5555/dup.1"):
			with self.assertRaisesRegex(frappe.ValidationError, first.name):
				self.publication(doi=text)

	def test_publications_without_a_doi_do_not_collide(self):
		self.publication()
		self.publication()
		self.assertEqual(frappe.db.count("Publication", {"doi": ["is", "not set"], "company": COLLEGE}), 2)

	def test_resaving_keeps_the_doi(self):
		pub = self.publication(doi="10.5555/keep.1")
		pub.citations = 3
		pub.save()
		self.assertEqual(frappe.db.get_value("Publication", pub.name, "doi"), "10.5555/keep.1")

	def test_unknown_unreachable_and_failing_crossref_give_clear_errors(self):
		doc = {"doctype": "Publication", "company": COLLEGE, "doi": "10.1234/none.1"}
		with patch("campus.research.crossref.requests.get", return_value=crossref_response(status=404)):
			with self.assertRaisesRegex(frappe.ValidationError, "no record of the DOI"):
				frappe.get_doc(doc).insert()
		with patch("campus.research.crossref.requests.get", return_value=crossref_response(status=503)):
			with self.assertRaisesRegex(frappe.ValidationError, "HTTP 503"):
				frappe.get_doc(doc).insert()
		with patch("campus.research.crossref.requests.get", side_effect=requests.ConnectionError("down")):
			with self.assertRaisesRegex(frappe.ValidationError, "could not be reached"):
				frappe.get_doc(doc).insert()

	def test_invalid_doi_is_refused_without_a_request(self):
		with patch("campus.research.crossref.requests.get") as get:
			with self.assertRaisesRegex(frappe.ValidationError, "not a valid DOI"):
				self.publication(doi="not a doi")
		get.assert_not_called()

	def test_a_non_json_answer_and_a_redirect_give_clear_errors(self):
		doc = {"doctype": "Publication", "company": COLLEGE, "doi": "10.1234/odd.1"}
		html = crossref_response()
		html.json.side_effect = ValueError("not json")
		with patch("campus.research.crossref.requests.get", return_value=html):
			with self.assertRaisesRegex(frappe.ValidationError, "could not be read"):
				frappe.get_doc(doc).insert()
		with patch("campus.research.crossref.requests.get", return_value=crossref_response(status=302)) as get:
			with self.assertRaisesRegex(frappe.ValidationError, "HTTP 302"):
				frappe.get_doc(doc).insert()
		self.assertIs(get.call_args.kwargs["allow_redirects"], False)

	def test_a_duplicate_doi_that_slips_past_the_check_gets_the_same_friendly_refusal(self):
		self.publication(doi="10.5555/race.1")
		with patch("campus.research.doctype.publication.publication.Publication.check_unique_doi"):
			with self.assertRaisesRegex(frappe.ValidationError, "already entered"):
				self.publication(doi="10.5555/race.1")

	def test_authors_must_belong_to_the_publications_college(self):
		outsider = self.make_employee("Outside", None, company=OTHER)
		with self.assertRaisesRegex(frappe.ValidationError, "does not belong"):
			self.publication(authors=[{"author_type": "Employee", "employee": outsider}])

	# authors
	def test_authors_are_employees_students_or_external(self):
		student = self.make_student("Ipra")
		pub = self.publication(
			authors=[
				{"author_type": "Employee", "employee": self.teachers[0]},
				{"author_type": "Student", "student": student},
				{"author_type": "External", "author_name": "Dr Outsider", "affiliation": "Elsewhere University"},
			]
		)
		self.assertEqual(pub.authors[0].author_name, frappe.db.get_value("Employee", self.teachers[0], "employee_name"))
		self.assertEqual(pub.authors[1].author_name, frappe.db.get_value("Student", student, "student_name"))
		self.assertEqual(pub.authors[2].author_name, "Dr Outsider")

	def test_author_rows_are_checked(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Add at least one author"):
			self.publication(authors=[])
		with self.assertRaisesRegex(frappe.ValidationError, "choose the Employee"):
			self.publication(authors=[{"author_type": "Employee"}])
		with self.assertRaisesRegex(frappe.ValidationError, "enter the name"):
			self.publication(authors=[{"author_type": "External", "author_name": " "}])
		with self.assertRaisesRegex(frappe.ValidationError, "more than once"):
			self.publication(authors=[{"author_type": "Employee", "employee": self.teachers[0]}] * 2)

	def test_a_journal_or_proceedings_is_needed_except_for_books(self):
		with self.assertRaisesRegex(frappe.ValidationError, "journal, proceedings or book"):
			self.publication(journal=None)
		self.publication(journal=None, publication_type="Book")
		self.publication(journal=None, container_title="Proceedings of ICSE", publication_type="Conference Paper")


class TestCountingRules(IprFixtures):
	# acceptance 2: once per institution, once per faculty
	def test_a_paper_by_three_teachers_counts_once_for_the_college_and_once_for_each_teacher(self):
		pub = self.publication(citations=4)
		register = self.register()
		self.assertEqual([(r["name"], r["authors"], r["teacher_authors"]) for r in register], [(pub.name, 3, 3)])
		self.assertEqual(self.point("publications_published")["value"], 1)
		self.assertEqual(self.point("ugc_care_papers")["value"], 1)
		self.assertEqual(self.point("publication_citations")["value"], 4)  # the paper's, not 3 x 4
		rows = self.by_teacher()
		self.assertEqual(set(rows), set(self.teachers))
		for row in rows.values():
			self.assertEqual((row["publications"], row["ugc_care_papers"], row["citations"], row["h_index"]), (1, 1, 4, 1))

	def test_teacher_counts_add_up_per_person_not_per_paper(self):
		self.publication(citations=5)
		self.publication(authors=[{"author_type": "Employee", "employee": self.teachers[0]}], journal=self.plain, citations=1)
		rows = self.by_teacher()
		self.assertEqual(self.point("publications_published")["value"], 2)
		self.assertEqual((rows[self.teachers[0]]["publications"], rows[self.teachers[0]]["ugc_care_papers"]), (2, 1))
		self.assertEqual((rows[self.teachers[0]]["citations"], rows[self.teachers[0]]["h_index"]), (6, 1))
		self.assertEqual(rows[self.teachers[1]]["publications"], 1)

	def test_students_and_external_authors_count_for_the_college_only(self):
		self.publication(
			authors=[
				{"author_type": "Student", "student": self.make_student("Iprb")},
				{"author_type": "External", "author_name": "Dr Outsider"},
			]
		)
		self.assertEqual(self.point("publications_published")["value"], 1)
		self.assertEqual(self.by_teacher(), {})
		self.assertEqual([(r["authors"], r["teacher_authors"]) for r in self.register()], [(2, 0)])

	def test_papers_outside_the_year_or_college_are_not_counted(self):
		self.publication(publication_date="2025-05-31")
		self.publication(publication_date="2026-06-01")
		frappe.get_doc(
			{
				"doctype": "Publication", "company": OTHER, "title": "Elsewhere", "publication_type": "Book", "publication_date": "2025-09-15",
				"authors": [{"author_type": "External", "author_name": "X"}],
			}
		).insert()
		self.assertEqual(self.point("publications_published")["value"], 0)
		self.publication(publication_date="2025-06-01")
		self.publication(publication_date="2026-05-31")
		self.assertEqual(self.point("publications_published")["value"], 2)

	def test_department_narrows_to_its_teachers_work(self):
		self.publication(authors=[{"author_type": "Employee", "employee": self.teachers[0]}])
		self.publication(authors=[{"author_type": "Employee", "employee": self.ece_teacher}])
		both = self.publication(authors=[{"author_type": "Employee", "employee": self.teachers[1]}, {"author_type": "Employee", "employee": self.ece_teacher}])
		self.assertEqual(self.point("publications_published")["value"], 3)
		self.assertEqual(self.point("publications_published", self.cse)["value"], 2)
		self.assertEqual(self.point("publications_published", self.ece)["value"], 2)
		self.assertEqual(set(self.by_teacher(department=self.ece)), {self.ece_teacher})
		self.assertEqual(self.by_teacher(department=self.ece)[self.ece_teacher]["publications"], 2)
		self.assertIn(both.name, [r["name"] for r in self.register(department=self.cse)])

	def test_ugc_care_papers_are_journal_articles_in_listed_journals_read_live(self):
		self.publication(journal=self.plain)
		conference = self.publication(journal=self.ugc, publication_type="Conference Paper")
		self.assertEqual(self.point("ugc_care_papers")["value"], 0)
		frappe.db.set_value("Indexed Journal", self.plain, "ugc_care", 1)
		self.assertEqual(self.point("ugc_care_papers")["value"], 1)
		self.assertNotIn(conference.name, [r["name"] for r in self.point("ugc_care_papers")["records"]])

	def test_books_and_chapters_include_conference_papers(self):
		self.publication(journal=None, publication_type="Book")
		self.publication(journal=None, publication_type="Book Chapter", container_title="Edited book")
		self.publication(journal=None, publication_type="Conference Paper", container_title="Proceedings")
		self.publication()
		self.assertEqual(self.point("books_and_chapters")["value"], 3)

	def test_h_index_data_point(self):
		for citations in (10, 8, 5, 4, 3):
			self.publication(citations=citations)
		self.assertEqual(self.point("publication_h_index")["value"], 4)
		self.assertEqual(self.point("publication_citations")["value"], 30)
		self.assertEqual(len(self.point("publication_h_index")["records"]), 5)

	def test_h_index_and_citations_cover_a_window_of_academic_years(self):
		for date, citations in (("2025-09-15", 10), ("2025-10-15", 8), ("2022-09-15", 6), ("2021-09-15", 5), ("2019-09-15", 50)):
			self.publication(publication_date=date, citations=citations)
		frappe.get_doc({"doctype": "Research Settings", "company": COLLEGE, **self.settings_values()}).insert()
		# the year alone: 10 and 8 -> h 2; five years back to 2021-06: 10, 8, 6, 5 -> h 4; the 2019 paper is outside
		self.assertEqual(self.point("publication_h_index")["value"], 4)
		self.assertEqual(self.point("publication_citations")["value"], 29)
		self.assertEqual(self.point("publications_published")["value"], 2)
		self.assertEqual(publications_by_teacher.execute({"company": COLLEGE, "academic_year": YEAR})[1][0]["h_index"], 2)
		frappe.db.set_value("Research Settings", COLLEGE, "publication_window_years", 1)
		self.assertEqual(self.point("publication_h_index")["value"], 2)

	def test_reports_are_empty_without_their_filters(self):
		self.publication()
		self.assertEqual(publication_register.execute({"company": COLLEGE})[1], [])
		self.assertEqual(publications_by_teacher.execute({"academic_year": YEAR})[1], [])
		self.assertEqual(patent_register.execute({})[1], [])

	def test_register_follows_the_users_company_permissions(self):
		self.publication()
		user = "ipr-other-college@example.com"
		make_user(user, [OTHER])
		frappe.get_doc("User", user).add_roles("IQAC Coordinator")
		frappe.set_user(user)
		self.assertEqual(self.register(), [])

	def test_faculty_profile_aggregates_publications_and_patents(self):
		self.publication(citations=6)
		self.publication(authors=[{"author_type": "Employee", "employee": self.teachers[0]}], citations=2)
		self.publication(authors=[{"author_type": "Employee", "employee": self.teachers[1]}], citations=9)
		profile = research.faculty_research_profile(self.teachers[0])
		self.assertEqual((profile["publication_count"], profile["citations"], profile["h_index"]), (2, 8, 2))
		self.assertEqual(profile["patents"], [])


class TestPatentLifecycle(IprFixtures):
	def disclosure(self, **values):
		doc = frappe.get_doc(
			{
				"doctype": "Invention Disclosure", "title": "Soil moisture probe", "company": COLLEGE, "department": self.cse,
				"ipr_type": self.ipr_type(), "disclosure_date": add_days(today(), -400),
				"inventors": [{"inventor_type": "Employee", "employee": e} for e in self.teachers[:2]], **values,
			}  # fmt: skip
		).insert()
		return doc

	def ipr_type(self):
		if not frappe.db.exists("IPR Type", "Patent"):
			frappe.get_doc({"doctype": "IPR Type", "ipr_type_name": "Patent"}).insert()
		return "Patent"

	def approved_disclosure(self, **values):
		doc = self.disclosure(**values)
		request = request_approval("Invention Disclosure", doc.name)
		frappe.set_user(REVIEWER)
		approve(request, None)
		frappe.set_user("Administrator")
		return frappe.get_doc("Invention Disclosure", doc.name)

	def patent(self, disclosure=None, **values):
		disclosure = disclosure or self.approved_disclosure()
		return frappe.get_doc(
			{
				"doctype": "Patent", "invention_disclosure": disclosure.name, "filed_date": add_days(today(), -300),
				"application_number": "202131001234", "institution_share_percent": 60, **values,
			}  # fmt: skip
		).insert()

	def grant(self, patent, **dates):
		patent.update(
			{"status": "Granted", "patent_number": "IN123456", "granted_date": add_days(today(), -10), **dates}
		)
		patent.save()
		return patent

	# disclosure and committee approval
	def test_disclosure_needs_committee_approval_to_submit(self):
		doc = self.disclosure()
		with self.assertRaisesRegex(frappe.ValidationError, "needs approval"):
			doc.submit()
		self.assertEqual(self.approved_disclosure().docstatus, 1)

	def test_inventors_never_approve_their_own_disclosure(self):
		user = "ipr-inventor@example.com"
		make_user(user, [COLLEGE])
		frappe.get_doc("User", user).add_roles("Principal")
		frappe.db.set_value("Employee", self.teachers[0], "user_id", user)
		doc = self.disclosure()
		request = request_approval("Invention Disclosure", doc.name)
		frappe.set_user(user)
		with self.assertRaises(frappe.PermissionError):
			approve(request, None)

	def test_submit_without_a_policy_is_refused(self):
		frappe.db.delete("Approval Policy", {"document_type": "Invention Disclosure"})
		with self.assertRaises(frappe.ValidationError):
			self.disclosure().submit()

	def test_negative_share_and_inventors_of_other_colleges_are_refused(self):
		with self.assertRaisesRegex(frappe.ValidationError, "can't be negative"):
			self.disclosure(inventors=[
				{"inventor_type": "Employee", "employee": self.teachers[0], "share_percent": 120},
				{"inventor_type": "External", "inventor_name": "Dr X", "share_percent": -20}])
		outsider = self.make_employee("Outside", None, company=OTHER)
		with self.assertRaisesRegex(frappe.ValidationError, "does not belong"):
			self.disclosure(inventors=[{"inventor_type": "Employee", "employee": outsider}])

	def test_cancelling_the_disclosure_does_not_freeze_the_patent(self):
		patent = self.patent()
		frappe.db.set_value("Invention Disclosure", patent.invention_disclosure, "docstatus", 2)
		patent = frappe.get_doc("Patent", patent.name)
		patent.append("costs", {"cost_date": today(), "description": "Renewal", "amount": 100})
		patent.save()
		self.assertEqual(patent.total_cost, 100)
		patent.update({"status": "Published", "published_date": add_days(today(), -100)})
		with self.assertRaisesRegex(frappe.ValidationError, "must be approved"):
			patent.save()

	def test_inventor_shares_default_to_equal_and_must_total_100(self):
		doc = self.disclosure(inventors=[{"inventor_type": "Employee", "employee": e} for e in self.teachers])
		self.assertEqual([r.share_percent for r in doc.inventors], [33.33, 33.33, 33.34])
		with self.assertRaisesRegex(frappe.ValidationError, "total 100"):
			self.disclosure(inventors=[{"inventor_type": "Employee", "employee": self.teachers[0], "share_percent": 60}, {"inventor_type": "External", "inventor_name": "Dr X", "share_percent": 30}])

	def test_disclosure_needs_inventors_and_no_future_date(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Add at least one inventor"):
			self.disclosure(inventors=[])
		with self.assertRaisesRegex(frappe.ValidationError, "in the future"):
			self.disclosure(disclosure_date=add_days(today(), 1))

	# patent
	def test_only_an_approved_disclosure_can_be_filed(self):
		with self.assertRaisesRegex(frappe.ValidationError, "must be approved"):
			self.patent(self.disclosure())

	def test_patent_takes_college_department_and_type_from_its_disclosure(self):
		patent = self.patent()
		self.assertEqual(
			(patent.title, patent.company, patent.department, patent.ipr_type, patent.status),
			("Soil moisture probe", COLLEGE, self.cse, "Patent", "Filed"),
		)

	def test_status_moves_forward_with_dates_and_never_back(self):
		patent = self.patent()
		patent.status = "Published"
		with self.assertRaisesRegex(frappe.ValidationError, "published date"):
			patent.save()
		patent = frappe.get_doc("Patent", patent.name)  # a refused save leaves the copy in hand stale
		patent.update({"status": "Published", "published_date": add_days(today(), -200)})
		patent.save()
		self.grant(patent)
		patent.status = "Examined"
		patent.examined_date = add_days(today(), -50)
		with self.assertRaisesRegex(frappe.ValidationError, "can't go back"):
			patent.save()

	def test_granted_needs_a_patent_number(self):
		patent = self.patent()
		patent.update({"status": "Granted", "granted_date": add_days(today(), -10)})
		with self.assertRaisesRegex(frappe.ValidationError, "patent number"):
			patent.save()

	def test_costs_are_totalled(self):
		patent = self.patent(costs=[
			{"cost_date": add_days(today(), -300), "description": "Filing fee", "amount": 8000},
			{"cost_date": add_days(today(), -100), "description": "Attorney", "amount": 12500.5},
		])
		self.assertEqual(patent.total_cost, 20500.5)
		patent.costs[0].amount = 0
		with self.assertRaisesRegex(frappe.ValidationError, "above zero"):
			patent.save()

	def test_licence_revenue_only_once_granted_and_moves_the_patent_to_licensed(self):
		licence = {"licensee": "Acme Agri", "licence_date": add_days(today(), -5), "amount_received": 1000}
		patent = self.patent()
		patent.append("licences", licence)
		with self.assertRaisesRegex(frappe.ValidationError, "only for a granted patent"):
			patent.save()
		patent = self.patent()
		self.grant(patent)
		patent.append("licences", {**licence, "licence_date": add_days(today(), -20)})
		with self.assertRaisesRegex(frappe.ValidationError, "before the patent was granted"):
			patent.save()
		patent = frappe.get_doc("Patent", patent.name)
		patent.append("licences", licence)
		patent.save()
		self.assertEqual(patent.status, "Licensed")

	def test_revenue_is_split_between_institution_and_inventors_by_their_shares(self):
		disclosure = self.approved_disclosure(inventors=[
			{"inventor_type": "Employee", "employee": self.teachers[0], "share_percent": 75},
			{"inventor_type": "External", "inventor_name": "Dr X", "share_percent": 25},
		])
		patent = self.grant(self.patent(disclosure))
		patent.append("licences", {"licensee": "Acme Agri", "licence_date": add_days(today(), -5), "amount_received": 1000})
		patent.append("licences", {"licensee": "Acme Agri", "licence_date": add_days(today(), -2), "amount_received": 500.01})
		patent.save()
		self.assertEqual((patent.licences[0].institution_amount, patent.licences[0].inventors_amount), (600, 400))
		self.assertEqual((patent.total_revenue, patent.institution_revenue, patent.inventors_revenue), (1500.01, 900.01, 600))
		shares = patent.inventor_shares()
		self.assertEqual([(s["inventor_name"], s["amount"]) for s in shares], [(frappe.db.get_value("Employee", self.teachers[0], "employee_name"), 450), ("Dr X", 150)])

	def test_institution_share_is_a_percentage(self):
		with self.assertRaisesRegex(frappe.ValidationError, "between 0 and 100"):
			self.patent(institution_share_percent=120)

	def test_disclosure_of_a_patent_cannot_change(self):
		patent = self.patent()
		patent.invention_disclosure = self.approved_disclosure(title="Another").name
		with self.assertRaisesRegex(frappe.ValidationError, "can't be changed"):
			patent.save()

	# reports and data points
	def test_patent_data_points_count_by_the_date_of_the_stage(self):
		filed_in_year = self.patent(filed_date="2025-08-01")
		filed_before = self.patent(filed_date="2025-01-01")
		self.grant(filed_before, granted_date="2025-12-01")
		self.assertEqual(self.point("patents_filed")["value"], 1)
		self.assertEqual(self.point("patents_granted")["value"], 1)
		self.assertEqual(self.point("patents_published")["value"], 0)
		filed_in_year.update({"status": "Published", "published_date": "2025-10-01"})
		filed_in_year.save()
		self.assertEqual(self.point("patents_published")["records"], [{"doctype": "Patent", "name": filed_in_year.name}])
		self.assertEqual(self.point("patents_filed", self.ece)["value"], 0)
		self.assertEqual(self.point("patents_granted", self.cse)["value"], 1)

	def test_patent_register_lists_with_costs_and_filters(self):
		plain = self.patent(costs=[{"cost_date": today(), "description": "Fee", "amount": 500}], filed_date="2025-08-01")
		granted = self.grant(self.patent(filed_date="2025-01-01"), granted_date="2025-11-01")
		rows = {r["name"]: r for r in patent_register.execute({"company": COLLEGE})[1]}
		self.assertEqual(set(rows), {plain.name, granted.name})
		self.assertEqual(rows[plain.name]["total_cost"], 500)
		self.assertEqual([r["name"] for r in patent_register.execute({"company": COLLEGE, "status": "Granted"})[1]], [granted.name])
		self.assertEqual([r["name"] for r in patent_register.execute({"company": COLLEGE, "academic_year": YEAR})[1]], [plain.name])
		self.assertEqual(patent_register.execute({"company": OTHER})[1], [])

	def test_faculty_profile_lists_patents_of_their_disclosures(self):
		patent = self.patent()
		self.assertEqual([p.name for p in research.faculty_research_profile(self.teachers[0])["patents"]], [patent.name])
		self.assertEqual(research.faculty_research_profile(self.teachers[2])["patents"], [])
