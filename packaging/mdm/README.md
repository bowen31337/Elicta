# Fallback distribution & EDR whitelisting (PRD NFR-3.6, NFR-3.7)

Per the architecture doc (§11.3) and PRD requirements table:

| Req | Requirement |
|---|---|
| NFR-3.5 | MDM distribution preferred on both desktop platforms — Jamf/Intune on macOS with a PPPC profile, Intune on Windows |
| NFR-3.6 | `.dmg` and MSI available as fallback distribution |
| NFR-3.7 | EDR whitelisting agreed with IT on both platforms before pilot — an unknown binary opening a loopback audio stream will be flagged |

Not every organization running this app has MDM configured. This directory
makes sure the fallback path — a person directly downloading and running an
installer — is a real, verified distribution channel rather than an
afterthought:

- The existing CI pipeline (`.github/workflows/build.yml`,
  `.github/workflows/sign-macos.yml`) already builds a notarised macOS `.dmg`
  (plus its `.app` bundle) and signed Windows `.msi`/`.exe` installers on
  every tag push. Those are CI build artifacts with 14-day retention — not
  something a user, or IT security, would ever find.
- [`scripts/prepare-release-assets.sh`](scripts/prepare-release-assets.sh)
  takes that CI output, **fails loudly if the `.dmg`, an `.msi`, the `.app`
  bundle, or a Windows `.exe` is missing** (a partial fallback, or an
  undocumented binary, is worse than an obvious build failure), and
  assembles the verified set into a release-ready bundle containing:
  - `SHA256SUMS.txt` — hashes of the installer packages themselves, for
    download integrity (NFR-3.6).
  - `EDR-WHITELIST.txt` — hashes of the binaries that actually *execute*
    after install (the macOS app's Mach-O executable, the Windows installer
    executable(s)). This is what an EDR/antivirus whitelisting policy keys
    on, and is the record IT needs before pilot (NFR-3.7).
- [`.github/workflows/release-fallback.yml`](../../.github/workflows/release-fallback.yml)
  runs after the macOS sign/notarize workflow completes, calls that script,
  and publishes the result — installers, checksums, and the EDR whitelisting
  record — as GitHub Release assets, so the release itself is the persisted
  record of what to whitelist and how to verify it.

## Why this doesn't duplicate build.yml / sign-macos.yml

`sign-macos.yml` calls `build.yml` as a reusable workflow, so a single
`Sign & Notarize macOS Build` run already contains the notarised macOS
bundle *and* both Windows-architecture MSI bundles (`build-windows` runs as
part of the same call). `release-fallback.yml` only downloads and republishes
what that run produced — it does not rebuild or re-sign anything, so signing
identity and notarization logic stay owned by their existing workflows.

## Testing

```
./packaging/mdm/scripts/test-prepare-release-assets.sh
```

Runs entirely against temp directories with fixture files — no network
access, no real build artifacts required.
