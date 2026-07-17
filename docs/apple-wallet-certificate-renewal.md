# Apple Wallet Pass Type ID certificate renewal

The platform signs passes for `pass.club.mbstudio.online` under Apple Team ID
`W66MF62243`. The current Pass Type ID certificate expired on 25 June 2026.
`AppleWWDR.pem` remains valid until 2030 and does not need replacement for this
renewal.

This procedure changes protected signing files only. It does not modify any
tenant, customer, card, Wallet identity, or database row.

## 1. Create a certificate signing request on a trusted Mac

Open **Keychain Access → Certificate Assistant → Request a Certificate From a
Certificate Authority**. Enter the Apple Developer account email and a clear
common name, leave the CA email blank, select **Saved to disk**, and save the
`.certSigningRequest` file. Keep the private key that Keychain Access creates;
the downloaded certificate is unusable for signing without that matching key.

## 2. Issue the replacement in Apple Developer

Sign in as an Account Holder or Admin and open **Certificates, Identifiers &
Profiles**:

1. Open **Certificates** and select **+**.
2. Under **Services**, select **Pass Type ID Certificate**.
3. Select the existing Pass Type ID `pass.club.mbstudio.online`. Do not create a
   different identifier.
4. Upload the CSR and download the resulting `.cer` certificate.
5. Double-click the `.cer` file to install it in Keychain Access.

In **My Certificates**, the new Pass Type ID certificate must expand to show
its private key. Export that certificate and private key together as a
password-protected `.p12` file.

## 3. Convert and verify the deployment files

Work in a private temporary directory and use a restrictive file-creation mask:

```bash
umask 077
openssl pkcs12 -in renewed-pass-certificate.p12 -clcerts -nokeys -out certificate.pem
openssl pkcs12 -in renewed-pass-certificate.p12 -nocerts -nodes -out key.pem
openssl x509 -in certificate.pem -noout -subject -issuer -dates
diff <(openssl x509 -in certificate.pem -pubkey -noout) <(openssl pkey -in key.pem -pubout)
chmod 600 certificate.pem key.pem
```

The `diff` command must produce no output. The certificate subject must contain
`UID=pass.club.mbstudio.online` and `OU=W66MF62243`, and `notAfter` must be in
the future.

## 4. Deploy without losing the previous material

Stop Wallet generation briefly. Make a timestamped, access-restricted backup
of the current `certificate.pem` and `key.pem`, then replace only these files:

```text
local-data/mypass_template/certificate.pem
local-data/mypass_template/key.pem
```

Keep `AppleWWDR.pem` unchanged. Never commit the `.p12`, private key, CSR, or
certificate files to Git. Restart the web and worker services, then run the
Apple Wallet check from `/dotykacka/platform/system-connections`. It validates
the expiry, Pass Type ID, Team ID, and certificate/private-key match before
reporting success.

## Official Apple instructions

- [Create Wallet identifiers and certificates](https://developer.apple.com/help/account/capabilities/create-wallet-identifiers-and-certificates)
- [Create a certificate signing request](https://developer.apple.com/help/account/certificates/create-a-certificate-signing-request)
- [Build and sign a Wallet pass](https://developer.apple.com/documentation/walletpasses/building-a-pass)
