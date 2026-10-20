# 0024 · Background jobs belong to the app (SMAppService)

- **Status:** Accepted
- **Area:** Architecture, distribution

## Context
The pipeline runs on a schedule while the app is closed. Jobs installed by hand into
`~/Library/LaunchAgents` outlive the app, point at whatever folder installed them, and are
invisible to the user. Ingest appends rather than de-duplicating, so two sets of jobs running
at once duplicate data.

## Decision
- **Five jobs ship inside the bundle** (`Contents/Library/LaunchAgents`): ingest at :07
  hourly, summarize at :15, improve at :17, promote at 02:30, snapshot at 00:47. Labels are
  `com.plasmie.<job>`, and the app registers them with `SMAppService.agent`. They show in
  System Settings › General › Login Items under Plasmie, survive a restart, run the bundled
  engine (through `plasmie-job.sh`), and stop when the app is deleted. Reset unregisters them.
- **Logs:** a plist inside a bundle can't name a log path in the user's home, so jobs pass
  `PLASMIE_JOB_LOG` and `plasmie-env.sh` sends their output to `~/Library/Logs/Plasmie`.
- **Never two sets at once.** The dev path, `launchd/install.sh`, runs jobs from a checkout
  as `com.plasmie.dev-<job>`. The app registers its own only when no dev agent and no job
  from an older install is loaded (`BackgroundJobs.legacyPresent`, via `LegacyJobs`), and
  `run-ingest.sh` also takes a lock.
- **Older installs' jobs are retired.** Jobs an older install registered under another
  bundle id can't be unregistered by this app, so `plasmie-migrate.py` boots them out
  (`launchctl bootout gui/$UID/<label>`) and fails, to be retried, while one is still loaded.
  The app runs that again on its own (`--retire-old-jobs`) if one comes back after a login.
  `launchd/install.sh retire` (also run by `install.sh` and `uninstall`, before installing
  `dev-*`) boots out and removes any dev agent under an older label and leaves
  `com.plasmie.dev-*` alone.
- **Approval:** if macOS holds the jobs for approval, the island and the window say so, with
  a button to Login Items. Open-at-login is separate and only ever the user's choice.

## Consequences
- Deleting the app stops the jobs; nothing scheduled is left behind.
- Diagnostics list the older labels too, so a stray job is visible in a bug report.
