# Tenant client runbook

## Initial configuration

1. Sign in and select the correct company. One user may belong to more than one
   tenant, so always verify the company name in the header.
2. Complete the public brand, contact and card-design settings. Publish a proof;
   do not treat a sample sheet as a production package.
3. Configure tenant-owned Brevo values in the tenant integration page.
4. Start Dotykačka connection from the tenant page, sign in to the tenant's POS
   account, choose the correct cloud and approve it. The Cloud ID remains locked
   until an explicit disconnect.
5. Never send a Refresh Token, Brevo API key or service-account file to another
   tenant or place it in a support message.

## Enrollment and follow-up

- Use the tenant-specific registration link or verified custom domain.
- A physical card must come from that tenant's available inventory.
- The enrollment screen shows redacted Wallet/POS/Brevo/email status. Retry a
  failed deterministic provider job from the enrollment detail. Email resend is
  a separate, explicit, audited generation.
- If a secure public status link expires, create a replacement through the
  authorized tenant flow; do not extend or edit the old database record.

## Printing

- Approve the published proof and accepted quote before submitting exactly one
  print request.
- Tenant users cannot download production ZIPs or mark cards printed/delivered.
- The platform operator centrally allocates card codes, produces and fulfills
  the order. Corrections are compensating events, never history edits.

