"""M06-03 Version rows of Question Paper, Question Bank Item and QP Setter Nomination copied confidential fields
(questions, paper fields) into a table System Managers read; those DocTypes no longer track changes. DML only."""

from campus.examinations.question_paper_setup import drop_confidential_versions


def execute():
	drop_confidential_versions()
