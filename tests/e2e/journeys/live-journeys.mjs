/**
 * The twelve journeys of `docs/journeys/`, driven against a *running* system.
 *
 * Each journey drives its screen in the real shell and, separately, the
 * service endpoints that screen is meant to rest on. Both halves are recorded,
 * because the interesting failures here live in the gap between them: a screen
 * can render perfectly while nothing behind it is connected, and an endpoint
 * can answer correctly while no screen ever calls it.
 *
 * A check that fails is a result, not an error. The run continues and the
 * report says what happened — a journey that stops at the first surprise
 * measures one thing and hides the rest.
 */

export const JOURNEYS = [
  {
    id: '01',
    slug: 'prepare-an-engagement',
    title: 'Prepare for the engagement',
    screen: 'prep',
    async run(ctx) {
      await ctx.narrate('Creating the engagement through the live service');
      const created = await ctx.api('POST', '/api/engagements', {
        client_organisation: 'Northwind Logistics',
        sector: 'Freight and logistics',
        commercial_context: 'Fixed-price discovery, three meetings',
      });
      ctx.check('engagement is created', created.status === 201 || created.status === 200,
        `status ${created.status}, body ${JSON.stringify(created.json)}`);
      const engagementId = created.json?.engagement_id;
      ctx.state.engagementId = engagementId;
      ctx.check('the service returns an engagement id', Boolean(engagementId), String(engagementId));

      await ctx.narrate('Adding engagement vocabulary — the keyterms sent to the transcriber');
      const terms = [
        ['Northwind', 'product_name'],
        ['Freightlink', 'internal_system'],
        ['TMS', 'acronym'],
      ];
      let accepted = 0;
      for (const [term, term_type] of terms) {
        const res = await ctx.api('POST', `/api/engagements/${engagementId}/vocabulary`, { term, term_type });
        if (res.status < 300) accepted += 1;
      }
      ctx.check('all three vocabulary terms are accepted', accepted === 3, `${accepted} of 3`);

      const rejected = await ctx.api('POST', `/api/engagements/${engagementId}/vocabulary`,
        { term: 'Northwind', term_type: 'client_name' });
      ctx.check('an unknown term type is rejected rather than stored', rejected.status === 422,
        `status ${rejected.status}`);

      await ctx.narrate('Attaching a reference document');
      const offSite = await ctx.api('POST', `/api/engagements/${engagementId}/documents/link`,
        { url: 'https://northwind.example/rfp.pdf', status: 'ground truth' });
      ctx.check('a non-SharePoint link is refused', offSite.status === 422, `status ${offSite.status}`);

      const linked = await ctx.api('POST', `/api/engagements/${engagementId}/documents/link`, {
        url: 'https://northwind.sharepoint.com/sites/discovery/Shared%20Documents/RFP.pdf',
        status: 'ground truth',
      });
      ctx.check('a SharePoint link is attached', linked.status < 300 && Boolean(linked.json?.id),
        `status ${linked.status}, id ${linked.json?.id}`);

      const listed = await ctx.api('GET', `/api/engagements/${engagementId}/documents`);
      ctx.check('the attached document appears in the document list',
        (listed.json?.documents ?? []).length > 0,
        `list returned ${JSON.stringify(listed.json)} after attaching ${linked.json?.id}`);

      await ctx.narrate('Compiling the question bank — the pre-reasoning step');
      const compile = await ctx.api('POST', `/api/engagements/${engagementId}/bank/compile`);
      ctx.check('compilation is accepted', compile.status < 300, `status ${compile.status}`);
      await ctx.sleep(4000);
      const bank = await ctx.api('GET', `/api/engagements/${engagementId}/bank`);
      ctx.check('the compiled bank contains candidate questions',
        (bank.json?.sections ?? []).length > 0,
        `bank after compile: ${JSON.stringify(bank.json).slice(0, 300)}`);

      await ctx.narrate('Choosing this engagement in the toolbar, as an operator would');
      await ctx.reloadTo('prep');
      const picked = await ctx.selectInPicker(engagementId);
      ctx.check('the engagement can be chosen from the toolbar', picked === engagementId,
        `the picker reads ${JSON.stringify(picked)} after choosing ${engagementId}`);

      await ctx.narrate('The Preparation screen in the running app');
      await ctx.go('prep');
      await ctx.shot('prep-screen');
      const heading = await ctx.text('#prep-title');
      ctx.check('the preparation screen names the client organisation',
        heading !== null && heading.trim() !== '—' && heading.trim() !== '',
        `heading reads ${JSON.stringify(heading)}`);
      const docRows = await ctx.count('#docs-title ~ .group .row');
      ctx.check('the screen lists the reference document just attached', docRows > 0,
        `${docRows} rows in the reference-documents section`);
      const vocabChips = await ctx.count('#vocab-title ~ .chips-row .pill');
      ctx.check('the screen shows the engagement vocabulary just added', vocabChips > 0,
        `${vocabChips} vocabulary chips rendered`);
    },
  },

  {
    id: '02',
    slug: 'start-a-meeting-with-consent',
    title: 'Start the meeting, with consent on the record',
    screen: 'consent',
    async run(ctx) {
      const engagementId = ctx.state.engagementId;
      await ctx.narrate('Creating the meeting');
      const meeting = await ctx.api('POST', '/api/meetings', {
        engagement_id: engagementId,
        capture_mode: 'line-in',
      });
      const meetingId = meeting.json?.meeting_id;
      ctx.state.meetingId = meetingId;
      ctx.check('the meeting is created', Boolean(meetingId), `status ${meeting.status}, id ${meetingId}`);
      ctx.check('the meeting carries its engagement context',
        Boolean(meeting.json?.engagement_context?.client_organisation),
        JSON.stringify(meeting.json?.engagement_context));

      await ctx.narrate('Reading the consent gate before anyone has confirmed');
      const before = await ctx.api('GET', `/api/meetings/${meetingId}/consent-gate?engagement_id=${engagementId}`);
      ctx.check('the gate reports consent is still awaited',
        before.json?.status === 'awaiting_confirmation', JSON.stringify(before.json?.status));
      ctx.check('the gate states its legal basis',
        typeof before.json?.prompt?.legal_basis === 'string',
        String(before.json?.prompt?.legal_basis));

      await ctx.narrate('Trying to start the session before consent — this must be refused');
      const early = await ctx.api('POST', `/api/meetings/${meetingId}/session/start`);
      ctx.check('starting a session before consent is refused', early.status >= 400,
        `status ${early.status}, ${JSON.stringify(early.json)}`);
      // Refused is not enough — it has to be refused *for the right reason*.
      // A service that cannot find the meeting at all also returns 4xx, and
      // would let a missing consent gate pass as a working one.
      const consentReason = JSON.stringify(early.json ?? '');
      ctx.check('the refusal is about consent, not a meeting the service cannot find',
        /consent/i.test(consentReason),
        `refused with ${consentReason} — 4xx here does not demonstrate a consent gate`);

      await ctx.narrate('The Consent screen before anyone has confirmed');
      await ctx.reloadTo('consent');
      await ctx.selectInPicker(engagementId, meetingId);
      await ctx.shot('consent-before');
      const beforeDisabled = await ctx.eval(
        `const b=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='Start');
         return b ? b.disabled : null`);
      ctx.check('capture cannot be started until consent is confirmed', beforeDisabled === true,
        `the Start button's disabled state is ${JSON.stringify(beforeDisabled)} while consent is unconfirmed`);

      await ctx.narrate('Confirming consent on the record');
      const confirm = await ctx.api('POST', `/api/meetings/${meetingId}/consent-confirmation`,
        { confirmed_by: 'Dana Whitfield, COO' });
      ctx.check('consent is recorded against a named person',
        confirm.json?.confirmed_by === 'Dana Whitfield, COO', JSON.stringify(confirm.json));
      ctx.check('consent is timestamped', Boolean(confirm.json?.confirmed_at),
        String(confirm.json?.confirmed_at));

      const after = await ctx.api('GET', `/api/meetings/${meetingId}/consent-gate?engagement_id=${engagementId}`);
      ctx.check('the gate opens once consent is confirmed',
        after.json?.status !== 'awaiting_confirmation',
        `gate still reads ${JSON.stringify(after.json?.status)} after a confirmation was accepted`);

      await ctx.narrate('Starting the session now that consent is on the record');
      const started = await ctx.api('POST', `/api/meetings/${meetingId}/session/start`);
      ctx.check('the session starts once consent is confirmed', started.status < 300,
        `status ${started.status}, ${JSON.stringify(started.json)}`);
      ctx.state.sessionId = started.json?.session_id ?? null;

      await ctx.narrate('The Consent screen in the running app');
      await ctx.reloadTo('consent');
      await ctx.selectInPicker(engagementId, meetingId);
      await ctx.shot('consent-screen');
      const startDisabled = await ctx.eval(
        `const b=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='Start'); return b? b.disabled : null`);
      ctx.check('capture becomes available once consent is on the record', startDisabled === false,
        `the Start button's disabled state is ${JSON.stringify(startDisabled)} after consent was confirmed`);
      const meetingTitle = await ctx.text('#consent-title');
      ctx.check('the consent screen names the meeting it gates',
        meetingTitle !== null && meetingTitle.trim() !== '—',
        `title reads ${JSON.stringify(meetingTitle)}`);
    },
  },

  {
    id: '03',
    slug: 'catch-a-vague-answer-live',
    title: 'Catch a vague answer while it still matters',
    screen: 'panel',
    blocked: 'No Deepgram backend exists. `TranscriptionBackend` has three implementations in `core/crates/asr-live` and all three are fakes; the crate has no dependencies, so it cannot open a socket.',
    async run(ctx) {
      const meetingId = ctx.state.meetingId;
      await ctx.narrate('Opening the live session stream the panel reads from');
      const stream = await ctx.api('GET', `/api/meetings/${meetingId}/session/stream`, null, 6000);
      ctx.check('the session stream is reachable', stream.status < 400,
        `status ${stream.status}, ${JSON.stringify(stream.json).slice(0, 200)}`);

      await ctx.narrate('Ticking the slow lane — the pre-reasoning that refills the bank');
      const tick = await ctx.api('POST', `/api/meetings/${meetingId}/slow-lane/tick`);
      ctx.check('the slow lane accepts a tick', tick.status < 400,
        `status ${tick.status}, ${JSON.stringify(tick.json)}`);

      await ctx.narrate('The live panel in the running app');
      await ctx.go('panel');
      await ctx.shot('panel-screen');
      const panelPresent = await ctx.count('main.panel');
      ctx.check('the panel renders', panelPresent === 1, `${panelPresent} panels found`);
      const coverage = await ctx.eval(
        `const m=document.querySelector('.meter'); return m? m.textContent.trim() : null`);
      // "not empty" is not a reading: the placeholder chrome renders "— / —",
      // which is a non-empty string and would pass a length check while
      // proving nothing arrived.
      ctx.check('the panel shows live coverage from the session',
        typeof coverage === 'string' && /\d/.test(coverage),
        `coverage chrome reads ${JSON.stringify(coverage)}`);
      const nudge = await ctx.eval(
        `const n=document.querySelector('.nudge'); return n? n.textContent.trim().slice(0,200) : null`);
      ctx.check('a follow-up question is surfaced to the operator',
        typeof nudge === 'string' && !/no active nudge/i.test(nudge) && nudge.length > 0,
        `nudge area reads ${JSON.stringify(nudge)}`);
    },
  },

  {
    id: '04',
    slug: 'run-a-code-switched-meeting',
    title: 'Run a meeting in two languages',
    screen: 'panel',
    blocked: 'Same missing vendor backend as journey 3 — the credential is configured and verified, but nothing can connect to Deepgram to transcribe.',
    async run(ctx) {
      await ctx.narrate('The panel is where a detected language change is shown');
      await ctx.go('panel');
      await ctx.shot('panel-language-chrome');
      const langChrome = await ctx.eval(
        `const l=document.querySelector('.chrome-right'); return l? l.textContent.trim() : null`);
      ctx.check('the panel reports which languages are being heard',
        typeof langChrome === 'string' && !/no language detected/i.test(langChrome),
        `language chrome reads ${JSON.stringify(langChrome)}`);

      await ctx.narrate('Checking the settings that govern code-switched transcription');
      const settings = await ctx.api('GET', '/api/admin/settings');
      ctx.check('keyterm prompting is on, so client terms survive transcription',
        settings.json?.connectors?.keyterm_prompting === true,
        String(settings.json?.connectors?.keyterm_prompting));
      ctx.check('a live transcription vendor is selected',
        typeof settings.json?.connectors?.live_vendor === 'string',
        String(settings.json?.connectors?.live_vendor));
      const asrConfigured = (settings.json?.secrets ?? [])
        .find((s) => s.key === 'asr_vendor_api_key')?.configured;
      ctx.check('the selected speech vendor has a credential', asrConfigured === true,
        `asr_vendor_api_key configured: ${asrConfigured}`);

      await ctx.narrate('Verifying that credential against the vendor');
      const probe = await ctx.api('POST', '/api/admin/settings/asr_vendor_api_key/test', null, 30000);
      ctx.check('the speech vendor accepts the configured credential',
        probe.json?.reachable === true, JSON.stringify(probe.json));
    },
  },

  {
    id: '05',
    slug: 'degraded-mode',
    title: 'When the connection drops',
    screen: 'panel',
    async run(ctx) {
      await ctx.narrate('The panel must say which mode it is in, never fail silently');
      await ctx.go('panel');
      await ctx.shot('panel-degraded-check');
      const degradedShown = await ctx.eval(
        `return document.body.textContent.includes('Deterministic only')`);
      const noteShown = await ctx.eval(
        `const n=document.querySelector('.degraded-note'); return n? n.textContent.trim() : null`);
      ctx.check('the panel is not falsely claiming degraded mode while the model is reachable',
        degradedShown === false,
        `degraded pill present: ${degradedShown}, note: ${JSON.stringify(noteShown)}`);

      await ctx.narrate('Confirming the model really is reachable, so that reading is honest');
      const test = await ctx.api('POST', '/api/admin/settings/anthropic_oauth_token/test', null, 60000);
      ctx.check('the configured model credential is reachable', test.json?.reachable === true,
        JSON.stringify(test.json));

      await ctx.narrate('The egress audit — what left the machine, and where to');
      const egress = await ctx.api('GET',
        `/api/audit/egress?engagement_id=${ctx.state.engagementId}&start_ms=0&end_ms=99999999999999`);
      ctx.check('an egress audit trail is available', egress.status < 300,
        `status ${egress.status}, ${JSON.stringify(egress.json).slice(0, 300)}`);
      ctx.check('the audit records what left the machine',
        Array.isArray(egress.json?.rows ?? egress.json) && (egress.json?.rows ?? egress.json).length > 0,
        `audit returned ${JSON.stringify(egress.json).slice(0, 240)} after a live model call was made`);
    },
  },

  {
    id: '06',
    slug: 'reconcile-the-recording',
    title: 'Check the recording',
    screen: 'recording',
    blocked: '`app/modules/asr-record` makes no outbound HTTP call, so the record path has no vendor client to reconcile two engines with.',
    async run(ctx) {
      const meetingId = ctx.state.meetingId;
      await ctx.narrate('Asking the record path to transcribe the meeting audio');
      const transcribe = await ctx.api('POST', `/api/meetings/${meetingId}/record/transcribe`,
        { audio_ref: 'memory://northwind-discovery-2' }, 60000);
      ctx.check('the record path accepts a transcription request', transcribe.status < 400,
        `status ${transcribe.status}, ${JSON.stringify(transcribe.json).slice(0, 300)}`);

      const divergences = await ctx.api('GET', `/api/meetings/${meetingId}/record/divergences`);
      ctx.check('divergences between the two engines are reported', divergences.status < 400,
        `status ${divergences.status}, ${JSON.stringify(divergences.json).slice(0, 300)}`);

      await ctx.narrate('The Recording screen in the running app');
      await ctx.reloadTo('recording');
      await ctx.selectInPicker(ctx.state.engagementId, meetingId);
      await ctx.shot('recording-screen');
      const engines = await ctx.count('#engines-title ~ .group .row');
      ctx.check('the screen names the engines that transcribed the meeting', engines > 0,
        `${engines} engine rows rendered`);
      const agreement = await ctx.text('.stat-value');
      ctx.check('the screen reports how far the engines agreed',
        agreement !== null && agreement.trim() !== '0%',
        `agreement reads ${JSON.stringify(agreement)}`);
    },
  },

  {
    id: '07',
    slug: 'produce-the-debrief',
    title: 'Get the write-up',
    screen: 'debrief-chat',
    async run(ctx) {
      const meetingId = ctx.state.meetingId;
      await ctx.narrate('Opening a debrief conversation against the live model');
      const start = await ctx.api('POST', `/api/meetings/${meetingId}/debrief/start`, null, 60000);
      ctx.check('a debrief conversation opens', start.status < 300, `status ${start.status}`);
      ctx.check('the conversation is anchored to a session',
        Boolean(start.json?.session_id), String(start.json?.session_id));
      const debriefSession = start.json?.session_id;
      ctx.state.debriefSession = debriefSession;

      await ctx.narrate('Asking a real question — this calls Claude for real');
      const question = 'What did the client say about the March deadline?';
      const asked = await ctx.api('POST', `/api/meetings/${meetingId}/debrief/message`,
        { message: question }, 120000);
      ctx.check('the debrief accepts a free-text question', asked.status < 300,
        `status ${asked.status}, ${JSON.stringify(asked.json).slice(0, 400)}`);
      // A reply that merely quotes the question back is a stub, not an answer.
      // Asserting only on the status code would let that pass, which is how a
      // placeholder survives a green suite.
      const reply = JSON.stringify(asked.json ?? '');
      ctx.check('the answer comes from the model rather than a stub echo',
        !reply.includes(`ack: ${question}`) && !/\back:\s/.test(reply),
        `the service replied ${reply.slice(0, 300)}`);

      await ctx.narrate('The citation-backed artifacts');
      for (const [name, path] of [
        ['project brief', `/api/sessions/${debriefSession}/project-brief`],
        ['decision log', `/api/sessions/${debriefSession}/decision-log`],
        ['open questions', `/api/sessions/${debriefSession}/open-questions`],
        ['follow-up email', `/api/sessions/${debriefSession}/follow-up-email`],
      ]) {
        const res = await ctx.api('GET', path, null, 60000);
        ctx.check(`the ${name} is produced`, res.status < 300,
          `status ${res.status}, ${JSON.stringify(res.json).slice(0, 240)}`);
      }

      const artifacts = await ctx.api('GET', `/api/meetings/${meetingId}/artifacts`);
      ctx.check('the meeting lists its artifacts', (artifacts.json?.artifacts ?? artifacts.json ?? []).length > 0,
        JSON.stringify(artifacts.json).slice(0, 300));

      await ctx.narrate('Asking about the meeting in the running app');
      await ctx.reloadTo('debrief-chat');
      await ctx.selectInPicker(ctx.state.engagementId, meetingId);
      await ctx.shot('debrief-chat-before-start');
      await ctx.clickText('button', 'Start');
      await ctx.sleep(4000);
      await ctx.shot('debrief-chat-started');
      const started = await ctx.eval(`return document.querySelector('#debrief-question') !== null`);
      ctx.check('the conversation opens from the screen', started === true, `ask form present: ${started}`);

      if (started === true) {
        await ctx.narrate('Typing a question into the live app and sending it to Claude');
        await ctx.type('#debrief-question', 'Which requirements are still only inferred?');
        await ctx.shot('debrief-chat-question-typed');
        await ctx.clickText('button', 'Ask');
        await ctx.sleep(20000);
        await ctx.shot('debrief-chat-answer');
        const turns = await ctx.count('.debrief-turn');
        ctx.check('the screen shows the question and an answer', turns >= 2, `${turns} turns rendered`);
        const answer = await ctx.eval(
          `const t=[...document.querySelectorAll('.debrief-turn--assistant p')].pop();
           return t ? t.textContent.trim() : null`);
        ctx.check('the answer on screen is a real answer, not the question echoed back',
          typeof answer === 'string' && !/^ack:/i.test(answer),
          `Elicta replied ${JSON.stringify(answer)}`);
        const error = await ctx.text('.debrief-error');
        ctx.check('the debrief screen reports no error', error === null,
          `error region reads ${JSON.stringify(error)}`);
      }

      await ctx.narrate('The Debrief artifacts screen');
      await ctx.go('debrief');
      await ctx.shot('debrief-artifacts-screen');
      const claims = await ctx.count('.row .quote');
      ctx.check('every claim on the debrief screen carries its citation', claims > 0,
        `${claims} cited claims rendered`);
    },
  },

  {
    id: '08',
    slug: 'carry-state-forward',
    title: 'Carry what you learned forward',
    screen: 'arc',
    async run(ctx) {
      const engagementId = ctx.state.engagementId;
      await ctx.narrate('The state that survives from one meeting into the next');
      const state = await ctx.api('GET', `/api/engagements/${engagementId}/state`);
      ctx.check('engagement state is readable', state.status < 300, `status ${state.status}`);
      ctx.check('open questions are carried forward to the next meeting',
        (state.json?.inherited_open_questions ?? []).length > 0,
        `state reads ${JSON.stringify(state.json)}`);

      const requirements = await ctx.api('GET', `/api/engagements/${engagementId}/requirements-state`);
      ctx.check('the requirements state is readable', requirements.status < 300,
        `status ${requirements.status}, ${JSON.stringify(requirements.json).slice(0, 240)}`);

      await ctx.narrate('The next meeting inherits the bank, weighted to what is still open');
      const second = await ctx.api('POST', '/api/meetings', {
        engagement_id: engagementId, capture_mode: 'line-in',
      });
      const secondId = second.json?.meeting_id;
      ctx.check('a second meeting is created in the same engagement', Boolean(secondId), String(secondId));
      const inherited = await ctx.api('GET', `/api/meetings/${secondId}/bank`);
      ctx.check('the second meeting inherits candidate questions',
        (inherited.json?.candidates ?? []).length > 0,
        `inherited bank: ${JSON.stringify(inherited.json).slice(0, 240)}`);

      await ctx.narrate('The Engagement arc screen in the running app');
      await ctx.reloadTo('arc');
      await ctx.selectInPicker(engagementId);
      await ctx.shot('arc-screen');
      const meetings = await ctx.count('.timeline-item');
      ctx.check('the arc shows the meetings held so far', meetings > 0, `${meetings} meetings on the timeline`);
    },
  },

  {
    id: '09',
    slug: 'replay-and-tune-ranking',
    title: 'Judge whether the suggestions are any good',
    screen: 'replay',
    async run(ctx) {
      await ctx.narrate('Starting a replay run over a recorded meeting');
      const run = await ctx.api('POST', '/api/replay/runs', { recording_id: 'northwind-discovery-2' }, 60000);
      ctx.check('a replay run starts', run.status < 300,
        `status ${run.status}, ${JSON.stringify(run.json).slice(0, 240)}`);
      const runId = run.json?.run_id ?? run.json?.id;
      ctx.state.replayRun = runId;

      if (runId) {
        const detail = await ctx.api('GET', `/api/replay/runs/${runId}`);
        ctx.check('the run reports its suggestions', detail.status < 300,
          `status ${detail.status}, ${JSON.stringify(detail.json).slice(0, 300)}`);

        await ctx.narrate('Rating a suggestion, then reading the release gates');
        const rated = await ctx.api('POST', `/api/replay/runs/${runId}/ratings`,
          { suggestion_id: 'suggestion-1', verdict: 'useful' });
        ctx.check('a rating is accepted', rated.status < 400,
          `status ${rated.status}, ${JSON.stringify(rated.json).slice(0, 240)}`);

        const metrics = await ctx.api('GET', `/api/replay/runs/${runId}/metrics`);
        ctx.check('the run reports the precision and embarrassment gates', metrics.status < 300,
          `status ${metrics.status}, ${JSON.stringify(metrics.json).slice(0, 300)}`);
      }

      await ctx.narrate('The Replay screen in the running app');
      await ctx.go('replay');
      await ctx.shot('replay-screen');
      const label = await ctx.text('#replay-title');
      ctx.check('the replay screen names the run it is showing',
        label !== null && label.trim() !== '—', `run label reads ${JSON.stringify(label)}`);
      const suggestions = await ctx.count('#rate-title ~ .group .row');
      ctx.check('the screen lists suggestions to rate', suggestions > 0, `${suggestions} suggestions rendered`);
    },
  },

  {
    id: '10',
    slug: 'configure-providers',
    title: 'Set up the services Elicta uses',
    screen: 'settings',
    async run(ctx) {
      await ctx.narrate('The Settings screen, read from the live service');
      await ctx.go('settings');
      await ctx.sleep(1500);
      await ctx.shot('settings-loaded');
      const loaded = await ctx.eval(`return document.querySelector('#model') !== null`);
      ctx.check('settings load from the service', loaded === true, `model field present: ${loaded}`);

      await ctx.narrate('Choosing OAuth-token authentication');
      await ctx.eval(
        `const r=[...document.querySelectorAll('input[name="auth-mode"]')].find(x=>x.value==='oauth_token');
         if(r && !r.checked) r.click(); return true`);
      await ctx.sleep(600);

      await ctx.narrate('Entering the Anthropic OAuth token — a password field, so it never renders');
      await ctx.type('#anthropic_oauth_token', ctx.secrets.anthropicToken, { secret: true });
      await ctx.shot('settings-token-entered');
      const masked = await ctx.eval(
        `const i=document.querySelector('#anthropic_oauth_token'); return i? i.type : null`);
      ctx.check('the credential field never renders its value', masked === 'password',
        `input type is ${JSON.stringify(masked)}`);

      await ctx.narrate('Saving');
      await ctx.clickText('button', 'Save');
      await ctx.sleep(3000);
      await ctx.shot('settings-saved');
      const savedShown = await ctx.eval(`return document.body.textContent.includes('Saved')`);
      ctx.check('the screen confirms the save', savedShown === true, `"Saved" shown: ${savedShown}`);

      const settings = await ctx.api('GET', '/api/admin/settings');
      const secret = (settings.json?.secrets ?? []).find((s) => s.key === 'anthropic_oauth_token');
      ctx.check('the service stores the token', secret?.configured === true, JSON.stringify(secret));
      ctx.check('a stored secret is never returned, only hinted at',
        typeof secret?.hint === 'string' && secret.hint.length === 4
          && !JSON.stringify(settings.json).includes(ctx.secrets.anthropicToken),
        `hint ${secret?.hint}; the response was checked for the raw value`);

      await ctx.narrate('Testing the credential against the vendor for real');
      await ctx.clickText('button', 'Test');
      await ctx.sleep(8000);
      await ctx.shot('settings-credential-tested');
      const stateLine = await ctx.text('#anthropic_oauth_token-state');
      ctx.check('the screen reports the credential verified',
        typeof stateLine === 'string' && /verified/i.test(stateLine),
        `state line reads ${JSON.stringify(stateLine)}`);

      await ctx.narrate('The speech vendors section');
      await ctx.eval(`document.querySelector('#live-vendor')?.scrollIntoView({block:'center'}); return true`);
      await ctx.sleep(800);
      await ctx.shot('settings-speech-vendors');
      const vendor = await ctx.eval(`const s=document.querySelector('#live-vendor'); return s? s.value : null`);
      ctx.check('a live transcription vendor can be chosen', vendor !== null, `live vendor is ${vendor}`);

      if (ctx.secrets.deepgramKey) {
        await ctx.narrate('Selecting Deepgram for live transcription');
        const chose = await ctx.select('#live-vendor', 'deepgram');
        ctx.check('Deepgram can be selected as the live vendor', chose === true,
          `#live-vendor now reads ${await ctx.eval(`const s=document.querySelector('#live-vendor'); return s? s.value : null`)}`);

        await ctx.narrate('Entering the Deepgram key');
        await ctx.eval(`document.querySelector('#asr_vendor_api_key')?.scrollIntoView({block:'center'}); return true`);
        await ctx.type('#asr_vendor_api_key', ctx.secrets.deepgramKey, { secret: true });
        await ctx.shot('settings-deepgram-entered');

        await ctx.clickText('button', 'Save');
        await ctx.sleep(3000);
        await ctx.shot('settings-deepgram-saved');

        const saved = await ctx.api('GET', '/api/admin/settings');
        const asr = (saved.json?.secrets ?? []).find((s) => s.key === 'asr_vendor_api_key');
        ctx.check('the service stores the speech-vendor key', asr?.configured === true,
          JSON.stringify(asr));
        ctx.check('the live vendor is now Deepgram',
          saved.json?.connectors?.live_vendor === 'deepgram',
          `live_vendor is ${saved.json?.connectors?.live_vendor}`);
        ctx.check('the speech key is write-only too, like the model credential',
          !JSON.stringify(saved.json).includes(ctx.secrets.deepgramKey),
          'the settings response was checked for the raw key');

        await ctx.narrate('Testing the Deepgram key against the vendor for real');
        await ctx.eval(`document.querySelector('#asr_vendor_api_key')?.scrollIntoView({block:'center'}); return true`);
        await ctx.clickBeside('#asr_vendor_api_key', 'Test');
        await ctx.sleep(8000);
        await ctx.shot('settings-deepgram-tested');
        const asrState = await ctx.text('#asr_vendor_api_key-state');
        ctx.check('the screen reports the Deepgram credential verified',
          typeof asrState === 'string' && /verified/i.test(asrState),
          `state line reads ${JSON.stringify(asrState)}`);
      }
    },
  },

  {
    id: '11',
    slug: 'control-capture',
    title: 'Control the recording',
    screen: 'capture',
    async run(ctx) {
      await ctx.narrate('The Capture screen — state must be unambiguous at a glance');
      await ctx.go('capture');
      await ctx.shot('capture-screen');
      const state = await ctx.text('#capture-title');
      ctx.check('the capture state is stated in words, not colour alone',
        typeof state === 'string' && ['Recording', 'Paused', 'Stopped'].includes(state.trim()),
        `state reads ${JSON.stringify(state)}`);

      const warning = await ctx.text('.capture-warning');
      const toggleDisabled = await ctx.eval(
        `const b=document.querySelector('.capture-toggle'); return b? b.disabled : null`);
      ctx.check('an unavailable audio backend is explained rather than left looking like a choice',
        !(toggleDisabled === true && warning === null),
        `pause disabled: ${toggleDisabled}, warning: ${JSON.stringify(warning)}`);
      ctx.note('capture in a browser', `pause control disabled: ${toggleDisabled}; reason shown: ${JSON.stringify(warning)}`);

      const sources = await ctx.count('#source-title ~ .group .row');
      ctx.check('the screen lists the audio sources it can record from', sources > 0,
        `${sources} sources listed`);
    },
  },

  {
    id: '12',
    slug: 'install-and-roll-out',
    title: 'Get Elicta onto people’s machines',
    screen: 'about',
    async run(ctx) {
      await ctx.narrate('The About screen — how this build got here, and what it was granted');
      await ctx.go('about');
      await ctx.shot('about-screen');
      const version = await ctx.text('.about-identity .t-footnote');
      ctx.check('the build identifies its version and platform',
        typeof version === 'string' && /\d+\.\d+\.\d+/.test(version), `reads ${JSON.stringify(version)}`);

      const signing = await ctx.eval(`return document.body.textContent.includes('Signature not checked')
        || document.body.textContent.includes('Signed and notarised')
        || document.body.textContent.includes('Unsigned')`);
      ctx.check('the signing state is stated, and unknown is distinguished from unsigned',
        signing === true, `signing row present: ${signing}`);

      const permissions = await ctx.count('#perm-title ~ .group .row');
      ctx.check('the OS permissions this build holds are listed', permissions > 0,
        `${permissions} permission rows rendered`);
    },
  },
];
