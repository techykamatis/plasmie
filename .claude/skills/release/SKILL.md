---
name: release
description: Cut a Plasmie release. Builds the DMG installer locally with app/make-release.sh, checks it (mounts, codesign, version, SHA-256), writes plain-English release notes for the people who install Plasmie, then, only after an explicit yes, tags v<VERSION> and creates a draft GitHub release with the DMG and .sha256 attached. After the release is published, it brings the website's version number (plasmie-site) in line with it. Use this whenever the user says /release, "ship 0.x", "cut a release", "publish the DMG", "put the installer on GitHub", "write release notes", "tag this version", "update the version on the website", or asks for a dry run or preview of release notes, even when they don't say "release". It does not build in CI.
---

# /release: build locally, release on GitHub

Plasmie ships as an ad-hoc-signed DMG built on this Mac. A release has two halves:

- **Local and safe to repeat:** pre-flight, build, verify, write the notes.
- **External and hard to undo:** push, tag, and the GitHub release. Other people can
  see these and download from them. Do them only after the user types an explicit yes
  in this conversation. The plan you wrote is not consent, and neither is an earlier
  "go ahead with the release".

Repo: `github.com/techykamatis/plasmie`, default branch `main`, version in `./VERSION`.
The helper is `.claude/skills/release/scripts/release.py`, referred to below as `R`.
Run it with the system `python3` from the repo root. It never builds, tags or pushes.

Releases go to the repo named by `RELEASE_REPO` at the top of `release.py`, the one
place it is set (default `techykamatis/plasmie`). Always pass it to `gh` as `-R "$REPO"`,
so that switching to a separate public releases repo later is a one-line change.

```bash
R=.claude/skills/release/scripts/release.py
REPO="$(python3 $R repo)"
```

## Dry run (`/release --dry-run`, "preview the notes")

Use this when the user wants to see the notes, or when the tree is mid-work:

```bash
python3 $R dry-run [--since <ref>]
```

This runs the real pre-flight and prints its verdict, so a dirty tree still shows
**FAIL**. Then it prints a warning and carries on to the notes material. Write the notes
from that material (step 3), lint them, and show them. Do not build, verify, tag or push
in a dry run. Write the draft notes to a temp file, not to `app/build`, which may hold an
installer the user is testing.

## 1. Pre-flight

```bash
python3 $R preflight
```

It checks: on the default branch; a clean working tree, untracked files included (the
build compiles whatever is in `app/Sources`, so a stray file would ship in a build that
no commit describes); VERSION is X.Y.Z; HEAD is the `chore: release <VERSION>` commit
(a warning if not); not behind origin; no `v<VERSION>` tag locally or on GitHub, and no
release by that name; `gh auth status`; `.venv/bin/python3` exists for the test gate.
It also warns when the website's version spans differ from VERSION. That's expected
until this release is published (step 7 updates them), but an unmarked or missing site
is worth mentioning.

On any **FAIL**, stop. Quote the failing lines, including the list of uncommitted
paths, and say what would fix each one. Do not commit, stash or clean other people's
work to get past it. That is the user's call.

## 2. Build and verify (local only)

The build happens here, on this Mac, and nowhere else. Never in CI, never in a GitHub
Action, never by asking someone else to build.

Before building, warn if `app/build` holds anything, because `make-app.sh` wipes it.
Then:

```bash
git rev-parse HEAD > /tmp/plasmie-release-head      # the commit this build is from
app/make-release.sh                                 # tests, ruff, bash -n, make-app, make-dmg
python3 $R verify
```

`make-release.sh` takes a few minutes. `make-dmg.sh` drives Finder through AppleScript
and checks the window layout itself, so leave Finder alone while it runs. If it fails,
show the tail of its output and stop. `verify` checks that the `.sha256` matches, the DMG
mounts read-only, `codesign --verify --deep --strict` passes on the app inside, and the
app's `CFBundleShortVersionString` equals VERSION. Any FAIL stops the release.

Outputs: `app/build/Plasmie-<VERSION>.dmg` and `app/build/Plasmie-<VERSION>.dmg.sha256`.

## 3. Release notes

The readers install Plasmie on their Macs. They don't read code. Every line answers one
question: what is different for me?

**Gather:** `python3 $R changes` prints commit subjects and first paragraphs since the
previous `v*` tag. With no tag yet, it prints all history plus a hint naming the previous
`chore: release` commit, which you can pass as `--since` for a narrower range. It also
lists changes to the user docs (`docs/`, `README.md`). Read the material, then rewrite
it. Do not paste it.

**Write** to `app/build/Plasmie-<VERSION>-notes.md`, or a temp file in a dry run:

```markdown
## New
- One short line per change, saying what the user can now do.

## Better
- What works better than before, from the user's side.

## Fixed
- What used to go wrong and now doesn't.

## Install
- **Step 1.** Open Plasmie-<VERSION>.dmg and drag **Plasmie** onto **Applications**.
- **Step 2.** Open Plasmie from Applications. When your Mac warns you, click **Done**. (It warns because Plasmie isn't from the App Store.)
- **Step 3.** Open **System Settings › Privacy & Security**, click **Open Anyway** and enter your password.

SHA-256 (Plasmie-<VERSION>.dmg): `<hash from the .sha256 file>`
```

Rules, and why:

- **Groups:** only New, Better, Fixed, in that order. Leave out an empty group. A change
  that only developers notice (tests, lint, refactors, build scripts, docs for
  contributors) goes in no group at all.
- **One short line each,** in plain words: "Ask now answers from your own folders too",
  not "fix(ask): query both qmd collections". Merge commits that add up to one change. On
  a first release, or a range spanning many versions, describe what Plasmie does now.
  Don't replay its history: a bug fixed before anyone installed it isn't news.
- **Leave out:** commit hashes, file and script names, flags, environment variables,
  internal or code names, ADR numbers, and words like API, refactor, migration or
  launchd. These mean nothing to the reader.
- **No people, companies, internal projects, or anything from vault or work data.**
  Commit bodies quote real notes (pets, colleagues, work projects) as examples. None of
  that belongs in public notes. Name a third-party service only when the user has to
  know it to use the feature. Apple Intelligence is the usual case.
- **No marketing voice:** no Unlock, Seamless, Effortless and friends; no "Not just X,
  it's Y"; no rhetorical questions; no em dashes; no exclamation marks; no puns or twists
  in headings. Write flat statements, the way a careful person writes a changelog.
- **The Install section always closes the notes.** It matches the three steps on the
  installer window and in `docs/QUICKSTART.md`. If those steps change, change this
  template with them.

**Lint:**

```bash
python3 $R check-notes <notes file> --sha <hex from the .sha256>   # omit --sha in a dry run
```

This runs the `DENY` list from `tests/repo/test_no_personal.py`, every commit author's name and
email, and the repo owner's login against the text. It also flags slop words, developer
words, file names, hashes, dashes, question marks, unknown headings, empty groups, a
missing or wrong SHA-256, and missing install steps. Fix every hit and re-run until it
says `notes ok`. The lint is a floor, not the bar. Reread the notes as someone who has
never seen the code.

## 4. Show, then stop

Show the user, in the conversation:

1. The notes, in full.
2. The plan: push `main` if it's ahead (say by how many commits), create and push the
   annotated tag `v<VERSION>`, create a **draft** release in `$REPO` titled
   `Plasmie <VERSION>`, and upload these three files (with their sizes):
   `Plasmie-<VERSION>.dmg` and `Plasmie-<VERSION>.dmg.sha256`. The file name always
   carries the version; the website's download buttons link to it by name.
3. That the repo is **private**, so the download works only for people with access to
   the repo (see "Private repo" below).
4. The question: "Push, tag and create the draft release? (yes / no, or edit the notes
   or the tag name)". The tag is `v<VERSION>` unless they ask for another name now.

Then end your turn and wait. Only a clear yes from the user continues: "yes", "go",
"do it". If they edit the notes, re-lint them and show the result again. If they say
anything ambiguous, ask.

## 5. On yes: push, tag, draft

First confirm nothing moved since the build: `git rev-parse HEAD` must equal
`/tmp/plasmie-release-head`, and `git status --porcelain` must be empty. If either
changed, stop. The DMG no longer matches HEAD.

Then, one command at a time, checking each before the next:

```bash
git push origin main                                     # only if ahead of origin
git tag -a v<VERSION> -m "Plasmie <VERSION>"
git push origin v<VERSION>
gh release create v<VERSION> -R "$REPO" --verify-tag --draft \
  --title "Plasmie <VERSION>" --notes-file <notes file> \
  app/build/Plasmie-<VERSION>.dmg app/build/Plasmie-<VERSION>.dmg.sha256
```

`--verify-tag` makes `gh` refuse to invent a tag on GitHub if the push didn't land. (If `$REPO` is ever a separate releases repo, the tag has to
exist there too. Push it to that repo as well, or drop `--verify-tag` and pass
`--target <commit>`, and say which you did.)
Print the draft's URL (`gh release view v<VERSION> -R "$REPO" --json url -q .url`) and ask:
"Publish it now? (yes / leave as draft)". Then stop again.

## 6. On a second yes: publish

```bash
gh release edit v<VERSION> -R "$REPO" --draft=false
```

Print the release URL. Never publish without this second yes. A draft is invisible to
everyone but repo collaborators. A published release notifies watchers.

If the user leaves it as a draft, stop here and leave the website alone. The site names
the latest *released* build, and a draft isn't released.

## 7. Website version (after publishing only)

The website (`~/code/plasmie-site`, its own git repo, served by GitHub Pages) shows the
version in `<span data-plasmie-version>` elements in `index.html`, and in `404.html`
if it has any. They must match the latest published release. Only after step 6
published the release:

```bash
git -C ~/code/plasmie-site status --porcelain            # must be empty; else stop and list it
python3 $R site-version <VERSION>                        # rewrites the spans, prints the diff
python3 $R site-version <VERSION> --check                # must say ok
git -C ~/code/plasmie-site diff
git -C ~/code/plasmie-site commit -am "Website: Plasmie <VERSION>"
```

Show the diff and the commit. Only the version text should change. Then ask: "Push the
website? This puts <VERSION> on the live site. (yes / not now)". Pushing deploys the
live site, so it needs its own, third yes. Neither of the earlier yeses covers it. On yes,
run `git -C ~/code/plasmie-site push`. If there's no remote, or the push fails, say so
and leave the commit in place. On "not now", say the commit is waiting locally and
`git -C ~/code/plasmie-site push` will publish it.

Don't change the download links on the site here. Where they point is the user's open
decision (see "Private repo").

## If something fails partway

Stop at the first failure. Don't retry an external step blindly. Run:

```bash
python3 $R state --tag v<VERSION>
```

It reports what exists now (local tag, tag on GitHub, release and whether it's a draft,
uploaded assets, branch ahead of origin) and prints undo commands, newest first. Tell the
user plainly what was done and what wasn't. For example: "The tag v0.11.0 is on GitHub.
No release was created. To undo: `git push origin :refs/tags/v0.11.0 && git tag -d
v0.11.0`." Don't run the undo commands without a yes either. Undo reference:

| Done | Undo |
|---|---|
| draft or published release | `gh release delete v<VERSION> -R "$REPO" --yes` (keeps the tag) |
| published, want it back to draft | `gh release edit v<VERSION> -R "$REPO" --draft=true` |
| website commit, not pushed | `git -C ~/code/plasmie-site reset --hard HEAD~1` (only that commit; check first) |
| website pushed | commit the previous version back with `release.py site-version <old>`, then push after a yes |
| tag pushed | `git push origin :refs/tags/v<VERSION>` |
| local tag | `git tag -d v<VERSION>` |
| `main` pushed | leave it: those are ordinary commits, and rewriting shared history is worse |

A half-uploaded asset can be replaced with `gh release upload v<VERSION> -R "$REPO" <file> --clobber`.

## Private repo

If `RELEASE_REPO` is private, release pages and downloads work only for people signed in
with access; everyone else gets a 404, including from the website's download buttons.
Check visibility at the confirmation step and say so plainly if it's private.
