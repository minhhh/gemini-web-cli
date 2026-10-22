# gemini-web-cli

Manage Gemini conversations from the command line, built on `gemini-webapi`. Every command prints one JSON document on stdout. Logs go to stderr. Non-zero exit code on failure.

Scope: conversations only. List them, read them, search them, delete them. It does not send prompts, generate images, or run Deep Research.

There is no official API for consumer Gemini conversations. This tool drives the same internal endpoints the web UI uses, authenticated with browser cookies.

## Status

Working: `chats list`, `chats read`, `chats search`, `chats delete`, `doctor`.

## Install

```sh
uv sync --extra dev
uv run gemini-web-cli doctor
```

## Output contract

Success, one line unless `--pretty`:

```json
{"ok": true, "command": "chats.list", "data": {"chats": [{"cid": "c_...", "title": "...", "pinned": false, "updated_at": "2026-02-10T00:15:18Z"}]}, "meta": {"count": 20}}
```

Failure, still on stdout, exit code non-zero:

```json
{"ok": false, "command": "chats.read", "error": {"code": "auth_failed", "message": "...", "hint": "..."}}
```

Exit codes: `0` ok, `1` operation failed, `2` usage error, `3` authentication failed.

## Cookie source

Only one browser is read, chosen by `--browser` (default `edge`). The library by default scans every installed browser and merges the jars, which silently mixes Google accounts: a secondary account answers every call successfully with an empty list. This tool pins the source, skips the scan, and refuses to run when the session did not come from the supplied cookies.

Cookies are read at runtime from the browser's own store. Nothing is copied into the repo.

## Commands

```sh
gemini-web-cli doctor                       # cookie, auth and connectivity checks
gemini-web-cli chats list --limit 20
gemini-web-cli chats read c_0123456789abcdef
gemini-web-cli chats search kafka           # titles today, see roadmap
gemini-web-cli chats delete c_... --yes     # destructive, --yes required
```

Global flags: `--browser`, `--home`, `--timeout`, `--pretty`, `--debug`, `--version`.

## Roadmap

1. Local archive with incremental sync, so reads and search do not hit the network
2. Full-text search across conversation bodies, backed by that archive
3. `chats export` to markdown or JSON, per conversation and in bulk
4. Pagination past the first list page, once its shape is known

## Notes

- `1PSIDTS` rotates. A stale cookie cache is the usual cause of "Are you signed in?" errors
- Deleting is server-side and immediate. There is no undo
- Scraping is against Google's terms of service. Use it on your own account, read-only by default
