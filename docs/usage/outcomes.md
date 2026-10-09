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
- Feedback questions are generic forms. Their CO tag is matched to the offering's course outcome by code when scores are read.

A course with no Course Outcomes yet keeps free tags.

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
