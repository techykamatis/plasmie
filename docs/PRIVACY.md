# Plasmie privacy

Plasmie is built so your work record stays on your Mac. This is what it does, from the code.

## What it reads

Only sources you switch on, and only your own:

- **Slack**: messages you sent and received (your Slack user token).
- **GitHub**: pull requests and issues you opened or commented on, read with a GitHub token you paste in (read-only is enough; kept in the Keychain).
- **Local git commits**: your own commit messages from repositories on your Mac, in the folders you list. No network.
- **Confluence**: pages you created or edited (your Atlassian address, email and API token).
- **Outlook** (mail and calendar): only after you click Connect and approve the sign-in.
- **Claude Code / AgentCLI sessions**: their local session logs on your Mac. No network.

Before anything is written, a redactor strips things that look like passwords, API keys and tokens.

## Where it's stored

- Your notes: the vault folder you chose.
- Plasmie's settings and state: `~/Library/Application Support/Plasmie`. Logs: `~/Library/Logs/Plasmie` (including a record of what was sent to the on-device model, so you can check it).
- Sign-ins (tokens, the Outlook refresh token, your Atlassian email): your **login Keychain**, as items named "Plasmie", never in a plain file.

## Network use

- Each connector you switch on talks only to its own service (Slack, GitHub, your Atlassian site, Microsoft for Outlook) to read your own account. A connector that's off makes no calls.
- First setup downloads, once: the search engine (qmd, from npm) and its search models (from Hugging Face).
- That's all. No telemetry, no analytics, no crash reports, nothing uploaded. (Plasmie's code is checked for this: a test fails if a new network address appears without being listed here.)

## The AI

Summaries, nightly filing and answers all run on your Mac with Apple's on-device model (Apple Intelligence). Apple's cloud (Private Cloud Compute) is never used, and no other AI service is called.

## iCloud sync (optional, off by default)

If you turn it on, Plasmie copies your curated notes, daily digests and Obsidian display settings to iCloud Drive › Plasmie so you can read them on your iPhone or iPad. It never copies raw captures (your Slack messages, sessions), your questions, plugin settings, or any note that looks like it holds a password. While it's on, those notes are also stored in your iCloud account (end-to-end encrypted only if you use Apple's Advanced Data Protection).

## Diagnostics

**Copy diagnostics** puts a report on your clipboard for you to send if you choose: versions, which connectors are on and working, and recent run summaries. It leaves out your notes, messages, account names and passwords. Nothing is sent automatically.

## Deleting everything

Plasmie window > Maintain > **Reset Plasmie…** removes Plasmie's background jobs, data, logs and preferences, then quits. Then delete the app. Your notes folder is never touched; delete it yourself if you want the notes gone. Plasmie's Keychain items can be removed in Keychain Access (search "Plasmie").
