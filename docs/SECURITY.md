# Security Policy

## Reporting a Vulnerability

Please report vulnerabilities privately through GitHub's **Security** tab using a private vulnerability report. Do not open a public issue containing credentials, personal stories, database URLs, invitation tokens, or reproduction data from a real family account.

Include the affected route, impact, reproduction steps using synthetic data, and any suggested remediation. Credentials included in a report should be revoked immediately.

## Secrets

- Production secrets belong only in Vercel Environment Variables.
- Local secrets belong only in `.env.local`, which is ignored by Git and Vercel.
- Google OAuth client JSON, private keys, databases, and logs must never be committed.
- If a secret appears in chat, logs, screenshots, commits, or pull requests, rotate it rather than merely deleting it.

## Data Protection

Memory Weaver stores personal stories, private story photos, and account identifiers. Photos are served through authenticated routes only; connected family members can view them, but only the owner can replace them. Production and preview deployments must use separate databases. Invitation tokens are one-time, expire after seven days, are stored as SHA-256 hashes, and are passed through URL fragments so they do not enter request logs.

## Supported Version

Security fixes are applied to the latest commit on `main`.
