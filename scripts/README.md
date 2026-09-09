# Candidate scripts

Implement the root validate.py, failure_test.py, backup.sh and restore.sh placeholders,
or document equivalent script names. Write your own .github/workflows/ci.yml.

- Validation: public access, endpoints, both/all backends, dependencies, network isolation and port exposure.
- Failure test: stop one backend, measure availability/errors, restore it, prove recovery.
- Backup/restore: use real PostgreSQL backup data and prove an actual restore.
- Use bounded waits, useful output, non-zero failures and safe cleanup.
- Never target an unrelated Compose project, container or volume.
- video_challenge.sh and scripts/video_challenge.py are supplied exercise tooling.
  Keep them unchanged and run the challenge only as directed in the brief.
