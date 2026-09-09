# Historical incident evidence

All logs contain synthetic lab data. Do not edit the originals.

- access.log: NGINX client-facing requests, JSON lines.
- error.log: NGINX diagnostic text.
- application.log: structured app requests/events, JSON lines.
- Time zone: UTC. Correlate using request_id, timestamp and upstream/instance.
- request_time is seconds; duration_ms is milliseconds.
- Comma-separated upstream values describe attempts for one client request.
- A log record is not always a distinct client request. Handle duplicates and malformed lines.
- These files describe a historical incident, not the current environment's full issue list.

Complete every question in ../log_analysis.md. Include reproducible commands/scripts,
parse exclusions, counts, a timeline and evidence. Do not manually count or invent conclusions.
