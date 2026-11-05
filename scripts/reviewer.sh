#!/usr/bin/env bash
# Run gh as the GitHub App that reviews this repo, so the review actor is a bot
# and not your account. Installation tokens last one hour and are cached.
#
#   scripts/reviewer.sh --whoami                       # app slug, id, name
#   scripts/reviewer.sh --token                        # print an installation token
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
for bin in gh curl openssl jq; do
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

# gh sends "Authorization: token <jwt>", which GitHub rejects for App JWTs.
# App-scoped calls must carry "Bearer", so they go through curl.
app_api() {
	local jwt=$1 method=$2 path=$3 body
	body=$(curl -sS --fail-with-body -X "$method" \
		-H "Authorization: Bearer $jwt" \
		-H "Accept: application/vnd.github+json" \
		"https://api.github.com$path") || die "request failed: $method $path: $body"
	printf '%s' "$body"
}

mode=gh
repo=""
while [ $# -ge 1 ]; do
	case "$1" in
	--whoami)
		mode=whoami
		shift
		;;
	--token)
		mode=token
		shift
		;;
	--repo)
		[ $# -ge 2 ] || die "--repo needs owner/name"
		repo=$2
		shift 2
		;;
	*) break ;;
	esac
done

if [ "$mode" = whoami ]; then
	app_api "$(app_jwt)" GET /app | jq '{slug, id, name}'
	exit 0
fi

if [ -z "$repo" ]; then
	repo=$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null) ||
		die "not in a repo, pass --repo owner/name"
fi
[ "$mode" = token ] || [ $# -ge 1 ] || die "usage: reviewer.sh [--repo owner/name] [--token] <gh args...>"

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
	installation=$(app_api "$jwt" GET "/repos/$repo/installation" | jq -r .id) ||
		die "no App installation found for $repo (is the App installed on it?)"
	response=$(app_api "$jwt" POST "/app/installations/$installation/access_tokens")
	token=$(printf '%s' "$response" | jq -r .token)
	# expires_at is one hour out; drop five minutes so a slow call cannot land past it.
	printf '%s' "$response" | jq -c '{token, expires: ((.expires_at | fromdate) - 300)}' >"$cache"
	chmod 600 "$cache"
fi

if [ "$mode" = token ]; then
	printf '%s\n' "$token"
	exit 0
fi

GH_TOKEN="$token" exec gh "$@"
