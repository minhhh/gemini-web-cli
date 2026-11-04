#!/usr/bin/env bash
# Give each agent task its own checkout so it never moves your branch.
#
#   scripts/worktree.sh new fix-timeout      # branch impl/fix-timeout from origin/main
#   scripts/worktree.sh list
#   scripts/worktree.sh rm fix-timeout
#   scripts/worktree.sh prune
#
# Worktrees live beside the repo, not inside it:
#   <parent>/.worktrees/<repo>/<slug>
# so nothing here needs a .gitignore entry. Secrets stay in $HOME, and the
# helper scripts are tracked files, so they are present in every worktree.
set -euo pipefail

die() { printf 'worktree: %s\n' "$*" >&2; exit 2; }

root=$(git rev-parse --show-toplevel 2>/dev/null) || die "not inside a git repository"
name=$(basename "$root")
base="${WORKTREE_BASE:-$(dirname "$root")/.worktrees/$name}"
prefix="${WORKTREE_PREFIX:-impl/}"

usage() {
	cat >&2 <<'EOF'
usage: worktree.sh <command> [args]

  new <slug> [--base <ref>]   create <parent>/.worktrees/<repo>/<slug>
                              on branch impl/<slug>, default base origin/main
  list                        git worktree list
  rm <slug> [--force]         remove the worktree, then delete its branch
  prune                       drop records for worktrees deleted by hand
EOF
	exit 2
}

sub="${1:-}"
[ $# -ge 1 ] && shift

case "$sub" in
new)
	[ $# -ge 1 ] || usage
	slug=$1
	shift
	from="origin/main"
	while [ $# -ge 1 ]; do
		case "$1" in
		--base)
			[ $# -ge 2 ] || die "--base needs a ref"
			from=$2
			shift 2
			;;
		*) die "unknown option: $1" ;;
		esac
	done
	path="$base/$slug"
	[ -e "$path" ] && die "already exists: $path"
	mkdir -p "$base"
	git fetch origin --quiet
	git worktree add -b "$prefix$slug" "$path" "$from" >&2
	printf '%s\n' "$path"
	;;
list)
	git worktree list
	;;
rm)
	[ $# -ge 1 ] || usage
	slug=$1
	shift
	path="$base/$slug"
	[ -d "$path" ] || die "no worktree at $path"
	force=""
	[ "${1:-}" = "--force" ] && force="--force"
	git worktree remove $force "$path"
	git branch -d "$prefix$slug" 2>/dev/null || git branch -D "$prefix$slug"
	;;
prune)
	git worktree prune --verbose
	;;
*)
	usage
	;;
esac
