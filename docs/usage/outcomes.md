# Outcomes and CO-PO matrices (M03-02, P3-T09)

Academics area > Masters / Transactions / Reports.

## Masters

- **Department Mission**: a department's numbered missions (M1, M2 ...).
- **Program Educational Objective**: PEO1 ... of a programme under a regulation. Its **Mission Mapping** rows map it to missions of the programme's department, with a correlation from 1 to 3 (the PEO-Mission matrix).
- **Program Outcome**: PO1 ... of a programme under a regulation. **Seed NBA POs** (list view button, or `campus.curriculum.api.seed_program_outcomes(program, regulation)`) adds the twelve NBA graduate attributes the programme doesn't have yet. Their statements are placeholders ("replace with the official NBA wording"), so edit them.
- **Program Specific Outcome**: PSO1 ... of a programme under a regulation.
- **Course Outcome**: the canonical CO of a course in one **curriculum** version. It has a code (CO1 ...), a statement and a Bloom level. The course must be in the curriculum. The code is stored in capitals without spaces, is unique per course and curriculum, and can't change after the first save.

The CO tags already used elsewhere are Course Outcome codes:
- CIA Schedule questions: checked against the COs of the offering's curriculum.
- Question Bank Items: checked against the COs of the course in any curriculum.
- Answer Script Bundle questions (the ESE pattern examiners mark against): checked against the COs of the course in any curriculum. Set the CO of each question here; CO attainment counts the valuation marks through it.
- Feedback questions are generic forms. Their CO tag is matched to the offering's course outcome by code when scores are read.

A course with no Course Outcomes yet keeps free tags. A tag is checked only when it is set or changed, so an old tag (for example "CO1, CO2") never blocks saving something else on the document.

## CO-PO Matrix

One per course and curriculum. A new matrix is filled with every CO against every PO and PSO of the programme, all at 0. Set each correlation to 0 (none), 1 (low), 2 (medium) or 3 (high). **Fill Grid** adds cells for a CO or PSO created later. The HOD of the course's department approves it: use **Request Approval** (policy "CO-PO Matrix - HOD", seeded when the HOD position exists). The final approval submits the matrix. Record the Board of Studies resolution in **BoS Resolution** if there is one.

- The matrix can't be sent for approval, or submitted, while a course outcome of the course maps to nothing. That includes a CO added after the grid was filled.
- On approval, the POs and PSOs with no correlation in any approved matrix of the curriculum are shown as a warning.
- A revision is an amendment: cancel the approved matrix and amend it. Only one draft or approved matrix exists per course and curriculum.

**Versions.** A matrix belongs to its curriculum. An offering (a Student Group generated from a curriculum, field `oc_curriculum`) uses the approved matrix of that curriculum: a 2022-batch offering uses the R2022 matrix even after R2026 has its own. Service calls: `campus.curriculum.api.matrix_for_offering(offering)`, `matrix_for(course, curriculum)` and `course_outcomes(course, curriculum)`.

**Prints** on CO-PO Matrix:
- **CO-PO Matrix**: the grid, with the column average of the non-zero correlations.
- **Course Outcome Sheet**: each CO with its statement and Bloom level.

## CO-PO Coverage report

Filters: college and curriculum. For each PO and PSO it shows the number of courses mapping it and the total correlation, over the curriculum's approved matrices. An outcome with a zero total is shown as "Not mapped" and listed in the report message.

Deferred: copying matrices into a new curriculum version, and a Bloom Level master (the six levels stay a fixed list, as on CIA questions).

## Attainment (M03-03)

**Attainment Policy** (Masters), one per regulation:
- CO final = direct x **Direct Weight** + indirect x **Indirect Weight** (they add up to 100). Indirect is the course exit survey.
- Direct = CIA level x **CIA Share** + ESE level x **ESE Share** (they add up to 100).
- **Student Threshold**: a student attains a CO in a tool (CIA or ESE) when scoring at least this % of the marks of the questions tagged with it. Questions the student was absent for count in neither marks nor maximum.
- **Level Bands**: the level of a tool is the highest band whose minimum share of students it reaches (0 below the first band). Levels rise with their minimums.
- **CO Target Level**, **PO / PSO Target Level**, and **PO Indirect Weight**: a PO / PSO final is the mapped CO attainment x (100 - this) + the programme exit survey x this.
- The survey level is the mean rating as a share of 5, scaled to the top level (4.0 of 5 is 80 %, so 2.4 with three levels).

Example, the SXCCE rule: 80 / 20, direct 60 ESE + 40 CIA, threshold 60 %, bands L1 40 %, L2 50 %, L3 60 %.

**CO Attainment Run** (Transactions), one per course offering. Create it for the offering and press **Compute**, or use **Compute for a Term** on the list (every offering of the term with an approved CO-PO Matrix and a policy). Both run on the bulk runner. The run uses the policy of the offering's curriculum regulation:
- Students: those with the latest, ratified result of a released exam session for the offering. SA, WD and Pending rows are left out; an AB student counts in the CIA only.
- CIA: the CO-tagged question marks of the offering's mark sheet. ESE: the question marks of the two valuations that decide the final mark, tagged by the bundle's question pattern.
- Indirect: the closed course exit survey campaigns of the offering, with the minimum group size applied. A CO without a survey score gets its direct level as the final.
- Each CO row shows the CIA and ESE % of students and levels, direct, indirect, final, target and whether it is met. "Assessed" off means no tagged question was answered; "Survey Score" off means no indirect level.
- The run copies the policy values it used and keeps an **Input Snapshot**: the sessions, the students, and per CO and tool the questions and each student's marks, maximum and whether they attained. Submit it once computed; a submitted run never changes when the policy is edited. To recompute, cancel and amend it.

**PO Attainment Run** (Transactions): a programme, a batch (admission year) and optionally one academic year. Optionally choose a closed **Programme Exit Survey**, a feedback campaign whose Likert questions are tagged PO1, PSO1 ... (small groups are hidden). Press **Compute** (bulk runner). The run uses the batch's regulation and policy and its submitted CO runs. Per PO / PSO it computes sum(CO final x correlation) / sum(correlation) through each run's approved CO-PO Matrix, then the exit survey at the PO indirect weight. "Mapped" off means no assessed CO maps to the outcome.

**Reports**: CO Attainment by Course (filters: college, year, term, programme, course, faculty), PO Attainment by Program (programme, batch, year), and Attainment Target Gap (every CO, PO and PSO of submitted runs below its target, with the gap). **Print** on CO Attainment Run: **Course Attainment Sheet** (NBA course file): faculty, policy, and per CO the questions, % and levels.

Demo data: `bench --site <site> execute campus.tests.attainment_fixtures.seed_outcome_demo` (after `make_demo`) adds B.E. CSE POs and PSOs, CO1-CO3 of Data Structures in the R2022 curriculum, its HOD-approved matrix, and the R2022 (SXCCE) and R2026 policies.

Deferred: question choice ("answer any five") is not modelled, so an unanswered optional ESE question counts as 0; revaluation, moderation and grace change the ESE total, not the question marks; a Curriculum Settings default policy.
