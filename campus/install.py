"""Install and migrate hooks for OneBook Campus."""

from campus.academic_governance.setup import setup_academic_governance
from campus.admissions.setup import ensure_aadhaar_role, setup_admissions
from campus.campus_finance.setup import setup_finance
from campus.campus_messaging.setup import setup_messaging
from campus.campus_platform.company_scope import setup_company_fields
from campus.campus_platform.module_packs import seed_module_packs
from campus.campus_platform.positions import ensure_seed_positions
from campus.campus_platform.regulation_setup import ensure_dean_role, setup_regulation_fields
from campus.campus_platform.verification import ensure_verification_role
from campus.curriculum.setup import setup_curriculum
from campus.examinations.setup import ensure_coe_role, seed_cia_unlock_policy
from campus.faculty.setup import setup_faculty
from campus.iqac.setup import ensure_iqac_role, seed_framework
from campus.student_services.setup import ensure_grievance_role, setup_student_services


def before_install():
	ensure_dean_role()  # regulation.json permissions reference it during DocType sync
	ensure_verification_role()  # verifiable_document.json likewise
	ensure_aadhaar_role()  # aadhaar_access_log.json likewise
	ensure_coe_role()  # exam doctypes likewise
	ensure_iqac_role()  # iqac doctypes likewise
	ensure_grievance_role()  # student_grievance.json likewise


def before_migrate():
	ensure_coe_role()  # exam doctype permissions reference it during DocType sync
	ensure_iqac_role()
	ensure_grievance_role()


def after_install():
	ensure_dean_role()
	ensure_verification_role()
	setup_company_fields()
	setup_regulation_fields()
	setup_curriculum()
	setup_admissions()
	seed_module_packs()
	ensure_seed_positions()
	seed_cia_unlock_policy()
	setup_messaging()
	setup_finance()
	setup_student_services()
	setup_faculty()
	setup_academic_governance()
	seed_framework()


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
	seed_cia_unlock_policy()
	setup_messaging()
	setup_finance()
	setup_student_services()
	setup_faculty()
	setup_academic_governance()
	seed_framework()
