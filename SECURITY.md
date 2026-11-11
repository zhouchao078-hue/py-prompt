# Security Policy

## Reporting a vulnerability

Please do not disclose security issues in a public issue.

Use GitHub's private vulnerability reporting for this repository. Include:

- affected version or commit
- reproduction steps
- potential impact
- any suggested mitigation

Do not include real API keys, access codes, session cookies, personal data, or
production database contents in a report.

## Public deployment

The application defaults to local-only mode. Before exposing it to the internet:

- set `PUBLIC_MODE=true`
- configure a strong `DEMO_ACCESS_CODE`
- configure a random `THREAD_SECRET`
- keep `DEMO_READONLY_LIBRARY=true` unless public writes are intentional
- provide secrets through the environment or an ignored `.env` file
- use HTTPS with the supplied Caddy configuration

Never commit `.env`, SQLite databases, generated images, logs, API keys, or
session recovery codes.
