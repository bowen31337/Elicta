# Setting It Up

Elicta uses outside services for two things: turning speech into text, and doing
the writing-up afterwards. Somebody has to tell it which services to use and give
it permission to use them. It is done in the app, once, by whoever administers
Elicta for the team — not by an engineer editing a server somewhere, because the
person who needs a key changed is rarely the person who could deploy one.

## Before anything is set up

On first run the screen says plainly that nothing is configured, rather than
looking ready and failing later.

![Before anything is configured](../../docs/journeys/screenshots/settings-first-run.png)

## Choosing where the writing-up happens

You can point Elicta at the company that makes the underlying service directly,
at Amazon's, Google's or Microsoft's hosted versions of it, or at your
organisation's own internal gateway. Each choice asks only for what it actually
needs, and refuses to save if something is missing — a message here is better
than a failure halfway through writing up a meeting.

Two of those choices ask for no key at all. If you already run on Amazon or
Google, Elicta uses the permissions your cloud account grants it. Asking you to
paste a key there would mean creating a long-lived credential in a place where
your own platform has a better mechanism.

![Pointing Elicta at an internal gateway](../../docs/journeys/screenshots/settings-compatible-endpoint.png)

## Keys and tokens

Both are supported, because organisations issue different things. You choose
which is in use and Elicta labels it, so there is never any doubt about which
credential a failure came from.

![Credentials configured, with the one in use marked](../../docs/journeys/screenshots/settings-configured.png)

Four details on this screen exist to stop a credential leaking, and they are
worth knowing about because they change how the screen behaves:

```diagram
type: stack
title: Why the credential fields behave oddly
item: The field is always empty | Elicta never sends a stored key back to the screen, so there is nothing to show. It displays the last four characters instead, which is enough to tell one key from another.
item: Blank means leave it alone | Saving a different setting cannot wipe your key by accident.
item: Clear is separate and deliberate | Removing a credential is its own action, because it cannot be undone.
item: Test really tests | It checks the credential against the service rather than reporting "configured" as though that meant "working". If it fails you see the service's own explanation, never your key.
```

## Choosing transcription services

The live transcription and the after-the-meeting transcription are set up
separately, because they are bought on different qualities. The live one is
chosen for how quickly it can tell that a sentence has finished. The
after-the-meeting ones are chosen for being accurate — and for disagreeing
usefully with each other.

![Transcription services](../../docs/journeys/screenshots/settings-speech-vendors.png)

The two used for the recording must be different companies. The same service
twice would agree with itself and flag nothing, so the form will not accept it.
You can also point Elicta at a service it does not ship support for, though it
will tell you that some behaviour then needs checking against that provider
yourself.

## For a shared installation

Where several machines share a deployment, the key can come from your own secret
store rather than being typed in — anything with a command line will do. If the
store cannot be reached, Elicta refuses to start and says why, rather than
quietly generating a new key that would leave the other machines unable to read
anything.

<!-- HANDBOOK-NAV -->

---

← [What Elicta Does](01-what-elicta-does.md) · [Contents](../index.md) · [Getting It Onto People's Machines](03-installing-it.md) →
