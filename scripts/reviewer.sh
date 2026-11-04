#!/usr/bin/env bash
# Run gh as the GitHub App that reviews this repo, so the review actor is a bot
# and not your account. Installation tokens last one hour and are cached.
#
#   scripts/reviewer.sh --whoami
#   scripts/reviewer.sh pr review 42 --comment -b "notes"
#   scripts/reviewer.sh --repo minhhh/other-repo pr list
#
# Reads App ID and private key from ~/.config/gh-secret/ (mode 0700):
#   reviewer-app-id     one line, the numeric App ID
#   reviewer-app.pem    private key generated on the App settings page
# Override with GH_REVIEWER_APP_ID and GH_REVIEWER_APP_KEY.
set -euo pipefail

state_dir="${XDG_CONFIG_HOME:-$HOME/.config}/gh-secret"
key="${GH_REVIEWER_APP_KEY:-$state_dir/reviewer-app.pem}"
id_file="$state_dir/reviewer-app-id"

die() { printf 'reviewer: %s\n' "$*" >&2; exit 2; }

[ -r "$key" ] || die "no app private key at $key"
for bin in gh openssl jq; do
	command -v "$bin" >/dev/null || die "missing dependency: $bin"
done

app_id="${GH_REVIEWER_APP_ID:-}"
if [ -z "$app_id" ] && [ -r "$id_file" ]; then
	app_id=$(tr -dc '0-9' <"$id_file")
fi
[ -n "$app_id" ] || die "no App ID: write it to $id_file or set GH_REVIEWER_APP_ID"

b64url() { openssl base64 -A | tr '+/' '-_' | tr -d '='; }

# App JWT: iss is the App ID, exp must be within 10 minutes, iat backdated for skew.
app_jwt() {
	local now header payload
	now=$(date +%s)
	header=$(printf '%s' '{"alg":"RS256","typ":"JWT"}' | b64url)
	payload=$(printf '{"iat":%d,"exp":%d,"iss":"%s"}' $((now - 60)) $((now + 540)) "$app_id" | b64url)
	printf '%s.%s.%s' "$header" "$payload" \
		"$(printf '%s.%s' "$header" "$payload" | openssl dgst -sha256 -sign "$key" | b64url)"
}

if [ "${1:-}" = "--whoami" ]; then
	GH_TOKEN="$(app_jwt)" exec gh api app --jq '{slug, id, name}'
fi

repo=""
if [ "${1:-}" = "--repo" ]; then
	[ $# -ge 2 ] || die "--repo needs owner/name"
	repo=$2
	shift 2
fi
[ $# -ge 1 ] || die "usage: reviewer.sh [--repo owner/name] <gh args...>"
if [ -z "$repo" ]; then
	repo=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
fi

cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/gemini-web-cli"
mkdir -p "$cache_dir"
chmod 700 "$cache_dir"
cache="$cache_dir/gh-app-$(printf '%s' "$repo" | tr '/' '-').json"

token=""
if [ -r "$cache" ]; then
	token=$(jq -r --argjson now "$(date +%s)" 'select(.expires > $now) | .token' "$cache" 2>/dev/null || true)
fi

if [ -z "$token" ]; then
	jwt=$(app_jwt)
	installation=$(GH_TOKEN="$jwt" gh api "repos/$repo/installation" --jq .id) ||
		die "no App installation found for $repo (is the App installed on it?)"
	response=$(GH_TOKEN="$jwt" gh api -X POST "app/installations/$installation/access_tokens") ||
		die "token exchange failed for installation $installation"
	token=$(printf '%s' "$response" | jq -r .token)
	# expires_at is one hour out; drop five minutes so a slow call cannot land past it.
	printf '%s' "$response" | jq -c '{token, expires: ((.expires_at | fromdate) - 300)}' >"$cache"
	chmod 600 "$cache"
fi

GH_TOKEN="$token" exec gh "$@"
