# gemini-web-cli

Manage Gemini conversations from the command line.

There is no official API for consumer Gemini conversations, and Google Takeout exports are manual and unthreaded. This tool drives the same internal endpoints the web UI uses, authenticated with your browser cookies. Scope is conversation history only.

## Install

```sh
uv sync --extra dev
uv run gemini-web-cli doctor
```

## Global flags

These are root options, so they must come **before** the subcommand. Click parses them at the root only, so the wrong placement is a usage error (exit `2`), not a warning:

```sh
$ gemini-web-cli chats list --pretty
Usage: gemini-web-cli chats list [OPTIONS]
Try 'gemini-web-cli chats list -h' for help.

Error: No such option: --pretty
# exit 2, all of it on stderr; stdout is empty

$ gemini-web-cli --pretty chats list
{
  "ok": true,
  ...
}
# indented envelope, abbreviated
```

| Flag | Default | Meaning |
|---|---|---|
| `--browser` | `edge` | Browser whose cookie store is read. One of `edge`, `chrome`, `brave`, `firefox`; any other value fails at runtime with `bad_browser` and exit `1`, not a usage error. |
| `--home` | `~/.local/state/gemini-web-cli`, or `$GEMINI_WEB_CLI_HOME` when set | State directory holding the cookie cache. |
| `--timeout` | `90` | Seconds to wait for the Gemini handshake. Minimum `5`. |
| `--pretty` | off | Indent the JSON output. Compact by default, because tokens. |
| `--debug` | off | Verbose library logs on stderr, and a traceback attached to unexpected errors. |
| `--version` | — | Print the version and exit. |
| `-h`, `--help` | — | Help at the root, at `chats`, and on every subcommand. |

## Commands

| Command | What it does |
|---|---|
| `doctor` | Check cookies, state directory and authentication. |
| `chats list` | List recent conversations, newest first. |
| `chats read` | Read one conversation's turns. |
| `chats search` | Case-insensitive substring match on titles. |
| `chats delete` | Delete one conversation server-side. |

| Command | Flag | Default | Meaning |
|---|---|---|---|
| `doctor` | `--offline` | off | Skip the authenticated network call. |
| `chats list` | `-n`, `--limit` | `50` | Conversations to return. Range `1`–`200`. |
| `chats read` | `--turns` | `200` | Turns to fetch. Range `1`–`2000`. |
| `chats read` | `--oldest-first` | off | Reverse the default newest-first order. |
| `chats search` | `-n`, `--limit` | `50` | Matches to return. Range `1`–`200`. |
| `chats delete` | `-y`, `--yes` | off | Confirm the deletion. Required: without it the command refuses and deletes nothing. |

```sh
gemini-web-cli doctor
gemini-web-cli doctor --offline
gemini-web-cli chats list
gemini-web-cli chats list -n 5
gemini-web-cli --pretty chats list -n 5
gemini-web-cli chats read c_0123456789abcdef
gemini-web-cli chats read c_0123456789abcdef --oldest-first
gemini-web-cli chats search kafka
gemini-web-cli chats delete c_0123456789abcdef --yes
```

`chats search` reads titles, not bodies. It cannot find a thread by something said inside it, so a phrase you remember from a conversation returns nothing even though the conversation exists. Full-text search needs the local archive in the roadmap.

## Output contract

One JSON document on stdout for any run that reaches a command, success and failure alike. Usage errors are the exception: click writes the `Usage:` / `Error:` text to stderr, stdout stays empty, and the exit code is `2`. `--help` and `--version` also bypass the envelope, printing plain text on stdout with exit `0`. A script piping stdout into `jq` has to handle exit `2` producing no JSON at all.

```json
{"ok": true, "command": "chats.list", "data": {"chats": [{"cid": "c_...", "title": "...", "pinned": false, "updated_at": "2026-02-10T00:15:18Z"}]}, "meta": {"count": 1}}
```

```json
{"ok": false, "command": "chats.read", "error": {"code": "auth_failed", "message": "...", "hint": "..."}}
```

Inside the envelope, errors are on stdout so a caller reads a single stream and branches on `ok`. Exit codes: `0` ok, `1` operation failed, `2` usage error, `3` authentication failed. Error codes: `api_error`, `auth_failed`, `bad_browser`, `confirmation_required`, `delete_failed`, `gemini_error`, `missing_dependency`, `no_context`, `not_found`, `rate_limited`, `timeout`, `unexpected`, `usage_limit`.

## Cookies

Only one browser is read, chosen by `--browser`. Cookies are read at runtime from that browser's own store, so nothing is copied into the repo.

The underlying library would instead scan every installed browser and merge the jars, which silently mixes Google accounts. A wrong or guest account answers every call successfully with an empty list, so the failure looks like "no history" rather than an error. Observed directly: one browser held the account with 20 conversations while another held a different account with 0. This tool pins the source, skips the scan, and refuses to run when the session did not come from the supplied cookies. Do not add a fallback to auto-detection; that path is the bug this tool exists to prevent.

`1PSIDTS` rotates. A stale cookie cache is the usual cause of "Are you signed in?" errors, and `doctor` reports it.

## Caveats

- Deleting is server-side and immediate. There is no undo, and `--yes` is the only guard.
- Every command except `chats delete` is read-only and changes no server state.
- Scraping is against Google's terms of service. Use it on your own account.
- `--debug` output and cookie-cache warnings embed `__Secure-1PSID` in file paths. Do not paste them into a public issue or transcript. State directories are created `0700` for the same reason.

## Roadmap

1. Local archive with incremental sync, so reads and search stop hitting the network
2. Full-text search across conversation bodies, backed by that archive
3. `chats export` to markdown or JSON, per conversation and in bulk
4. Pagination past the first list page, once its shape is known
