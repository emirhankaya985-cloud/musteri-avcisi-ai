# Optional Gmail API transport

`leadhunter.gmail_api` is an isolated OAuth 2.0 Gmail API transport. It is
not wired into `automatic_mail`, the owner-approved mail worker, or any
GitHub workflow. The adapter refuses to run unless `GMAIL_API_ENABLED=true`;
that variable is not present in the current deployment configuration.

The adapter expects these runtime settings:

- `GMAIL_OAUTH_CLIENT_ID`
- `GMAIL_OAUTH_CLIENT_SECRET`
- `GMAIL_OAUTH_REFRESH_TOKEN`
- `GMAIL_OAUTH_SCOPE=https://www.googleapis.com/auth/gmail.send`
- `GMAIL_SENDER_ADDRESS`
- `GMAIL_API_ENABLED=true` (leave unset until a separately reviewed integration)

The account owner must create/configure an OAuth client in Google Cloud,
complete Google's authorization flow, and grant the narrow `gmail.send` scope.
The refresh token belongs in GitHub Secrets; never paste it into chat, code,
logs, issue text, or this document. The configured scope string documents the
expected grant but does not prove the token's grant; Google's API response is
the runtime authority. Google classifies `gmail.send` as a sensitive scope,
and OAuth verification requirements depend on the app's deployment/use case.

On a send call the adapter first exchanges the refresh token for an access
token, sends one RFC 2822 message through Gmail API, and returns only the
`id` from a successful Gmail API response. Missing IDs and all provider/network
errors fail closed with redacted exceptions. There is no SMTP fallback and no
automatic enablement.

This transport is intentionally not a policy gate. A future business-mail
integration must first pass the existing per-recipient legal/IYS/opt-out,
deduplication, idempotency, quota, and sender-reputation checks before calling
it. SMTP's historical acceptance records remain unchanged and are not Gmail
API message IDs or inbox-delivery proof. No email was sent while adding this
module.

Official references:

- [Gmail API `users.messages.send`](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/send)
- [Gmail API OAuth scopes](https://developers.google.com/workspace/gmail/api/auth/scopes)
- [Gmail API server-side OAuth flow](https://developers.google.com/workspace/gmail/api/auth/web-server)
