#!/usr/bin/env bash
# generate-pppc-profile.sh — render the PPPC configuration profile (PRD
# NFR-3.5) that pre-grants Microphone and Screen Recording to the notarised
# macOS build, so Jamf/Intune can push it and no pilot user ever sees a TCC
# prompt.
#
# Usage: generate-pppc-profile.sh <output-path>
#
# Required environment:
#   TEAM_ID     Apple Developer Team ID the build is signed with (the same
#               identity sign-macos.yml re-signs with via
#               APPLE_SIGNING_IDENTITY / notarises via APPLE_TEAM_ID). The
#               profile grants access by code requirement, not by binary
#               hash, so it keeps matching every signed build without being
#               regenerated on each release — unlike EDR-WHITELIST.txt
#               (NFR-3.7), which intentionally pins exact hashes.
#
# Optional environment:
#   BUNDLE_ID   App bundle identifier (default: com.elicta.desktop)
#   ORG_NAME    Organization name recorded in the profile (default: Elicta)
#   PROFILE_UUID / TCC_PAYLOAD_UUID
#               Override the generated PayloadUUIDs (useful for
#               reproducible test fixtures); default to a fresh uuidgen each.
#
# The profile must be delivered via MDM (PayloadScope System) — PPPC
# payloads are silently ignored if a user just double-clicks the .mobileconfig,
# which is why this is a distinct artifact from the NFR-3.6 fallback
# installers rather than something bundled into the .dmg.

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $(basename "$0") <output-path>" >&2
  exit 2
fi

output_path="$1"

if [[ -z "${TEAM_ID:-}" ]]; then
  echo "error: TEAM_ID must be set — the PPPC code requirement has to name the Developer ID team the build is signed with" >&2
  exit 1
fi

bundle_id="${BUNDLE_ID:-com.elicta.desktop}"
org_name="${ORG_NAME:-Elicta}"
profile_uuid="${PROFILE_UUID:-$(uuidgen)}"
tcc_payload_uuid="${TCC_PAYLOAD_UUID:-$(uuidgen)}"

# Matches what `codesign -d -r-` prints for a Developer ID Application
# signed build: true for any binary signed by this bundle ID + team,
# regardless of which specific release produced it.
code_requirement="identifier \"${bundle_id}\" and anchor apple generic and certificate leaf[subject.OU] = \"${TEAM_ID}\""

mkdir -p "$(dirname "$output_path")"

cat > "$output_path" <<PROFILE
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>PayloadContent</key>
	<array>
		<dict>
			<key>PayloadType</key>
			<string>com.apple.TCC.configuration-profile-policy</string>
			<key>PayloadIdentifier</key>
			<string>${bundle_id}.pppc.tcc</string>
			<key>PayloadUUID</key>
			<string>${tcc_payload_uuid}</string>
			<key>PayloadVersion</key>
			<integer>1</integer>
			<key>PayloadDisplayName</key>
			<string>${org_name} Microphone &amp; Screen Recording (PPPC)</string>
			<key>PayloadEnabled</key>
			<true/>
			<key>Services</key>
			<dict>
				<key>Microphone</key>
				<array>
					<dict>
						<key>Identifier</key>
						<string>${bundle_id}</string>
						<key>IdentifierType</key>
						<string>bundleID</string>
						<key>CodeRequirement</key>
						<string>${code_requirement}</string>
						<key>StaticCode</key>
						<false/>
						<key>Allowed</key>
						<true/>
						<key>Comment</key>
						<string>PRD NFR-3.5: live meeting capture needs microphone access without a TCC prompt on managed devices.</string>
					</dict>
				</array>
				<key>ScreenCapture</key>
				<array>
					<dict>
						<key>Identifier</key>
						<string>${bundle_id}</string>
						<key>IdentifierType</key>
						<string>bundleID</string>
						<key>CodeRequirement</key>
						<string>${code_requirement}</string>
						<key>StaticCode</key>
						<false/>
						<key>Allowed</key>
						<true/>
						<key>Comment</key>
						<string>PRD NFR-3.5: ScreenCaptureKit loopback capture needs Screen Recording access without a TCC prompt on managed devices.</string>
					</dict>
				</array>
			</dict>
		</dict>
	</array>
	<key>PayloadDisplayName</key>
	<string>${org_name}: Microphone &amp; Screen Recording (PPPC)</string>
	<key>PayloadDescription</key>
	<string>Pre-grants ${org_name} (${bundle_id}) Microphone and Screen Recording access for managed deployment. Must be installed via MDM (Jamf/Intune) — PPPC payloads are ignored when a profile is installed manually.</string>
	<key>PayloadIdentifier</key>
	<string>${bundle_id}.pppc</string>
	<key>PayloadOrganization</key>
	<string>${org_name}</string>
	<key>PayloadRemovalDisallowed</key>
	<false/>
	<key>PayloadScope</key>
	<string>System</string>
	<key>PayloadType</key>
	<string>Configuration</string>
	<key>PayloadUUID</key>
	<string>${profile_uuid}</string>
	<key>PayloadVersion</key>
	<integer>1</integer>
</dict>
</plist>
PROFILE

echo "wrote PPPC profile to $output_path"
