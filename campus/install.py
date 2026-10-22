"""Install and migrate hooks for OneBook Campus."""

from campus.academic_governance.setup import setup_academic_governance
from campus.admissions.setup import ensure_aadhaar_role, setup_admissions
from campus.campus_finance.setup import setup_finance
from campus.campus_messaging.setup import setup_messaging
from campus.campus_platform.company_scope import setup_company_fields
from campus.campus_platform.mandatory_approval import seed_mandatory_approval
from campus.campus_platform.module_packs import seed_module_packs
from campus.campus_platform.positions import ensure_seed_positions
from campus.campus_platform.regulation_setup import ensure_dean_role, setup_regulation_fields
from campus.campus_platform.verification import ensure_verification_role
from campus.curriculum.outcomes import seed_co_po_matrix_policy
from campus.curriculum.setup import setup_curriculum
from campus.examinations.question_paper_setup import setup_question_papers
from campus.examinations.remuneration_payment import setup_remuneration
from campus.examinations.setup import ensure_coe_role, setup_examinations
from campus.faculty.setup import seed_course_allocation_policy, setup_faculty
from campus.iqac.export_seed import seed_export_templates
from campus.iqac.feedback_seed import setup_feedback
from campus.iqac.official_seed import seed_official_register
from campus.iqac.regulator_seed import seed_regulator_templates
from campus.iqac.setup import (
	ensure_iqac_role,
	seed_evidence_sources,
	seed_framework,
	seed_iqac_policies,
	sync_data_points,
)
from campus.research.setup import setup_research
from campus.student_services.mentoring import ensure_mentoring_roles, setup_mentoring
from campus.student_services.setup import ensure_grievance_role, setup_student_services


def before_install():
	ensure_dean_role()  # regulation.json permissions reference it during DocType sync
	ensure_verification_role()  # verifiable_document.json likewise
	ensure_aadhaar_role()  # aadhaar_access_log.json likewise
	ensure_coe_role()  # exam doctypes likewise
	ensure_iqac_role()  # iqac doctypes likewise
	ensure_grievance_role()  # student_grievance.json likewise
	ensure_mentoring_roles()  # counselling_note.json and parent_interaction.json likewise


def before_migrate():
	ensure_coe_role()  # exam doctype permissions reference it during DocType sync
	ensure_iqac_role()
	ensure_grievance_role()
	ensure_mentoring_roles()


def after_install():
	ensure_dean_role()
	ensure_verification_role()
	setup_company_fields()
	setup_regulation_fields()
	setup_curriculum()
	setup_admissions()
	seed_module_packs()
	ensure_seed_positions()
	setup_examinations()
	setup_question_papers()
	setup_messaging()
	setup_finance()
	setup_student_services()
	setup_mentoring()
	setup_faculty()
	seed_course_allocation_policy()
	seed_co_po_matrix_policy()
	setup_academic_governance()
	setup_remuneration()
	seed_framework()
	seed_export_templates()
	sync_data_points()
	seed_iqac_policies()
	setup_feedback()
	seed_regulator_templates()
	seed_official_register()
	seed_evidence_sources()
	setup_research()
	seed_mandatory_approval()  # once; a patch seeds existing sites, so the college's edits to the list stand


def after_migrate():
	ensure_coe_role()
	ensure_dean_role()
	ensure_verification_role()
	setup_company_fields()
	setup_regulation_fields()
	setup_curriculum()
	setup_admissions()
	seed_module_packs()
	ensure_seed_positions()
	setup_examinations()
	setup_question_papers()
	setup_messaging()
	setup_finance()
	setup_student_services()
	setup_mentoring()
	setup_faculty()
	seed_course_allocation_policy()
	seed_co_po_matrix_policy()
	setup_academic_governance()
	setup_remuneration()
	seed_framework()
	seed_export_templates()
	sync_data_points()
	seed_iqac_policies()
	setup_feedback()
	seed_regulator_templates()
	seed_official_register()
	seed_evidence_sources()
	setup_research()
