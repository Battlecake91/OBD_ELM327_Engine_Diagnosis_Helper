# Microsoft Artifact Signing setup

The Windows release workflow signs release builds with Microsoft Artifact Signing. Pull requests and normal pushes still build and test an unsigned executable; only tag builds and manual release runs use Azure credentials and publish a signed release.

## Important availability note

A **Public Trust** certificate profile is required to remove the Windows "Unknown publisher" warning for public downloads.

Microsoft currently allows Public Trust onboarding for:

- organizations in the United States, Canada, the European Union, and the United Kingdom;
- individual developers only in the United States and Canada.

An individual developer located in Germany therefore needs an eligible organization identity to obtain a Public Trust profile. A Private Trust profile does not make public Windows installations trust the publisher automatically.

## 1. Create the Azure resources

1. In the Azure subscription, register the `Microsoft.CodeSigning` resource provider.
2. Create an Artifact Signing account.
3. Complete a Public identity validation.
4. Create a `PublicTrust` certificate profile.
5. Note these values:
   - Azure subscription ID
   - Microsoft Entra tenant ID
   - Artifact Signing endpoint for the selected region, for example `https://weu.codesigning.azure.net/`
   - Artifact Signing account name
   - certificate profile name

Microsoft setup guide:

https://learn.microsoft.com/azure/artifact-signing/quickstart

## 2. Create the GitHub OIDC identity

Create or select a Microsoft Entra application registration. Add a federated credential with these values:

| Field | Value |
|---|---|
| Issuer | `https://token.actions.githubusercontent.com` |
| Subject | `repo:Battlecake91/OBD_ELM327_Engine_Diagnosis_Helper:environment:artifact-signing` |
| Audience | `api://AzureADTokenExchange` |

Using the GitHub environment in the subject gives tag builds and manually started releases one stable OIDC identity.

Assign the application's service principal the Azure role:

`Artifact Signing Certificate Profile Signer`

Scope the role as narrowly as possible, preferably to the certificate profile or its Artifact Signing account.

## 3. Configure the GitHub environment

In the GitHub repository, open:

`Settings -> Environments -> New environment`

Create an environment named exactly:

`artifact-signing`

Add these environment secrets:

| Secret | Value |
|---|---|
| `AZURE_CLIENT_ID` | Application (client) ID of the Entra application |
| `AZURE_TENANT_ID` | Microsoft Entra tenant ID |
| `AZURE_SUBSCRIPTION_ID` | Azure subscription ID |

Add these environment variables:

| Variable | Example |
|---|---|
| `ARTIFACT_SIGNING_ENDPOINT` | `https://weu.codesigning.azure.net/` |
| `ARTIFACT_SIGNING_ACCOUNT_NAME` | Artifact Signing account name |
| `ARTIFACT_SIGNING_CERTIFICATE_PROFILE_NAME` | Public Trust certificate profile name |

No client secret is required. Authentication uses GitHub OIDC and `azure/login`.

Optional environment protection rules can require manual approval before a release is signed.

## 4. Create a signed release

### Manual release

1. Open `Actions`.
2. Select `Windows executable and release`.
3. Select `Run workflow`.
4. Run it from `master`.
5. Enter a release tag such as `v3.1.0`.

### Tag-triggered release

```bash
git checkout master
git pull
git tag v3.1.0
git push origin v3.1.0
```

The release job performs these steps:

1. downloads the tested unsigned executable from the build job;
2. signs it with `azure/artifact-signing-action@v2`;
3. verifies the Authenticode signature;
4. calculates SHA-256 after signing;
5. uploads the signed artifact;
6. creates or updates the GitHub release.

## 5. Verify a downloaded executable

In PowerShell:

```powershell
Get-AuthenticodeSignature .\OBD_ELM327_Engine_Diagnosis_Helper.exe |
    Format-List Status, StatusMessage, SignerCertificate, TimeStamperCertificate
```

Expected status:

```text
Valid
```

The signed publisher identity removes the "Unknown publisher" warning. Microsoft Defender SmartScreen can still warn temporarily for a new application or certificate until it has established reputation.
