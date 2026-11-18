# ScholarPulse authentication setup

This update adds Gmail password recovery and Google sign-in while retaining the existing email-verification registration flow.

## 1. Configure environment variables

Copy `.env.example` to `.env` and fill in the existing database, session, Gemini, and SMTP settings. For Gmail SMTP, use a Google App Password (not your normal Google password). Keep `.env` private and never commit it.

Add Google OAuth credentials:

```env
GOOGLE_CLIENT_ID=your_google_oauth_client_id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_google_oauth_client_secret
GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/auth/google/callback
PASSWORD_RESET_TTL_MINUTES=15
```

## 2. Create Google OAuth credentials

1. Open https://console.cloud.google.com/auth/clients and select/create a Google Cloud project.
2. Configure the OAuth consent screen and add the accounts that may test the app if the app remains in Testing mode.
3. Create an OAuth client ID with application type **Web application**.
4. Add this exact Authorized redirect URI: `http://localhost:8000/api/v1/auth/google/callback`.
5. Copy the Client ID and Client Secret into `.env`.
6. Enable the Google identity / OAuth APIs if Google Cloud prompts you.

The application requests the OpenID Connect scopes `openid email profile`. Google sign-in requires a verified Gmail address. New users are created as verified student accounts only after checking the consent box in ScholarPulse. Existing accounts with the same verified Gmail address are signed in.

## 3. Start the application

```bash
docker compose up -d --build
docker compose logs -f backend
```

Alembic automatically applies migration `0004_password_reset` during container startup. Do not delete the MySQL volume to apply this migration.

## 4. Password recovery

From the sign-in panel choose **Forgot password?**. Enter the verified Gmail address, retrieve the six-digit code from the email, and submit it with a new password. Codes expire after `PASSWORD_RESET_TTL_MINUTES`, are single-use, and allow at most five attempts. The request endpoint uses a generic response to avoid revealing whether an account exists.

## 5. Production deployment

Use HTTPS, set `GOOGLE_REDIRECT_URI` to the public HTTPS callback URL, register that exact URI in Google Cloud Console, and set `SESSION_COOKIE_SECURE=true`. Keep Google client secret, SMTP password, session secrets, and Gemini API key server-side.
