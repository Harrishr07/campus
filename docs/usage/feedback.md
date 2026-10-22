# Feedback (P3-T07, M01-05, M03-03, M07-04)

## Forms and campaigns

1. **Feedback Form** (IQAC > Feedback): the questions. Each question is one of three types:
   - **Likert**: a rating from 1 (strongly disagree) to 5 (strongly agree);
   - **Choice**: one option, listed one per line;
   - **Text**.

   A Likert question can carry a **CO** tag (CO1, CO2, ...), the same tags used on CIA questions. Set-up seeds placeholder forms for you to reword: Course Exit Survey (CO1-CO5), Programme Exit Survey, Student Satisfaction Survey, and Curriculum Feedback for Students, Teachers, Employers and Alumni.
2. **Feedback Campaign**: set the form, the college, the **Audience**, the window (**Opens On** / **Closes On**), **Anonymous** (on by default) and **Remind Every (Days)**.
   - **Course Offering Students**, **Parents** and **Teachers**: the students, their guardians, or the instructors of the **Course Offering** (a course Student Group). You can also pick a messaging **Audience Rule** of the college instead.
   - **Students**: needs an Audience Rule or a course offering.
   - **Alumni** and **Employers**: list them as **Invitees** (External Members). Each gets a signed link and needs no login.

   Once a response exists, the form, audience, offering, instructor, college and anonymity can't change.
3. **Send Invitations** (button) sends the `Feedback Invitation` message to everyone the campaign addresses, through the bulk runner. Reminders (`Feedback Reminder`) go out every N days after the opening, until the window closes. They go to everyone addressed, including people who have already answered (see Anonymity). Edit the wording in Message Template.
4. Students and parents see open campaigns under **Feedback** in /campus-portal. Everyone answers at `/feedback/<campaign>`.
5. **Action Taken** and **Action Taken Report** on the campaign record what the college did. Feedback Campaign is listed under Evidence Sources in Campus Settings, with the report as its file, so **Attach as Evidence** works for NAAC 1.4.

## Anonymity

In an anonymous campaign, a **Feedback Response** keeps:
- the campaign, the form, the offering and instructor (copied from the campaign);
- the day (no time);
- the answers.

It keeps no user, owner, respondent record or IP. It is written by a plain insert, so there is no Version, document follow, comment or notification. Its owner is "Guest" and its times are midnight of the day.

One response per respondent is enforced by **Feedback Response Token**:
- its name is a keyed hash (the site's encryption key) of campaign and respondent;
- its owner is "Guest" and its times are the campaign's opening day;
- it keeps nothing else, so it can't be matched to a response.

Only System Manager can open single responses or tokens. Staff see the analysis.

Reminders go to everyone addressed so that the Message Log never shows, day by day, who has answered.

A **named** (not anonymous) campaign also stores the respondent on the response.

- An anonymous campaign whose audience is smaller than the minimum group size (counted in people: a student's record and their login are one person) takes no answers and sends no invitations: its responses keep the offering and instructor, which could point to the few people addressed. Widen the audience or make it named.
- A user who answers to several records of the audience (e.g. a User and a Student key) claims all of them at once.
- A refused answer gives a message that names no answer. The posted campaign, answers, member and signature are taken out of the request's form data before anything else runs (a call missing them is refused the same way, not with a server error), so no Error Log or request error snapshot of that request holds them. Only a refusal or the generic error ever leaves the answer call: any other failure, even when its rollback or its Error Log write fails too, writes at most one Error Log "Feedback response failed" with the class name only, empty metadata (no form data, no user), owner "Guest" and the day's midnight as its time, and the respondent sees a generic error.

Site settings a college collecting real feedback must keep:
- **developer_mode off**: in developer mode Frappe stores every request error with its stack locals, which hold the posted answers and the respondent.
- **view tracking off** for Feedback Response (it is off in the DocType).
- **recorder off** (Frappe's request recorder): it stores every SQL query of a request with the user, including the answers being inserted.
- **telemetry off** (no Sentry DSN / `enable_telemetry` unset): Frappe sends each logged error with its request data to the telemetry service.
- **do not rotate the site encryption key while a campaign is open**: tokens are keyed by it, so after a rotation the same people could answer again.

A System Manager who reads Message Log sees each invitee's signed link and, by opening it, whether that invitee has answered (not what).

## Analysis

**Feedback Analysis** (report; IQAC Coordinator, System Manager, Principal) groups by **Question**, **Course** (offering) or **Faculty** (the campaign's instructor) and shows the response count and average rating:
- per question, the 1-5 distribution, or the counts of each choice;
- free-text answers are counted but never listed.

Only **closed** campaigns (window ended before today) of the colleges you are permitted for are counted, so figures don't move while answers come in. A closed campaign with responses cannot reopen.

Each (campaign, question) cell, and then each (campaign, group) cell, with fewer responses than **Campus Settings > Feedback Minimum Group Size** (seeded 5, and a blank value means 5; never below 3: settings refuse less and code treats a lower stored value as 3) is dropped **before** cells are pooled. So an optional question answered by a few never shows as a Course or Faculty figure minus the question rows. A small campaign therefore never shows as the difference between two filters (say "all campaigns" minus "the big campaign"). The report says how many cells were hidden.

The minimum group size hides small groups. It does not protect a group whose members all gave the same rating: if all 5 rated 1, each of them did.

`campus.iqac.api.indirect_co_scores(offering)` returns the indirect CO attainment of an offering: `{CO: {responses, average, percent, suppressed}}` from the CO-tagged Likert answers of its closed **Course Offering Students** campaigns. Those campaigns take their audience from the offering itself, never from an Audience Rule. **percent** is the mean rating as a share of 5. Small (campaign, question) and (campaign, CO) cells are dropped before pooling. A CO with no cell left is suppressed and its figures are None.

## Deferred

- Self-appraisal "Student Feedback" quantity (campus.faculty.self_appraisal.phase3_quantity), and NAAC 1.4.1 / 1.4.2 data points from campaigns.
- Listing free-text comments to staff.
- Message Log keeps the rendered invitation, including an invitee's signed link. A user who can read Message Log could answer for that invitee once.
- Database server logs (binary / general log) and backups are outside the app's control: insert order there is not anonymised.
