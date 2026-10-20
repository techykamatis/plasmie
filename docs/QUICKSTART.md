# Plasmie quickstart

Plasmie is a small pink blob that lives beside your MacBook's notch. It gathers what you work on (messages, code, notes), writes it into a folder of notes you can read in Plasmie, and answers questions about it. Everything runs on your Mac. Nothing is uploaded.

## What you need

- A Mac with Apple silicon (M1 or newer), on macOS 26 or later
- **Apple Intelligence turned on** (System Settings > Apple Intelligence & Siri). Plasmie's summaries and answers come from Apple's on-device model
- About 6 GB of free disk space and an internet connection for the first setup (search models, about 4 GB, downloaded once)
- Nice to have: Apple's Command Line Tools (keeps a history of your notes); setup offers to install them. Obsidian is optional: another way to browse and edit your notes

## Install

It takes a minute.

- **Step 1.** Open the Plasmie disk image and drag **Plasmie** onto **Applications**.
- **Step 2.** Open Plasmie from Applications. When your Mac warns you, click **Done**. (It warns because Plasmie isn't from the App Store.)
- **Step 3.** Go to **System Settings > Privacy & Security**. Click **Open Anyway** and enter your password.

You only do this once, and it's the only warning you'll see. If you open Plasmie straight from the disk image, it offers to move itself to Applications first. Say yes.

## First run

1. **Checklist.** Plasmie checks your Mac. Anything missing has a button (Download, Install, Settings). Fix it, click **Check again**, then **Continue**.
2. **Where your notes live.** Pick a folder (default `~/knowledge`). If you already have a Plasmie vault, choose it: Plasmie uses it as it is and never overwrites it.
3. **Your choices.** Open Plasmie at login? Mirror your notes to iCloud Drive (for Obsidian on iPhone)? Both are off unless you turn them on.
4. **Setup** runs on its own; keep working. If it stops, click **Try again** and it picks up where it left off.

Then Plasmie shows you around the notch in three short steps.

## Everyday use

- **Hover over the notch**: a fun fact from your own notes (↻ for another, ↗ to open it), plus **Ask**, **Ingest** (gather now), **Map** (your notes; click one to read it) and **More**.
- **Ask**: press Control-Option-Command-K anywhere and ask about your work; answers show their sources.
- **More** opens the Plasmie window: status, connectors, settings, trophies.
- Plasmie gathers every hour, writes a daily summary, and files lasting knowledge overnight (around 2:30 am).

## Connectors

In the Plasmie window, each source has an On/Off switch: Slack, GitHub, local git commits, Confluence, Outlook and Claude Code sessions. Network ones start **off**; local ones start on only if they exist on your Mac. Off means nothing is read. Sign-ins are kept in your Mac's Keychain. For GitHub, paste a token from github.com › Settings › Developer settings (read-only access is enough); nothing else to install.

## Where things live

- Your notes: the folder you chose. Keep it on your Mac (to read it on your phone, use the iCloud mirror instead).
- Plasmie's own data: `~/Library/Application Support/Plasmie`; logs: `~/Library/Logs/Plasmie`.

## Coming from Plasmie or Plasmie

Plasmie used to be called Plasmie, and Plasmie before that. Quit the old app, move it from Applications to the Bin, install Plasmie as above, then open Plasmie: it brings your notes, data, settings and connector sign-ins along by itself. One thing to redo in the Plasmie window: turn **Open at login** back on if you used it.

## Uninstall

Plasmie window > Maintain > **Reset Plasmie…** removes Plasmie's background jobs, settings, sign-ins and logs, then quits. **Your notes are never touched.** Then drag Plasmie from Applications to the Bin. Delete your notes folder only if you want the notes gone.

## Trouble?

1. **"Plasmie can't be opened"**: do Step 3 above.
2. **Apple Intelligence is off or still downloading**: the island tells you; turn it on in System Settings, or wait for the download.
3. **Nothing captured yet**: switch a connector on, then press **Ingest**. Quiet sources can take a day to show anything.
4. **Something looks broken**: Plasmie window > Maintain > **Run setup again…** repairs it and keeps your notes and settings.
5. **Need help**: Plasmie window > Maintain > **Copy diagnostics**, then paste it into a message. It leaves out your notes, messages and passwords.
