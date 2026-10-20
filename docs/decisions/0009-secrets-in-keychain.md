# 0009 · Credentials in the login Keychain, via /usr/bin/security only

- **Status:** Accepted
- **Area:** Security, architecture

## Context
Connectors need tokens. A plain dotfile shared with other tools exposes every secret in it
to every job that sources it, and to backups, grep and accidental sharing. Plasmie ships
ad-hoc signed, so its code identity changes with every build: a Keychain item tied to the
app binary would prompt after each update and from every background job.

## Decision
- **What:** `SLACK_USER_TOKEN`, `JIRA_API_TOKEN`, `CONFLUENCE_API_TOKEN`, `MS_REFRESH_TOKEN`
  and the Atlassian email (`JIRA_EMAIL`, `CONFLUENCE_EMAIL`, half of a Basic-auth
  credential) are generic passwords in the login Keychain: service `Plasmie` (from the brand
  constant, [0014](0014-brand-plasmie.md)), account = the variable name. Non-secret settings
  (site URL, orgs, folders, switches) live in `config.env`.
- **Who touches them:** only `/usr/bin/security`, from Python (`keychain.py`), shell
  (`plasmie_secrets` in `plasmie-env.sh`) and Swift (`Keychain.swift`). An item `security`
  creates trusts exactly that tool to decrypt it, by Apple's code requirement, so neither an
  app rebuild nor a launchd job is a new identity asking for access. No `-T` flag: with an
  explicit trusted list every later `-U` update prompts (tested).
- **Never on a command line:** writes pipe the command into `security -i` on stdin. Its line
  limit is 4096 bytes; a longer token goes as `-w <token>` for the call's few milliseconds,
  visible only to same-user processes, which can already read the item through `security`,
  so it adds no reader.
- **Least privilege:** jobs get only Plasmie's credentials, and only the jobs that call a
  connector (ingest, backfills, doctor) get them; summarize and promote don't.
- **Importing from `~/.claude/.env`, once:** an install that has run before and keeps its
  keys in that file copies its own keys out (tokens to the Keychain, settings to
  `config.env`, under their `PLASMIE_*` names), never edits the file, never overwrites a
  value already set (a rotated Outlook token must not be rolled back), and marks itself done
  (`.secrets-migrated`) only when every token landed. It runs from setup and lazily from the
  first job or Settings open. Until it succeeds, the file's tokens are still used, so a
  connector is never cut off. A fresh install imports nothing: another tool's file is not
  Plasmie's to read.
- The Settings window never shows a token; it shows "Connected" from `plasmie-doctor.py`.

## Alternatives rejected
- **Security.framework from the app** (`SecItemAdd`): items would trust only that build, so
  each update and every hourly job would prompt.
- **`-T /usr/bin/security`:** updates prompt.
- **Deleting the keys from `~/.claude/.env` after importing:** other tools read them.

## Consequences
Any process running as the user can still read the items by running `security`: the same
reach a plain file has, minus backups, grep and accidental sharing. The values stay out of
unrelated jobs' environments. Tests use a throwaway keychain (`PLASMIE_KEYCHAIN`); a path
that doesn't exist is refused, because `security` would silently use the login one.
