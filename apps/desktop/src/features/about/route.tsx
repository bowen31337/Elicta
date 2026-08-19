import '../prep/screens.css';

import { Mark, ScreenEyebrow } from '../../ui/Mark';
import { buildInfo } from './useBuildInfo';
import { updateChannelSummary, useProvenance } from './useProvenance';

/**
 * Journey 12 — how this app got onto the machine, and what it was granted.
 *
 * Most "About" screens are a version string and a copyright line. This one
 * carries the answers an operator or an IT reviewer actually needs mid-pilot:
 * whether the build is signed, how it was installed, and which OS permissions
 * it holds. On macOS a meeting tool asking for Screen Recording generates the
 * same support question over and over, so the screen answers it before it is
 * asked rather than leaving the operator to find System Settings.
 */
export interface Permission {
  readonly name: string;
  readonly granted: boolean;
  readonly why: string;
}

export interface AboutScreenProps {
  readonly version: string;
  readonly platform: string;
  readonly architecture: string;
  /** `null` when the OS could not be asked — rendered distinctly from `false`. */
  readonly signed: boolean | null;
  readonly signedBy: string | null;
  readonly installedVia: 'MDM' | 'Direct download' | 'Unknown';
  readonly updateChannel: string;
  readonly permissions: readonly Permission[];
}

export function AboutScreen({
  version,
  platform,
  architecture,
  signed,
  signedBy,
  installedVia,
  updateChannel,
  permissions,
}: AboutScreenProps) {
  const missing = permissions.filter((permission) => !permission.granted);

  return (
    <main className="screen" aria-labelledby="about-title">
      <header className="screen-head">
        <ScreenEyebrow>About</ScreenEyebrow>
        <div className="about-identity">
          <Mark size={56} />
          <div>
            <h1 className="t-large-title" id="about-title">
              Elicta
            </h1>
            <p className="t-footnote tabular">
              {version} · {platform} {architecture}
            </p>
          </div>
        </div>
      </header>

      <section aria-labelledby="build-title">
        <h2 className="t-section" id="build-title">
          This build
        </h2>
        <div className="group">
          <div className="row">
            <div className="row-main">
              <span className="t-body">
                {signed === null
                  ? 'Signature not checked'
                  : signed
                    ? 'Signed and notarised'
                    : 'Unsigned'}
              </span>
              <span className="t-footnote">
                {signed === null
                  ? 'This build could not be verified on this platform. That is not the same as being unsigned.'
                  : signed
                    ? `${signedBy} — the OS verified this before it ran.`
                    : 'This build has not been signed. It should not be used with client audio.'}
              </span>
            </div>
            <span
              className={
                signed === null ? 'pill' : signed ? 'pill pill--ok' : 'pill pill--alert'
              }
            >
              {signed === null ? 'Unknown' : signed ? 'Verified' : 'Unverified'}
            </span>
          </div>
          <div className="row">
            <div className="row-main">
              <span className="t-body">
                {installedVia === 'Unknown' ? 'Install method unknown' : `Installed by ${installedVia}`}
              </span>
              <span className="t-footnote">
                {installedVia === 'MDM'
                  ? 'Managed install. Permissions below were granted by profile, so nobody had to answer a prompt.'
                  : installedVia === 'Direct download'
                    ? 'Direct download. Permissions were granted by you at first launch.'
                    : 'The management state of this machine could not be read.'}
              </span>
            </div>
          </div>
          <div className="row">
            <div className="row-main">
              <span className="t-body">Updates</span>
              <span className="t-footnote">{updateChannel}</span>
            </div>
          </div>
        </div>
      </section>

      <section aria-labelledby="perm-title">
        <h2 className="t-section" id="perm-title">
          Permissions
        </h2>
        <div className="group">
          {permissions.map((permission) => (
            <div className="row" key={permission.name}>
              <div className="row-main">
                <span className="t-body">{permission.name}</span>
                <span className="t-footnote">{permission.why}</span>
              </div>
              <span className={permission.granted ? 'pill pill--ok' : 'pill pill--alert'}>
                {permission.granted ? 'Granted' : 'Needed'}
              </span>
            </div>
          ))}
        </div>
        {missing.length > 0 ? (
          <p className="t-footnote hint">
            Capture will not start without {missing.map((p) => p.name).join(' and ')}.
            On a managed machine your IT team can grant this by profile rather
            than each person answering a prompt.
          </p>
        ) : null}
      </section>
    </main>
  );
}

export default function AboutRoute() {
  // Version, platform and architecture come from the build and the browser;
  // signing, install method and the update channel come from the shell asking
  // the OS, which is the only place any of the three is knowable.
  const build = buildInfo();
  const { signing, install, update } = useProvenance();

  return (
    <AboutScreen
      version={build.version}
      platform={build.platform}
      architecture={build.architecture}
      signed={signing?.signed ?? null}
      signedBy={signing?.signedBy ?? null}
      installedVia={
        install?.managed === true
          ? 'MDM'
          : install?.managed === false
            ? 'Direct download'
            : 'Unknown'
      }
      updateChannel={updateChannelSummary(update)}
      permissions={[]}
    />
  );
}
