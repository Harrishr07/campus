"""M06-02 Malpractice Reports seeded before fix round 2 have a COE approval level that cannot edit the committee
decision, which now belongs to the approver. Fill a blank level of the seeded policy only. DML only."""

from campus.examinations.setup import open_decision_to_approver


def execute():
	open_decision_to_approver()
