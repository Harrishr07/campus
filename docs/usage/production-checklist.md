# Production checklist (PR-05)

Two commands, both read-only, to run before go-live and after every upgrade. Never run them against a development
site expecting a pass: `education.localhost` and `campus.localhost` are development sites and fail on purpose.

## 1. Site check

```
bench --site <site> execute campus.setup.site_check.run
```

One line per item, `OK`, `WARN` or `FAIL`. The production profile (default) exits 1 when any item fails, so it can
gate a deploy script. `--kwargs '{"profile": "development"}'` prints the same lines and always exits 0.

| Item | Fails when | Fix |
|---|---|---|
| developer_mode | `developer_mode` is on in site_config | `bench --site <site> set-config developer_mode 0` |
| allow_tests | `allow_tests` is on | `bench --site <site> set-config allow_tests 0` |
| telemetry (WARN) | System Settings "Enable Telemetry" is on | System Settings > Telemetry |
| request_recorder | The request recorder is recording | Recorder page > Stop |
| scheduler | Scheduler disabled, paused or in maintenance mode | `bench --site <site> enable-scheduler`; unset `pause_scheduler` / `maintenance_mode` |
| email_account | No Email Account with outgoing enabled and "Default Outgoing" | Create one and tick both |
| whatsapp | WhatsApp Settings has no default outgoing account, or the account is not Active | Fill WhatsApp Settings; set the account Active |
| backups | Backups are not encrypted, `backup_limit` is 0, or `encryption_key` is missing from site_config | System Settings > Backups; keep `encryption_key` safe: a restore needs it |
| backup_age (WARN) | No backup file, or the newest is over 2 days old | Check the backup cron |
| error_log | More than 10 Error Log rows in the last day | Read them (Error Log list) and fix the cause |
| mail_queue | An Email Queue row went to Error in the last day | Email Queue list, filter Status = Error |

## 2. Permission matrix

```
bench --site <site> execute campus.setup.permission_matrix.run
```

Writes `docs/usage/permission-matrix.csv` (every campus DocType and Report, every role, the flags read, write, create,
delete, submit, cancel, export, print, share and the permission level) and raises with the list of defects when a rule
is broken. Commit the CSV after a permission change: its diff is the review of the change. The rules, also run by
`campus.tests.test_hardening`:

- Only System Manager deletes a record kept for history (Lifecycle Transition, Official Document, Completion Check,
  results, certificates, the financial and audit ledgers; the list is `HISTORY_KEPT` in the module).
- Student, Guardian and Guest read only the DocTypes in `STUDENT_READABLE`, and share or export none.
- Confidential DocTypes (the restricted-record hook list, CO Attainment Snapshot, the exam-confidential set) are read
  only by the roles in `CONFIDENTIAL_READERS`. A new confidential DocType must be added there, or the check fails.

## 3. Backup and restore drill

Run once before go-live, and after any change of hosting. A backup that has never been restored is not a backup.

1. Back up with files, on the live bench:
   `bench --site <site> backup --with-files`
   The files land in `sites/<site>/private/backups/`: database dump, `-files.tar`, `-private-files.tar` and
   `-site_config_backup.json`. Copy them off the server.
2. Note the counts to compare, on the live site:
   `bench --site <site> mariadb -e "select (select count(*) from tabStudent) students, (select count(*) from \`tabStudent Result\`) results, (select count(*) from tabFile) files"`
   Add any other DocType the college cares about (Fee Structure, Sales Invoice, Official Document).
3. Create a scratch site (never restore onto the live site or a development site):
   `bench new-site restore-drill.localhost --mariadb-user-host-login-scope=%`
   then restore into it:
   `bench --site restore-drill.localhost restore <database.sql.gz> --with-public-files <files.tar> --with-private-files <private-files.tar> --encryption-key <backup_encryption_key>`
   The backup encryption key is `backup_encryption_key` in the live site_config. Also copy `encryption_key` from the
   backup's `site_config_backup.json` into the scratch site's `site_config.json`, or stored passwords and API
   secrets cannot be decrypted.
4. `bench --site restore-drill.localhost migrate`, then run the count query of step 2 on the scratch site. The numbers
   must match. Open a Student Result and a private attachment in the browser: they must load.
5. `bench --site restore-drill.localhost execute campus.setup.site_check.run --kwargs '{"profile": "development"}'`
   to confirm the restored site's own state (a scratch site is expected to fail email and WhatsApp).
6. Drop the scratch site: `bench drop-site restore-drill.localhost`. Record the date, the backup file names and the
   counts compared.
