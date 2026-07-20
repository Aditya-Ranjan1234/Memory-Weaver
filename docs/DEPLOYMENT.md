# Secure Vercel Deployment

## Required Production Variables

Add these under **Vercel Project > Settings > Environment Variables** and scope them to **Production**:

```text
DATABASE_URL
MW_GOOGLE_CLIENT_ID
MW_SESSION_SECRET
OPENAI_API_KEY
MW_INTERVIEW_MODEL=gpt-4o-mini
MW_TRANSCRIBE_MODEL=gpt-4o-mini-transcribe
MW_ALLOWED_HOSTS=memories-weaver.vercel.app
```

`MW_SESSION_SECRET` must contain at least 48 characters. Generate it inside the virtual environment:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Do not configure `MW_DEV_AUTH` in Vercel.

## Neon Variables

The Neon integration may create provider-prefixed variables such as `DATABASE_POSTGRES_URL`, `DATABASE_POSTGRES_HOST`, and `DATABASE_PGUSER`. They can remain, but the application reads only `DATABASE_URL` at runtime.

`DATABASE_URL` must be the pooled Neon URL. `DATABASE_URL_UNPOOLED` is used only when running Alembic migrations and does not need to be available to the application Function.

Do not expose the production database to arbitrary Preview deployments. Either scope production Neon variables to **Production** or configure Neon preview branches with separate credentials.

## Database Migration

Run migrations locally from the virtual environment using the direct Neon URL:

```powershell
.\.venv\Scripts\Activate.ps1
python -m alembic upgrade head
python -m alembic current
```

Migrations are intentionally not executed during every Vercel build or cold start.

## Google Authentication

Create a Google Identity Services Web client and configure these Authorized JavaScript origins:

```text
http://127.0.0.1:8000
http://localhost:8000
https://memories-weaver.vercel.app
```

Add custom domains separately. The app needs only the Web client ID. Do not upload or commit the downloaded OAuth client JSON or client secret.

After saving the Google and Vercel settings, redeploy the Production deployment. Environment-variable changes do not alter an already-built deployment.

## Sign In And Add Your Data

1. Open `https://memories-weaver.vercel.app/login`.
2. Select **Continue with Google** and choose the Google account that will own the archive.
3. On the private dashboard, select **Add story**.
4. Choose **Memory** or **Timeline Event**, then add a title, story, relevant tags, and an optional year.
5. Select **Record voice** to dictate instead of typing. Stop the recording and wait for the transcript before saving.
6. Select **AI interview** when you want the conversational interviewer to ask follow-up questions and shape the answers into a story.
7. Select **Invite family** to create a seven-day link. Send that link privately; after the relative signs in and accepts it, both accounts can see the combined family archive.

Stories are stored in Neon under the signed-in Google account. The public landing-page demo is intentionally separate from private account data.

If **Continue with Google** is absent, confirm `MW_GOOGLE_CLIENT_ID` is set in Vercel Production and redeploy. If Google reports an origin error, add the exact deployed origin to the Web client in Google Cloud. If AI or transcription returns an error, replace `OPENAI_API_KEY` with an active server-side key and redeploy.

## Deployment Checklist

1. Rotate any credential that has appeared in chat, screenshots, logs, or shell history.
2. Apply Alembic migrations.
3. Confirm Preview deployments do not use the production database.
4. Add the required Production variables.
5. Redeploy after any environment-variable change.
6. Verify `/health`, Google login, story isolation, voice transcription, and family invitations.
7. Enable GitHub private vulnerability reporting, secret scanning, and push protection in repository settings when available.
