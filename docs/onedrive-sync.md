# OneDrive sync (cross-device)

The vault lives on **local disk** (`~/knowledge`) — the source of truth. The loop's
launchd agents only ever read/write there, because `~/Library/CloudStorage/` is
TCC-protected and background reads fail from it (see the
`knowledge-vault-stays-local` constraint / memory).

For cross-device access, a **one-way mirror** copies the local vault into OneDrive.

## How it works

- `mirror-to-onedrive.sh` — `rsync -a --delete` from `$VAULT_DIR` → `$MIRROR_DEST`.
  - Reads both paths from `config.env` (quoted, so paths with spaces like `AI Labs` are safe).
  - No-ops quietly if `MIRROR_DEST` is unset (sync not configured).
  - Refuses to run if the source looks empty/broken (guards against `--delete` wiping the replica).
  - Excludes `.DS_Store`, `.ruff_cache/`, `.obsidian/workspace*.json`.
  - rsync writes-then-renames, so a file the loop is mid-rewrite never propagates half-written.
- `com.plasmie.dev-mirror` LaunchAgent runs it hourly at `:40`.
- Direction is **local → OneDrive only**. Never edit the OneDrive copy expecting it to flow back.

## Why writing to CloudStorage works when reading didn't

The loop's *reads* from CloudStorage failed under launchd (TCC). Writing works because
`/bin/bash` has Full Disk Access granted, and the mirror only *writes* to CloudStorage
(it reads from the unprotected local vault). On a fresh machine this grant may be needed:
**System Settings ▸ Privacy & Security ▸ Full Disk Access ▸ add `/bin/bash`.**

## Verify

```sh
ls -ld ~/knowledge                                   # a real dir, NOT a CloudStorage symlink
launchctl kickstart -k gui/$(id -u)/com.plasmie.dev-mirror
launchctl list com.plasmie.dev-mirror | grep LastExitStatus   # = 0
tail -1 ~/.plasmie/logs/mirror.log            # "mirror rc=0"
# replica has every note:
diff <(cd ~/knowledge && find . -name '*.md'|sort) \
     <(cd "$(. ~/.plasmie/config.env; echo "$MIRROR_DEST")" && find . -name '*.md'|sort)
```
