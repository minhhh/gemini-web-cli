# gemini-web-cli: working context

State of the project as of first build. Read this before changing anything.

Implementing a change means working in a worktree, not in this checkout. See [Agent workflow](#agent-workflow) before the first edit.

## What this is

A Python CLI that manages Gemini conversations from the terminal, built on the `gemini-webapi` package. The command is `gemini-web-cli`, the package is `gemini_web_cli`, the folder is `local_tools/gemini-web-cli`.

Scope is deliberately narrow: list, read, search and delete conversations. Prompts, image generation, Gems and Deep Research were removed on purpose. Do not add them back without asking.

Why it exists: there is no official API for consumer Gemini conversations. Exports through Google Takeout are manual and unthreaded. The only way to work with real threads is the same internal endpoint the web UI calls, which needs browser cookies.

## What works today

| Command | State | Notes |
|---|---|---|
| `doctor` | done | cookie inventory, state dir writability, authenticated probe |
| `chats list` | done | returns one page, currently 20 conversations |
| `chats read` | done | full turns, newest first, `--oldest-first` to reverse |
| `chats search` | partial | titles only, full text needs the archive |
| `chats delete` | done | requires `--yes`, verifies by re-reading |

Verified against a real account: 20 conversations listed, a 16-turn thread read intact, a throwaway conversation created and deleted, then confirmed gone.

## How the authentication actually works

Three layers, all needed:

1. Cookies for `.google.com`: `__Secure-1PSID` and `__Secure-1PSIDTS`, plus the identity cookies that decide which Google account the session belongs to
2. A `GET https://gemini.google.com/app` carrying those cookies, from which the client scrapes `SNlM0e` (access token), `cfb2h` (build label), `FdrFJe` (session id), `TuX5cc` (language), `qKIAYe` (push id)
3. POSTs to `https://gemini.google.com/_/BardChatUi/data/batchexecute` with `rpcids`. Listing is `MaZiqc`, reading and deleting use the conversation id `c_...`

No OAuth, no API key. `1PSIDTS` rotates, so a stale cookie cache shows up as "Are you signed in?" rather than an HTTP 401.

## The trap this project exists to avoid

`gemini_webapi` reads every installed browser's cookie store on init, merges the jars, and caches the result. Two browsers on one machine are usually logged into different Google accounts. A wrong or guest account answers every RPC successfully with an empty list, so the failure looks like "no history", not like an error.

Observed directly: Edge held the account with 20 conversations, Firefox held a different account with 0.

Guards in `client.py`:

- Only the browser given by `--browser` is read. The library's scan is replaced in `sys.modules["gemini_webapi.utils.get_access_token"].load_browser_cookies`
- Cookies are passed explicitly, so `cookie_source` must start with `Base Cookies` or the run aborts
- `GEMINI_COOKIE_PATH` points at the tool's own state dir, never the shared temp cache

Note the patching gotcha: `import gemini_webapi.utils.get_access_token as gat` returns the *function* re-exported by the package, not the module. Patch through `sys.modules` or the assignment silently does nothing.

## JSON contract

One document on stdout per run, success and failure alike. Logs go to stderr.

```json
{"ok": true, "command": "chats.list", "data": {"chats": []}, "meta": {"count": 0}}
{"ok": false, "command": "chats.read", "error": {"code": "not_found", "message": "...", "hint": "..."}}
```

Errors are on stdout so an agent reads a single stream and branches on `ok`. Exit codes: `0` ok, `1` failed, `2` usage, `3` auth. Stable error codes include `auth_failed`, `not_found`, `confirmation_required`, `rate_limited`, `timeout`, `delete_failed`, `unexpected`.

`--pretty` indents. Default is compact, because tokens.

The `command` field is a fixed id (`chats.list`), never a copy of `sys.argv`: argv also holds global option values, so reading it produced ids like `/tmp/gw-x.nope`. Success and failure envelopes both take it from `invocation.name()`, recorded from the click context chain by `invocation.record()`, which the root callback and `settings_of()` call. A command must take its settings through `settings_of()` or its failures fall back to the parent group's name, and `test_every_command_refuses_an_unsupported_browser` fails when one does not. Global checks that fail must be raised from where settings are consumed, for the same reason.

## Layout

```
src/gemini_web_cli/
├── cli.py          typer root, global flags, central error handling
├── client.py       single-browser cookie policy, client factory, error mapping
├── config.py       Settings, state dir, supported browsers
├── errors.py       ToolError with codes and exit codes
├── invocation.py   command path used by error envelopes
├── output.py       JSON envelope
├── serialize.py    Gemini objects to plain JSON
└── commands/
    ├── chats.py    list, read, search, delete
    └── doctor.py   self checks
```

## Working on it

```sh
cd local_tools/gemini-web-cli
uv sync --extra dev
uv run gemini-web-cli doctor
uv run gemini-web-cli chats list --limit 5
uv run pytest
uv run ruff check .
```

Use `--home /tmp/gweb-state` when experimenting so the real state dir stays clean. `--debug` sends library logs to stderr and adds a traceback to unexpected errors.

Defaults: `--browser edge`, state at `~/.local/state/gemini-web-cli`, 90s handshake timeout.

## Agent workflow

**Rule: implementing a change happens in a fresh worktree. Do not edit files in the main checkout.** Two reasons. Branch churn stays out of the checkout the user is working in, and an uncommitted change in that checkout is no longer something you have to work around.

The worktree decides where the edits land. The credential decides which GitHub actor does the pushing, and those are separate choices.

When asked to implement a feature or a fix:

1. Pick a kebab-case slug that says what the change is, not what number the issue has: `timeout-exit-code`, not `issue-42`
2. Create the worktree and move into it. This prints the path and nothing else, so capture it

   ```sh
   wt=$(scripts/worktree.sh new timeout-exit-code)   # branch impl/timeout-exit-code from origin/main
   cd "$wt"
   uv sync --extra dev                              # .venv is per checkout, not shared
   ```

3. Implement there, in that directory, for the whole task. If the task grows a second independent change, make a second worktree rather than mixing it into the same branch
4. Commit and push as the implementer identity. Never plain `git commit` with the ambient git config

   ```sh
   scripts/implementer.sh commit "fix: return exit 1 when the thread is missing"
   scripts/implementer.sh git push -u origin HEAD
   scripts/implementer.sh gh pr create --fill
   ```

5. Review is the other role and the other credential: `scripts/reviewer.sh pr review <n> --comment -b "..."` from the main checkout. The bot's approval is what satisfies the required approval, since you cannot approve your own PR
6. Report back the worktree path, the branch, and the PR URL. Those three are what the user needs to look at the work
7. After the PR merges, remove the worktree from the main checkout: `scripts/worktree.sh rm timeout-exit-code`

Do not use a worktree for reading. Answering a question, grepping the code, or reviewing a PR needs no checkout and no branch, and creates clutter to clean up.

The rules that permissions do not enforce, so they are discipline:

- Never commit as the implementer in the main checkout, and never push `main` from a worktree. The ruleset's admin bypass applies to your PAT, so it will not stop you
- Never let the reviewer role commit. It has no author identity for a reason
- Both wrappers read secrets from `$HOME`, so they behave the same in every worktree. Do not copy a key or a PAT into a repo, and do not add them to a worktree

Mechanics worth knowing:

- Worktrees live at `<parent>/.worktrees/<repo>/<slug>`, outside the repo, so no ignore entry is needed
- One worktree per task, one branch per worktree, removed after merge. `scripts/worktree.sh prune` clears stale records left by a manual `rm -rf`
- `scripts/worktree.sh list` shows what is checked out where, which is the first thing to run when a branch in `git branch` is checked out but not visible in the main checkout
- The commit author name is free text. github.com renders the account that owns the author email instead, so `minhhh-agent-implementer <4078393+minhhh@users.noreply.github.com>` reads `minhhh` on the web and the agent name in `git log --format='%an'`. Expected, not a misconfiguration. A `[bot]` badge needs the App's bot-owner email, which would move the commits off your account

## Toolchain notes

- Python 3.11, `uv` for env and runs, `ruff` with line length 120, `pytest`
- `typer` 0.27 does not depend on click and vendors its own internals. `except click.exceptions.Exit` crashes, use `typer.Exit`. Options are function calls in defaults, so `B008` is ignored per file
- Help and usage errors render through click's plain formatter, not rich: every `typer.Typer(...)` carries `rich_markup_mode=None`, which is what removes the rounded box panels. There is no global switch and sub-apps do not inherit, so a new sub-Typer needs the flag or its help comes back boxed. Each `typer.Typer(...)` also sets `context_settings={"help_option_names": ["-h", "--help"]}` so `-h` works at every level; a new sub-Typer needs that too
- Ruff rules `B008` and `ARG001` are suppressed for Typer command modules only

## Next steps, in order

1. Local archive. Sync conversations to disk with incremental updates, so reads and search stop hitting the network
2. Full-text search over the archive. Today `chats search` sees titles only, which is the weakest part of the tool
3. `chats export` to markdown or JSON, one conversation or many
4. Pagination past the first list page. The list RPC payload takes a count, the shape of the continuation is unknown

## Guardrails

- Deletion is server-side and permanent. Never add a path that deletes without `--yes`
- Read-only is the default posture. Any action that changes server state needs an explicit flag
- Scraping violates Google's terms of service. Keep it to the user's own account
- Do not let the tool fall back to auto-detect cookies. That path is the bug this project was built to prevent
- Cookie cache file names embed `__Secure-1PSID`, and library debug logs print those paths. Never paste `--debug` output or a cookie-cache warning into a public issue or transcript. State dirs are created `0700` for the same reason
