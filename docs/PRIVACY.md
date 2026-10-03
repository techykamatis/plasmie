# Plasmie privacy

Plasmie is built so your work record stays on your Mac. This is what it does, from the code.

## What it reads

Only sources you switch on, and only your own:

- **Slack**: messages you sent and received (your Slack user token).
- **GitHub**: pull requests and issues you opened or commented on, in the organisations you list (through the `gh` command-line tool, signed in as you).
- **Local git commits**: your own commit messages from repositories cloned on your Mac (default folder `~/code`). No network.
- **Confluence**: pages you created or edited (your Atlassian address, email and API token).
- **Claude Code sessions**: local session logs in `~/.claude/projects`.
- **AgentCLI sessions**: its local database, `~/.agentcli/cli/db/db.sqlite`.
- **Outlook** (mail and calendar): the code exists but is switched off in this version.

Before anything is written, a redactor strips things that look like passwords, API keys and tokens.

## Where it's stored

- Your notes: the vault folder you chose (default `~/knowledge`).
- Plasmie's settings, state and models: `~/Library/Application Support/Plasmie`
- Logs, including a record of what was sent to the on-device model: `~/Library/Logs/Plasmie`

## Network use

- Each connector you enable talks to its own service (Slack, GitHub, your Atlassian site), to read your own account.
- One-time setup downloads: the AI and search models from huggingface.co, Python packages from PyPI, and the search tool (qmd) from npm.
- That's all. The app itself has no telemetry and no analytics, and nothing is uploaded.

## The AI

Summaries and answers run on your Mac. Plasmie uses Apple's on-device model (Apple Intelligence) when available, and otherwise a Gemma model it downloads and runs locally. Nightly filing runs on the local model too. Private Cloud Compute (Apple's cloud) is not used.

## Secrets

Connector tokens are saved as plain text in `~/.claude/.env`, readable only by your account (permissions 600). That file is shared with other tools such as Claude Code. Moving them into the macOS Keychain is planned. Until then, don't share that file.

## Deleting everything

See "Uninstall" in the Quickstart. Deleting the app, the two Plasmie folders, and your notes folder removes everything Plasmie made, apart from tokens in `~/.claude/.env`. Disconnecting a connector in Plasmie removes its token from that file.
