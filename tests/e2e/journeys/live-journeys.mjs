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

/**
 * A real `.docx` — a ZIP of OOXML parts — so the upload check exercises the
 * extractor rather than a `.txt` that would pass by decoding. Built here rather
 * than checked in as a binary: what it is testing is the format.
 */
const DOCX_WITH_TEXT = (() => {
  const parts = [];
  const encoder = new TextEncoder();
  const name = 'word/document.xml';
  const xml =
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">' +
    '<w:body><w:p><w:r><w:t>Northwind moves 350 consignments a day through cross-dock.' +
    '</w:t></w:r></w:p></w:body></w:document>';
  const data = encoder.encode(xml);
  const nameBytes = encoder.encode(name);

  // Stored (uncompressed) entries keep this to a CRC and two headers.
  let crc = ~0;
  for (const byte of data) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
  }
  crc = (~crc) >>> 0;

  const u16 = (value) => [value & 0xff, (value >>> 8) & 0xff];
  const u32 = (value) => [value & 0xff, (value >>> 8) & 0xff, (value >>> 16) & 0xff, (value >>> 24) & 0xff];

  const local = [
    0x50, 0x4b, 0x03, 0x04, ...u16(20), ...u16(0), ...u16(0), ...u16(0), ...u16(0),
    ...u32(crc), ...u32(data.length), ...u32(data.length),
    ...u16(nameBytes.length), ...u16(0), ...nameBytes,
  ];
  parts.push(...local, ...data);

  const central = [
    0x50, 0x4b, 0x01, 0x02, ...u16(20), ...u16(20), ...u16(0), ...u16(0), ...u16(0), ...u16(0),
    ...u32(crc), ...u32(data.length), ...u32(data.length),
    ...u16(nameBytes.length), ...u16(0), ...u16(0), ...u16(0), ...u16(0), ...u32(0), ...u32(0),
    ...nameBytes,
  ];
  const centralStart = parts.length;
  parts.push(...central);

  parts.push(
    0x50, 0x4b, 0x05, 0x06, ...u16(0), ...u16(0), ...u16(1), ...u16(1),
    ...u32(central.length), ...u32(centralStart), ...u16(0),
  );
  return new Uint8Array(parts);
})();

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

      await ctx.narrate('Attaching a reference document by link');
      const offSite = await ctx.api('POST', `/api/engagements/${engagementId}/documents/link`,
        { url: 'https://northwind.example/rfp.pdf', status: 'ground truth' });
      ctx.check('a link that is not a Microsoft 365 one is refused', offSite.status === 422,
        `status ${offSite.status}`);

      // A link is only worth attaching if its contents can be read. Until the
      // Microsoft 365 connector is configured, attaching one recorded a URL and
      // an empty body — which is what made `bank/compile` answer with an empty
      // bank and look like a missing model. Refusing, and naming the setting,
      // is the behaviour under test here; against a tenant-configured service
      // the same call attaches and carries text.
      const linked = await ctx.api('POST', `/api/engagements/${engagementId}/documents/link`, {
        url: 'https://northwind.sharepoint.com/sites/discovery/Shared%20Documents/RFP.pdf',
        status: 'ground truth',
      });
      const linkDetail = String(linked.json?.detail ?? '');
      ctx.check('a link is either read or refused, never attached unread',
        (linked.status < 300 && Boolean(linked.json?.id)) ||
          (linked.status === 502 && /not configured|Microsoft 365/i.test(linkDetail)),
        `status ${linked.status}, body ${JSON.stringify(linked.json).slice(0, 200)}`);

      await ctx.narrate('Uploading a document from the drop zone');
      const uploaded = await ctx.upload(`/api/engagements/${engagementId}/documents`, {
        filename: 'Warehouse throughput study 2025.docx',
        content: DOCX_WITH_TEXT,
        fields: { status: 'ground truth' },
      });
      ctx.check('an uploaded document is accepted',
        uploaded.status === 201 && Boolean(uploaded.json?.document_id),
        `status ${uploaded.status}, body ${JSON.stringify(uploaded.json).slice(0, 200)}`);

      const listed = await ctx.api('GET', `/api/engagements/${engagementId}/documents`);
      ctx.check('the uploaded document appears in the document list',
        (listed.json?.documents ?? []).length > 0,
        `list returned ${JSON.stringify(listed.json)}`);

      await ctx.narrate('Taking a mistyped word back out');
      const mistyped = await ctx.api('POST', `/api/engagements/${engagementId}/vocabulary`,
        { term: 'Freightlnk', term_type: 'internal_system' });
      const mistypedId = mistyped.json?.term_id;
      const removed = await ctx.api(
        'DELETE', `/api/engagements/${engagementId}/vocabulary/${mistypedId}`);
      ctx.check('a vocabulary term can be removed', removed.status === 204,
        `status ${removed.status}`);

      const afterRemoval = await ctx.api('GET', `/api/engagements/${engagementId}/vocabulary`);
      const termsNow = (afterRemoval.json?.terms ?? []).map((t) => t.term);
      ctx.check('the removed word is gone and the others are not',
        !termsNow.includes('Freightlnk') && termsNow.includes('Northwind'),
        `vocabulary reads ${JSON.stringify(termsNow)}`);

      ctx.check('removing something that is not there is not reported as success',
        (await ctx.api('DELETE', `/api/engagements/${engagementId}/vocabulary/term-nope`))
          .status === 404,
        'a 204 for an id nobody has would make a typo look like a removal');

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

      // What this journey can and cannot drive from outside. The gate has two
      // consent models and only one of them is reachable here: nothing sets an
      // engagement's consent model over the API, so every engagement created
      // through it takes DEFAULT_CONSENT_MODEL, which is engagement-level. The
      // asking model — prompt, refusal, confirmation, record — is covered by
      // tests/e2e/api_integration/test_consent_and_egress.py, which can seed
      // the model. What this run demonstrates is what an operator of this
      // build actually meets.
      ctx.note('the asking consent model is not reachable over the API',
        'no endpoint sets an engagement consent model, so this run exercises the '
        + 'engagement-level default only; the per-meeting gate is covered in the API suite');

      await ctx.narrate('Reading the consent gate on a meeting nobody has confirmed');
      const gate = await ctx.api('GET', `/api/meetings/${meetingId}/consent-gate?engagement_id=${engagementId}`);
      ctx.check('the gate reports that consent is not being asked for',
        gate.json?.status === 'not_required', JSON.stringify(gate.json?.status));
      ctx.check('a gate that is not asking carries no prompt',
        gate.json?.prompt === null || gate.json?.prompt === undefined,
        JSON.stringify(gate.json?.prompt));

      await ctx.narrate('The Consent screen as an operator of this build meets it');
      await ctx.reloadTo('consent');
      await ctx.selectInPicker(engagementId, meetingId);
      await ctx.shot('consent-screen');

      const rowText = await ctx.eval(
        `const el=[...document.querySelectorAll('.row')].find(r=>/Not required|Not confirmed|Confirmed/.test(r.textContent));
         return el ? el.textContent.trim() : null`);
      ctx.check('the screen says consent is not required for this meeting',
        typeof rowText === 'string' && /Not required for this meeting/.test(rowText),
        JSON.stringify(rowText));
      // The screen must not dress an unasked question up as an answered one.
      ctx.check('the screen does not claim anything is on record',
        typeof rowText === 'string' && !/On record/.test(rowText) && /nothing is recorded/i.test(rowText),
        JSON.stringify(rowText));

      const startDisabled = await ctx.eval(
        `const b=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='Start');
         return b ? b.disabled : null`);
      ctx.check('capture can be started with nothing confirmed — the stage default',
        startDisabled === false,
        `the Start button's disabled state is ${JSON.stringify(startDisabled)} with no confirmation recorded`);

      await ctx.narrate('Starting the session, which this build admits without a confirmation');
      const started = await ctx.api('POST', `/api/meetings/${meetingId}/session/start`);
      ctx.check('the session starts without a consent confirmation', started.status < 300,
        `status ${started.status}, ${JSON.stringify(started.json)}`);
      ctx.state.sessionId = started.json?.session_id ?? null;

      // The other half of "not asked": nothing may exist that suggests it was.
      const record = await ctx.api('GET', `/api/meetings/${meetingId}/consent-record`);
      ctx.check('no consent record is written when consent was never asked for',
        record.status === 404, `status ${record.status}, ${JSON.stringify(record.json)}`);

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
      const stream = await ctx.sse(`/api/meetings/${meetingId}/session/stream`, 6000);
      ctx.check('the session stream is reachable', stream.status < 400,
        `status ${stream.status}, ${stream.text.slice(0, 200)}`);

      await ctx.narrate('Ticking the slow lane — the pre-reasoning that refills the bank');
      const tick = await ctx.api('POST', `/api/meetings/${meetingId}/slow-lane/tick`);
      ctx.check('the slow lane accepts a tick', tick.status < 400,
        `status ${tick.status}, ${JSON.stringify(tick.json)}`);

      await ctx.narrate('The live panel in the running app');
      await ctx.reloadTo('panel');
      await ctx.selectInPicker(ctx.state.engagementId, meetingId);
      await ctx.shot('panel-screen');
      const panelPresent = await ctx.count('main.panel');
      ctx.check('the panel renders', panelPresent === 1, `${panelPresent} panels found`);

      // The distinction that was invisible before, and that mattered most:
      // the panel used to render `<OperatorPanel />` with no props, so it
      // opened no stream for any meeting and every reading below was a
      // placeholder. "Connected, with nothing to send" and "not connected at
      // all" look identical on screen; this separates them by asking the page
      // whether it actually opened the connection.
      const streamOpened = await ctx.eval(
        `return performance.getEntriesByType('resource')
           .some(e => e.name.includes('/session/stream'))`);
      ctx.check('the panel opens the meeting’s live session stream',
        streamOpened === true,
        `the page ${streamOpened ? 'opened' : 'never opened'} a request to .../session/stream`);
      const coverage = await ctx.eval(
        `const m=document.querySelector('.meter'); return m? m.textContent.trim() : null`);
      // "not empty" is not a reading: the placeholder chrome renders "— / —",
      // which is a non-empty string and would pass a length check while
      // proving nothing arrived.
      ctx.check('the panel shows live coverage from the session',
        typeof coverage === 'string' && /\d/.test(coverage),
        `coverage chrome reads ${JSON.stringify(coverage)} — the stream is open, `
        + `but nothing writes session_stream_events, so the session carries no coverage`);
      const nudge = await ctx.eval(
        `const n=document.querySelector('.nudge'); return n? n.textContent.trim().slice(0,200) : null`);
      ctx.check('a follow-up question is surfaced to the operator',
        typeof nudge === 'string' && !/no active nudge/i.test(nudge) && nudge.length > 0,
        `nudge area reads ${JSON.stringify(nudge)} — no utterance exists to trigger on, `
        + `because every transcription backend in asr-live is a test double`);
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

      await ctx.narrate('The mode the panel reads is carried on the live session stream');
      const stream = await ctx.sse(`/api/meetings/${ctx.state.meetingId}/session/stream`);
      const laneFrame = String(stream.text ?? '')
        .split('\n\n')
        .map((block) => block.split('\n'))
        .filter((lines) => lines[0] === 'event: lane')
        .map((lines) => JSON.parse((lines[1] ?? '').replace('data: ', '')))[0] ?? null;
      ctx.check('the stream tells the panel which mode it is in, before anything else',
        laneFrame !== null && typeof laneFrame.model_reachable === 'boolean',
        `first lane frame: ${JSON.stringify(laneFrame)}`);
      ctx.check('a reachable provider is reported as reachable, from a real call rather than from setup',
        laneFrame?.model_reachable === true,
        `lane says ${JSON.stringify(laneFrame)} while the credential test above reported reachable`);

      await ctx.narrate('A provider that refuses must be named, not left as a silent gap');
      // The credential here cannot submit a batch — the Analyst pass is refused
      // for want of a scope. That is a real upstream failure across a real seam,
      // so it is the one honest way to prove the degraded path live. It must
      // *not* move the panel: the compiler is a different workload on a
      // different entitlement from the slow lane the badge speaks for.
      await ctx.api('POST', `/api/engagements/${ctx.state.engagementId}/bank/compile`);
      await ctx.sleep(3000);
      const afterCompile = await ctx.sse(`/api/meetings/${ctx.state.meetingId}/session/stream`);
      const laneAfter = String(afterCompile.text ?? '')
        .split('\n\n')
        .map((block) => block.split('\n'))
        .filter((lines) => lines[0] === 'event: lane')
        .map((lines) => JSON.parse((lines[1] ?? '').replace('data: ', '')))[0] ?? null;
      ctx.check('a refused batch does not put the live panel into degraded mode',
        laneAfter?.model_reachable === true,
        `lane after a batch refused for scope: ${JSON.stringify(laneAfter)}`);

      await ctx.narrate('A write-up that stopped early has to say so, not just come back shorter');
      const completion = await ctx.api('GET', `/api/meetings/${ctx.state.meetingId}/debrief/completion`);
      ctx.check('a meeting with no debrief run is not reported as a failed one',
        completion.status === 404,
        `status ${completion.status}, ${JSON.stringify(completion.json).slice(0, 200)}`);
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
      // Two readings are acceptable and one is not. A figure is fine, and so
      // is saying nothing was compared — this meeting has no pair of
      // transcripts, because no speech vendor is wired. A bare "0%" is the one
      // answer that is wrong, and it is what a live run photographed, sitting
      // beside a count of nought disagreements.
      //
      // Asserting only `!== '0%'` would have gone green the moment the screen
      // started rendering an em dash, which is not "reporting how far the
      // engines agreed" either.
      const agreement = await ctx.text('.stat-value');
      const compared = await ctx.eval(
        `return document.body.textContent.includes('Not compared yet')`);
      ctx.check('the screen reports how far the engines agreed, or says it cannot',
        agreement !== null && agreement.trim() !== '0%'
          && (compared === true || /^\d+%$/.test(agreement.trim())),
        `agreement reads ${JSON.stringify(agreement)}, "not compared" shown: ${compared}`);

      const disagreementNote = await ctx.eval(
        `const s=[...document.querySelectorAll('section')].find(
           (n) => n.textContent.includes('Where they disagreed'));
         return s ? s.textContent.replace('Where they disagreed', '').trim().slice(0, 120) : null`);
      ctx.check('an empty disagreement list explains itself rather than reading as agreement',
        disagreementNote !== null && disagreementNote.length > 0,
        `the section under the heading reads ${JSON.stringify(disagreementNote)}`);
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

      // Both figures hold a release, and neither can be read without knowing
      // how much evidence is behind it. A live run photographed "100%" in
      // green against a bar of 70%, taken over a single rating, with nothing
      // on screen to say so.
      const gateCaptions = await ctx.eval(
        `return [...document.querySelectorAll('.stat')]
           .map((s) => s.textContent.trim()).join(' | ')`);
      ctx.check('each gate says how much evidence it rests on',
        typeof gateCaptions === 'string'
          && /(\d+ of \d+ rated|of \d+ rated|Nothing rated yet)/.test(gateCaptions),
        `the gate tiles read ${JSON.stringify(gateCaptions)}`);
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
