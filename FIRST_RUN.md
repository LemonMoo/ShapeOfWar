# Shapes of War — first run on a new PC

Windows shows a blue **"Windows protected your PC"** box the first time you open
`ShapesOfWarLauncher.exe`. That's Microsoft Defender SmartScreen. It appears for
any app it hasn't seen many people run before — it is not a virus warning, and
it does not mean anything is wrong with the download.

## Getting past it

1. Click **More info** on the blue box.
2. Click **Run anyway**.

That's it — Windows remembers the choice, so it only happens once.

If there's no "Run anyway" button, unblock the file first:

1. Right-click `ShapesOfWarLauncher.exe` → **Properties**
2. At the bottom of the General tab, tick **Unblock**
3. Click **OK**, then open it normally

## Why it happens

The launcher isn't code-signed (a code-signing certificate is a paid, per-year
thing). Unsigned apps start with no reputation with SmartScreen, so Windows
warns until enough people have run that exact file. Because the launcher
updates the *game* rather than itself, its own file stays the same from release
to release, so the warning fades on its own as more people use it.

## Only download it from here

https://github.com/LemonMoo/ShapeOfWar/releases/latest

Grab `ShapesOfWarLauncher.exe` from the latest release. Don't accept it from
anyone via chat/email attachments — if it didn't come from that link, don't run
it.
