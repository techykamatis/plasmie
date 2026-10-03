# 0021 · Credentials in the login Keychain, via /usr/bin/security only

- **Status:** Accepted · 2026-10-04
- **Area:** Security, architecture

## Context
Connector credentials lived in `~/.claude/.env`, a plain file shared with other tools,
sourced whole by the hourly ingest (so every job saw every secret in it, Plasmie's or not)
and written by the app and `msgraph.py`. Plasmie is about to ship to friends, ad-hoc signed:
its code identity changes with every build. An earlier Keychain attempt was reverted.

## Decision
- **What:** `SLACK_USER_TOKEN`, `JIRA_API_TOKEN`, `CONFLUENCE_API_TOKEN`, `MS_REFRESH_TOKEN`,
  and the Atlassian email (`JIRA_EMAIL`, `CONFLUENCE_EMAIL`, half of a Basic-auth credential)
  are generic passwords in the login Keychain: service `Plasmie`, account = the variable name.
  Non-secret settings (site URL, orgs, folders, switches) stay in `config.env`.
- **Who touches them:** only `/usr/bin/security`, from Python (`keychain.py`), shell
  (`plasmie_secrets` in `plasmie-env.sh`) and Swift (`Keychain.swift`). An item `security`
  creates trusts exactly that tool to decrypt it, by Apple's code requirement, so neither an
  app rebuild nor a launchd job is ever a new identity asking for access. No `-T` flag:
  with an explicit trusted list every later `-U` update prompts (tested).
- **Never on a command line:** writes pipe the command into `security -i` on stdin. Its line
  limit is 4096 bytes; a longer token falls back to `-w <token>` as an argument for the
  call's few milliseconds, visible only to same-user processes, which can already read the
  item through `security`, so it adds no reader.
- **Least privilege:** jobs get only Plasmie's credentials, and only the jobs that call a
  connector (ingest, backfills, doctor), not summarize/promote.
- **Migration, once:** an install that has run before copies its Plasmie keys out of
  `~/.claude/.env` (tokens to the Keychain, settings to `config.env`), never edits that
  file, never overwrites a newer value, and marks itself done (`.secrets-migrated`). It runs
  from setup and lazily from the first job or Settings open. Until it succeeds the old
  file's tokens are still used, so an upgrade can't cut a connector off. A fresh install
  imports nothing: another tool's file is not Plasmie's to read.
- The Settings window never shows a token; it shows "Connected" from `plasmie-doctor.py`.

## Alternatives rejected
- **Security.framework from the app** (SecItemAdd): items would trust only that build; each
  update and every hourly job would prompt.
- **`-T /usr/bin/security`**: updates prompt.
- **Deleting the keys from `~/.claude/.env` after migrating**: other tools read them.

## Consequences
Any process running as the user can still read the items by running `security` (the same
reach the plain file had, minus backups, grep and accidental sharing). The values no longer
leak into unrelated jobs' environments. Tests use a throwaway keychain (`PLASMIE_KEYCHAIN`);
a path that doesn't exist is refused, because `security` would silently use the login one.
