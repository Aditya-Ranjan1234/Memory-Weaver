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

Memory Weaver stores personal stories, revisions, private photographs, audio, transcripts, comments, capsules, family relationships, and account identifiers. Media is served through authenticated routes only. Connected family members can view shared media; archive roles control who can edit stories, and only media owners can delete files. Story deletion is recoverable until the owning account is permanently deleted. Complete ZIP and JSON exports are available before deletion.

Production and preview deployments must use separate databases. Invitation tokens are one-time, expire after seven days, are stored as SHA-256 hashes, and are passed through URL fragments so they do not enter request logs. Offline drafts and queued stories are stored in the signed-in browser's local storage; users on shared devices should sign out and clear site data when appropriate.

## Supported Version

Security fixes are applied to the latest commit on `main`.
