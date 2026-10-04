# 0026 · Background jobs belong to the app (SMAppService)

- **Status:** Accepted · 2026-10-04 · job labels and bundle renamed by 0027 (`com.plasmie.*`, `Plasmie.app`), then by 0028 (`com.plasmie.*`, `Plasmie.app`)
- **Area:** Architecture, distribution

## Decision
The five scheduled jobs (ingest :07 hourly, summarize :15, improve :17, promote 02:30,
snapshot 00:47) ship inside `Plasmie.app/Contents/Library/LaunchAgents` as `com.plasmie.*`
and the app registers them with `SMAppService.agent`. They show in System Settings ›
General › Login Items as Plasmie, survive a restart, run the bundled engine, and stop when
the app is deleted. Reset unregisters them.
- A plist inside a bundle can't name a log path in the user's home, so jobs pass
  `PLASMIE_JOB_LOG` and `plasmie-env.sh` redirects their output to `~/Library/Logs/Plasmie`.
- **Never two sets at once.** Ingest appends (it doesn't de-duplicate), so the old
  `com.plasmie.*` agents from `~/Library/LaunchAgents` are retired by migration step 3 and
  the app registers only once none remain; `run-ingest.sh` also takes a lock.
- If macOS holds the jobs for approval, the island and window say so with a button to
  Login Items. Open-at-login is separate and only ever the user's choice.
- `launchd/install.sh` stays as the dev-checkout path (jobs running a checkout).

## Consequences
- Labels are generic (`com.plasmie.*`): the last owner-specific identifier left is the
  bundle id, which changes with the Developer ID work.
- Switched on the owner's Mac on 2026-10-04 01:10; first runs from the bundle verified
  in the audit log.
