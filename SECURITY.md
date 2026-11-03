# Security policy

RAMMIT keeps Roblox logins on your PC, so security reports matter. This policy covers the RAMMIT app, the installer (`RAMMIT-Setup.exe`), the website ([rammit-pi.vercel.app](https://rammit-pi.vercel.app)) and the build and release files in this repository.

## Report a vulnerability privately

Use GitHub's private vulnerability reporting: **[Report a vulnerability](https://github.com/CBlockDigital/RAMMIT/security/advisories/new)**. You need a GitHub account. Only you and the repository's maintainers can see the report.

Please don't report security problems in public issues, discussions or pull requests.

Include:

- which part is affected (app, installer, website or release files) and its version (the app shows it at the bottom of the Settings panel, for example `RAMMIT v1.1.1 · Stable`);
- what an attacker could do, and what they need first (for example local access, a malicious theme or a crafted link);
- steps to reproduce, ideally with a small proof of concept.

**Never include real Roblox cookies (`.ROBLOSECURITY`), passwords, or files from a `Config` folder such as `Accounts.json`.** Describe the data instead, or use the throw-away demo accounts that the test harness creates (`Production/RAMMIT-Stable/Tests/UiHarness.py`).

## What happens next

- Reports are read and handled as the maintainers' time allows. RAMMIT is a free project without a dedicated security team, so there are no guaranteed response times.
- Confirmed problems are fixed in a new release and described in a GitHub Security Advisory. You'll be credited if you want to be.
- Please allow a reasonable time for a fix to be released before you publish details.

## Supported versions

| Version | Security fixes |
|---|---|
| The [latest release](https://github.com/CBlockDigital/RAMMIT/releases/latest) | Yes |
| Older releases | No. Update with `RAMMIT-Setup.exe`, or download the latest zip. |

## Scope

In scope: everything in this repository, that is `Production/RAMMIT-Stable` (the app), `Production/Installer` (the installer), `Web/Website` (the website) and the build and release scripts.

Please report these to their owners instead:

- **Roblox** (its website, apps, client and APIs): Roblox's own security reporting channel.
- **Bloxstrap and Fishstrap**: their own GitHub repositories.
- **Windows and the Microsoft Edge WebView2 Runtime**: the Microsoft Security Response Center.
- **GitHub and Vercel** (the platforms themselves): their own security programmes.

Known limits. These are not vulnerabilities by themselves, but tell us if you can make them worse:

- Saved logins are encrypted with Windows DPAPI for your Windows user. That stops a copied `Accounts.json` from being read on another PC or by another Windows user. It does not protect against malware that already runs as you.
- Themes are trusted code. A theme folder can contain JavaScript that runs in RAMMIT's window, so only install themes from people you trust.
- The executables are not code-signed yet, so Windows SmartScreen may warn about them.

## Verify your download

GitHub shows a SHA-256 digest next to every file on a release page, and each zip also comes with a `.sha256` file. To check a file in PowerShell:

```powershell
Get-FileHash .\RAMMIT-Setup.exe -Algorithm SHA256
```

Compare the result with the digest on the [release page](https://github.com/CBlockDigital/RAMMIT/releases/latest). A matching hash shows the file wasn't damaged or swapped after it was published there. Only download RAMMIT from this repository's releases, or from the links on [rammit-pi.vercel.app](https://rammit-pi.vercel.app).

## More

- [Production/RAMMIT-Stable/SECURITY.md](Production/RAMMIT-Stable/SECURITY.md): the security audit of RAMMIT 1.0.0 and what it fixed.
- [rammit-pi.vercel.app/security/](https://rammit-pi.vercel.app/security/): this policy on the website, plus [security.txt](https://rammit-pi.vercel.app/.well-known/security.txt).
