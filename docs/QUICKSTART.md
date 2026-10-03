# Plasmie quickstart

Plasmie is a small pink blob that lives beside your MacBook's notch. It quietly gathers what you work on (messages, code, notes), writes it into a folder of notes you can read in Obsidian, and answers questions about it. Everything runs on your Mac; nothing is uploaded.

## What you need

- A Mac with Apple silicon (M1 or newer)
- About 12 GB of free disk space (Plasmie downloads roughly 9 GB of models, once)
- An internet connection for that first setup
- Node.js 22 or newer (powers the notes search). Get it at nodejs.org
- Apple Intelligence turned on (System Settings > Apple Intelligence & Siri). Plasmie uses Apple's on-device model when it can, and a local model it downloads when it can't
- Nice to have: Obsidian (to read your notes), Apple's Command Line Tools (a history of your notes), Claude Code (nightly filing of new knowledge)

## Install

1. Open the Plasmie disk image and drag **Plasmie** onto **Applications**.
2. Open Plasmie from Applications. macOS will say it can't check it for malicious software, because Plasmie isn't from the App Store yet. Click **Done**.
3. Open **System Settings > Privacy & Security**, scroll down, and click **Open Anyway** next to Plasmie. Enter your password.

You only do this once. (On recent macOS, right-click > Open no longer skips this step.)

## First run

Plasmie opens a checklist of what your Mac needs. Anything missing has a button next to it (Download, Install, Storage settings). Fix those, click **Check again**, then **Set up Plasmie**.

Setup downloads about 9 GB once: roughly 4.9 GB for the answer model and 3.7 GB for the search models. You can keep working meanwhile. If it stops, reopen Plasmie and click **Try again**; it picks up where it left off. At the end it creates your notes folder (default `~/knowledge`) and starts the background helpers.

## Everyday use

- **Hover over the notch** and Plasmie's island opens: a fun fact from your own notes, plus buttons for **Ask**, **Ingest** (gather now), **Vault** (open your notes in Obsidian) and **More**.
- **Ask**: press Control-Option-Command-K anywhere, type a question about your work, and read the answer with its sources.
- **More** brings the Plasmie window forward: status, connector switches, settings.
- Plasmie gathers new activity every hour, writes a short summary, and files lasting knowledge overnight (around 2:30 am).

## Connectors

Open the Plasmie window (**More**) and go to **Connectors**. Each source has its own On/Off switch and is off until you set it up: Slack, GitHub, local git commits, Confluence, Claude Code sessions, AgentCLI sessions (Outlook is not working yet). Off means nothing is read from it. Turning one back on does not fill in the time it was off. Notes already captured stay.

## Where things live

- Notes: the vault folder you chose (default `~/knowledge`). Keep it on your Mac, not in iCloud or OneDrive.
- Plasmie's data and models: `~/Library/Application Support/Plasmie`
- Logs: `~/Library/Logs/Plasmie`
- Connector passwords/tokens: `~/.claude/.env` (see Privacy)

## Uninstall

A "Reset Plasmie" button is planned; for now:

1. Quit Plasmie (hover the notch, or right-click it > Quit Plasmie).
2. In Terminal, stop the background helpers (this works even after the app is gone):
   ```
   for l in com.plasmie.dev-ingest com.plasmie.dev-summarize com.plasmie.dev-improve com.plasmie.dev-promote com.plasmie.dev-snapshot com.plasmie.mlx-server; do launchctl bootout gui/$(id -u)/$l 2>/dev/null; rm -f ~/Library/LaunchAgents/$l.plist; done
   ```
3. Delete **Plasmie** from Applications.
4. Delete `~/Library/Application Support/Plasmie` and `~/Library/Logs/Plasmie`.
5. Your notes folder is yours: delete it only if you want the notes gone.
6. Optional: remove any Plasmie keys (SLACK_USER_TOKEN, JIRA_API_TOKEN, and so on) from `~/.claude/.env`, and the search engine with `npm uninstall -g @tobilu/qmd` plus `~/.cache/qmd`.

## Trouble?

1. **"Plasmie can't be opened"**: use the Open Anyway steps above.
2. **Apple Intelligence is off**: turn it on in System Settings. Plasmie still works without it, using the local model.
3. **Node.js missing or too old**: the checklist shows it; install Node 22+ from nodejs.org, then click Check again.
4. **Nothing captured yet**: all connectors start off. Switch one on and add its details, then press **Ingest** in the island. Quiet sources can take a day or more to show anything.
5. **Need to send logs**: open Finder > Go > Go to Folder, paste `~/Library/Logs/Plasmie`, and send the files in it (look them over first; they can contain snippets of your work).
