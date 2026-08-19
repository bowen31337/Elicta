# 10. Set up the services Elicta uses

*For whoever administers Elicta for the team · once, then rarely*

Elicta relies on outside services to transcribe audio and to do the writing-up.
Those are configured in the app, not by an engineer editing a server, because
the person who needs a key changed is not usually the person who could deploy.

The screen is organised by service — one section for the AI work, one for
transcription, one for managed capture — and each section carries its own
readiness. A credential lives in the section for the thing it authenticates,
rather than in a single list of keys that gave no clue which was which.

## First run

Nothing is set up, and the screen says so plainly rather than looking ready:
every section reads "needs a credential" or "needs a key" beside its title.

![Before anything is configured](screenshots/settings-first-run.png)

## Choosing where the AI work goes

You can point Elicta at Anthropic directly, at Amazon, Google or Microsoft's
hosted versions, or at your own internal gateway. Each option asks only for
what it actually needs, and refuses to save if something is missing — better a
message here than a failure in the middle of writing up a meeting.

Two of those options ask for no key at all. If you run on Amazon or Google,
Elicta uses the permissions your cloud account already grants it. Asking you to
paste a key there would mean creating a long-lived credential where your own
platform has a better mechanism.

![Pointing Elicta at an internal gateway](screenshots/settings-compatible-endpoint.png)

## Your key, or your token

Both are supported, because organisations issue different things. You choose
which one is in use, and only that one is asked for — a credential of the other
kind that is still stored is named in a line of its own, with a way to clear it,
so nothing is held that the operator cannot see.

![Credentials configured, with the one in use marked](screenshots/settings-configured.png)

Four things on this screen exist to stop a credential leaking:

- The field is always empty. Elicta never sends a stored key back to the
  screen, so there is nothing to display — it shows the last four characters
  instead, which is enough to tell one key from another.
- Leaving it blank means "leave it alone", so saving a different setting cannot
  wipe your key by accident.
- **Clear** is a separate, deliberate action, because it cannot be undone.
- **Test** actually checks the credential against the service rather than
  reporting "configured" as though it meant "working". If it fails, you see the
  service's own explanation — never your key.

## Choosing transcription services

The live path and the recording are set up separately because they are bought
on different things: one on how quickly it can tell a sentence has finished,
the other on two services disagreeing usefully. The key sits with them, named
after the vendor selected above it — "AssemblyAI key", not "speech-to-text
vendor key".

![Transcription services](screenshots/settings-speech-vendors.png)

The two used for the recording must be different companies. The same one twice
would agree with itself and flag nothing — so the form will not accept it. You
can also point Elicta at a service we do not ship support for, though it will
tell you that some features then need checking against that provider yourself.

## Where this stands

| | |
|---|---|
| ✅ Ready | Everything on this screen, including live credential testing for the AI provider and both supported transcription services |
| ✅ Ready | For a shared deployment the key can now come from your own secret store — 1Password, Vault, AWS, Google, anything with a command line. If the store cannot be reached, Elicta refuses to start and says why, rather than quietly making a new key that leaves the other machines unable to read anything |
