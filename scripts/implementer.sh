#!/usr/bin/env bash
# Act as the implementer: your GitHub account, your repository, a distinct commit name.
#
#   scripts/implementer.sh whoami
#   scripts/implementer.sh gh pr create --fill
#   scripts/implementer.sh commit "fix: return exit 1 when the thread is missing"
#   scripts/implementer.sh git push -u origin HEAD
#
# The author name is set per command, never in git config, so a stray commit
# elsewhere stays yours. The PAT is used for both gh and git, which means
# revoking it stops the agent without touching the keyring token gh uses.
set -euo pipefail

NAME="${IMPL_NAME:-minhhh-agent-implementer}"
EMAIL="${IMPL_EMAIL:-4078393+minhhh@users.noreply.github.com}"
token_file="${IMPL_TOKEN_FILE:-${XDG_CONFIG_HOME:-$HOME/.config}/gh-secret/agent-implementer}"
trailer="${IMPL_TRAILER:-Assisted-by: agent-implementer}"

die() { printf 'implementer: %s\n' "$*" >&2; exit 2; }

read_token() {
	[ -r "$token_file" ] || die "no PAT at $token_file"
	tr -d '[:space:]' <"$token_file"
}

# git needs a usable password; the default helpers answer with the keyring token,
# so they are cleared and replaced with one that returns this PAT.
git_as_implementer() {
	GH_TOKEN="$(read_token)" \
		GIT_AUTHOR_NAME="$NAME" GIT_AUTHOR_EMAIL="$EMAIL" \
		GIT_COMMITTER_NAME="$NAME" GIT_COMMITTER_EMAIL="$EMAIL" \
		exec git \
		-c credential.helper= \
		-c 'credential.helper=!f() { echo username=minhhh; echo "password=$GH_TOKEN"; }; f' \
		"$@"
}

sub="${1:-}"
[ $# -ge 1 ] && shift

case "$sub" in
whoami)
	printf 'name:  %s\nemail: %s\n' "$NAME" "$EMAIL"
	GH_TOKEN="$(read_token)" exec gh api user --jq '"gh:    " + .login'
	;;
gh)
	[ $# -ge 1 ] || die "usage: implementer.sh gh <gh args...>"
	GH_TOKEN="$(read_token)" exec gh "$@"
	;;
git)
	[ $# -ge 1 ] || die "usage: implementer.sh git <git args...>"
	git_as_implementer "$@"
	;;
commit)
	[ $# -ge 1 ] || die 'usage: implementer.sh commit "<message>" [git commit args...]'
	message=$1
	shift
	git_as_implementer commit -m "$message" -m "$trailer" "$@"
	;;
*)
	die 'usage: implementer.sh {whoami|gh|git|commit} ...
  whoami   print the identity and the account the PAT belongs to
  gh       run gh as the implementer
  git      run git with the implementer identity and PAT
  commit   commit staged changes with a message and the assisted-by trailer'
	;;
esac
