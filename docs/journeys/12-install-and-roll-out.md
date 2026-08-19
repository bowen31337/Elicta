# 12. Get Elicta onto people's machines

*For IT · once, before a pilot · then for every user at first launch*

This is invisible when it goes well and very visible when it does not. A
meeting tool that asks every person for permission to record their screen
generates the same support ticket over and over.

## What IT does once

**Push it through your device management.** That is the preferred route, not
the fallback, because it lets you grant microphone and screen-recording access
centrally. Nobody sees a permission prompt, and nobody has to be talked through
one.

**Keep the plain installers as a backup**, for machines outside management.

**Agree the security exception before the pilot, not during it.** An unfamiliar
application opening an audio stream is exactly what endpoint security software
is built to flag — and it will flag it in the middle of someone's client
meeting if this is left until then.

Elicta ships for Windows and Mac together, signed and verified by both
operating systems.

## What the person sees

The About screen answers the questions a pilot actually raises — is this build
trustworthy, how did it get here, what is it allowed to do — rather than
sending someone into system settings to find out.

![A managed install, with permissions already granted](screenshots/about-managed.png)

On a machine outside management, the same screen names what is missing, what it
blocks, and that IT can grant it centrally.

![An install missing a permission it needs](screenshots/about-unmanaged.png)

## Both platforms have to behave identically

This is checked automatically rather than assumed: the same recorded meeting is
replayed on Windows and on Mac, and the suggestions must come out identical. If
they diverge, the release stops. Two platforms quietly behaving differently
would mean every quality judgement only applied to whichever one it was made
on.

## Where this stands

| | |
|---|---|
| ✅ Ready | Packaging for both platforms, signing and verification, the managed-deployment profile, and the automatic check that both platforms behave identically |
| ✅ Ready | The About screen reports the real version and platform it is running on |
| ✅ Ready | Whether the build is signed, and how it was installed, are now read from the operating system rather than taken on trust. Where the answer cannot be established the screen says so, which reads differently from “unsigned” — an IT reviewer needs to tell those apart |
| ✅ Ready | Elicta checks for a new version on launch and tells you what is waiting. It never installs on its own — an update that restarted the app by itself would eventually do it during a client meeting |
| ⏳ Not yet | The update service needs its signing key and address set before a release goes out. Until then the screen says there is no update channel configured, rather than accepting whatever it is offered |
