import React from 'react';
import ReactDOM from 'react-dom/client';

import '../styles.css';
import { AboutScreen } from '../features/about/route';
import { ArcScreen } from '../features/arc/route';
import { CaptureScreen } from '../features/capture/route';
import { ConsentScreen } from '../features/consent/route';
import { DebriefChatScreen } from '../features/debrief-chat/route';
import { DebriefScreen } from '../features/debrief/route';
import { OperatorPanel } from '../features/panel/route';
import { PrepScreen } from '../features/prep/route';
import { RecordingScreen } from '../features/recording/route';
import { ReplayScreen } from '../features/replay/route';
import { SettingsPanel } from '../features/settings/SettingsPanel';
import { AppShell } from '../shell/AppShell';
import { buildDestinations } from '../shell/destinations';
import { SCENES } from './scenes';
import { STUB_SETTINGS_CONTROLLER } from './settingsScenes';
import {
  ABOUT_MANAGED,
  ABOUT_UNMANAGED,
  ARC,
  CAPTURING,
  CAPTURING_ACOUSTIC,
  PAUSED,
  CONSENT_CONFIRMED,
  CONSENT_PENDING,
  DEBRIEF,
  DEBRIEF_CHAT,
  DEBRIEF_CHAT_EMPTY,
  PREP,
  RECORDING,
  REPLAY,
  REPLAY_FAILING,
} from './synthetic';

/**
 * Journey capture harness.
 *
 * `?scene=<name>` renders one screen with fixed state so a screenshot is
 * deterministic — no clock, no network, no animation mid-flight. This entry is
 * not part of the shipped app: `index.html` is, and it imports nothing from
 * this directory.
 */
const SCREENS: Record<string, () => JSX.Element> = {
  prep: () => <PrepScreen {...PREP} />,
  'prep-uncompiled': () => <PrepScreen {...PREP} bank={null} />,
  'consent-pending': () => <ConsentScreen {...CONSENT_PENDING} />,
  'consent-confirmed': () => <ConsentScreen {...CONSENT_CONFIRMED} />,
  recording: () => <RecordingScreen {...RECORDING} />,
  debrief: () => <DebriefScreen {...DEBRIEF} />,
  'debrief-chat': () => <DebriefChatScreen {...DEBRIEF_CHAT} />,
  'debrief-chat-empty': () => <DebriefChatScreen {...DEBRIEF_CHAT_EMPTY} />,
  arc: () => <ArcScreen {...ARC} />,
  replay: () => <ReplayScreen {...REPLAY} />,
  capturing: () => <CaptureScreen {...CAPTURING} />,
  paused: () => <CaptureScreen {...PAUSED} />,
  'capture-acoustic': () => <CaptureScreen {...CAPTURING_ACOUSTIC} />,
  'about-managed': () => <AboutScreen {...ABOUT_MANAGED} />,
  'about-unmanaged': () => <AboutScreen {...ABOUT_UNMANAGED} />,
  'replay-failing': () => <ReplayScreen {...REPLAY_FAILING} />,
};

function renderScene(scene: string) {
  if (scene.startsWith('settings')) {
    return <SettingsPanel controller={STUB_SETTINGS_CONTROLLER[scene]} />;
  }

  const screen = SCREENS[scene];
  if (screen) return screen();

  const state = SCENES[scene];
  if (!state) {
    return <p style={{ padding: 16 }}>Unknown scene: {scene}</p>;
  }
  return <OperatorPanel initial={state} />;
}

/**
 * Which fixed screen stands in for each destination when the whole window is
 * the subject. The window is a screen too — its sidebar and toolbar carry
 * contrast, focus and landmark obligations like any other — and auditing it
 * against live routes would mean auditing whatever the service happened to
 * return that minute.
 */
const SHELL_SCENES: Record<string, string> = {
  prep: 'prep',
  consent: 'consent-confirmed',
  panel: 'nudge-surfaced',
  capture: 'capturing',
  recording: 'recording',
  debrief: 'debrief',
  'debrief-chat': 'debrief-chat',
  arc: 'arc',
  replay: 'replay',
  settings: 'settings-configured',
  about: 'about-managed',
};

function Scene() {
  const scene = new URLSearchParams(window.location.search).get('scene') ?? 'before-meeting';

  if (scene === 'shell') {
    return (
      <AppShell
        destinations={buildDestinations(Object.keys(SHELL_SCENES))}
        renderScreen={(destination) => renderScene(SHELL_SCENES[destination.feature])}
      />
    );
  }

  return renderScene(scene);
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Scene />
  </React.StrictMode>,
);
