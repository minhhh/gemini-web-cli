# gemini-web-cli: working context

State of the project as of first build. Read this before changing anything.

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

## Layout

```
src/gemini_web_cli/
├── cli.py          typer root, global flags, central error handling
├── client.py       single-browser cookie policy, client factory, error mapping
├── config.py       Settings, state dir, supported browsers
├── errors.py       ToolError with codes and exit codes
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

## Toolchain notes

- Python 3.11, `uv` for env and runs, `ruff` with line length 120, `pytest`
- `typer` 0.27 does not depend on click and vendors its own internals. `except click.exceptions.Exit` crashes, use `typer.Exit`. Options are function calls in defaults, so `B008` is ignored per file
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
