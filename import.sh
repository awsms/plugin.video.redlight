#!/usr/bin/env bash
# Merge the latest upstream plugin.video.redlight directory into this fork.
#
# The commit in .upstream-commit is the merge base.  A temporary repository is
# used for the three-way merge so that upstream changes are combined with our
# changes instead of replacing them.  Nothing in the real checkout is changed
# unless that merge completes without conflicts.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UPSTREAM_URL="${UPSTREAM_URL:-https://github.com/The-Red-Wizard/TheRedWizard.git}"
UPSTREAM_BRANCH="${UPSTREAM_BRANCH:-main}"
ADDON="plugin.video.redlight"
STATE_FILE="$ROOT/.upstream-commit"

die() {
	printf 'ERROR: %s\n' "$*" >&2
	exit 1
}

set_output() {
	if [ -n "${GITHUB_OUTPUT:-}" ]; then
		printf '%s=%s\n' "$1" "$2" >> "$GITHUB_OUTPUT"
	fi
}

replace_addon() {
	local source_dir="$1"
	rm -rf "$MERGE_REPO/$ADDON"
	cp -a "$source_dir/$ADDON" "$MERGE_REPO/$ADDON"
	if ! git -C "$MERGE_REPO" add --all 2> "$TEMP_DIR/git-add-errors"; then
		cat "$TEMP_DIR/git-add-errors" >&2
		return 1
	fi
}

command -v git >/dev/null || die "git is required"
command -v tar >/dev/null || die "tar is required"
[ -d "$ROOT/$ADDON" ] || die "$ADDON directory not found"
[ -f "$STATE_FILE" ] || die "$STATE_FILE not found"

cd "$ROOT"
if [ -n "$(git status --porcelain)" ]; then
	die "the working tree must be clean before syncing"
fi

BASE_SHA="$(tr -d '[:space:]' < "$STATE_FILE")"
[[ "$BASE_SHA" =~ ^[0-9a-fA-F]{40}$ ]] \
	|| die "$STATE_FILE must contain one full 40-character commit SHA"

TEMP_DIR="$(mktemp -d)"
if [ "${KEEP_SYNC_TEMP:-0}" = "1" ]; then
	echo "==> Keeping temporary sync data in $TEMP_DIR"
else
	trap 'rm -rf "$TEMP_DIR"' EXIT
fi
UPSTREAM_REPO="$TEMP_DIR/upstream"
BASE_DIR="$TEMP_DIR/base"
LATEST_DIR="$TEMP_DIR/latest"
MERGE_REPO="$TEMP_DIR/merge"
MERGED_DIR="$TEMP_DIR/merged"
mkdir -p "$BASE_DIR" "$LATEST_DIR" "$MERGED_DIR"

echo "==> Fetching $UPSTREAM_URL ($UPSTREAM_BRANCH)"
git clone --quiet --filter=blob:none --no-checkout --single-branch \
	--branch "$UPSTREAM_BRANCH" "$UPSTREAM_URL" "$UPSTREAM_REPO"
LATEST_SHA="$(git -C "$UPSTREAM_REPO" rev-parse "refs/remotes/origin/$UPSTREAM_BRANCH")"

git -C "$UPSTREAM_REPO" cat-file -e "$BASE_SHA^{commit}" 2>/dev/null \
	|| die "tracked upstream commit $BASE_SHA is no longer in upstream history"
git -C "$UPSTREAM_REPO" merge-base --is-ancestor "$BASE_SHA" "$LATEST_SHA" \
	|| die "upstream history was rewritten after $BASE_SHA; refusing an unsafe merge"
git -C "$UPSTREAM_REPO" cat-file -e "$BASE_SHA:$ADDON" 2>/dev/null \
	|| die "$ADDON does not exist at tracked commit $BASE_SHA"
git -C "$UPSTREAM_REPO" cat-file -e "$LATEST_SHA:$ADDON" 2>/dev/null \
	|| die "$ADDON does not exist at latest commit $LATEST_SHA"

if git -C "$UPSTREAM_REPO" diff --quiet "$BASE_SHA" "$LATEST_SHA" -- "$ADDON"; then
	echo "==> No upstream $ADDON changes since $BASE_SHA"
	set_output changed false
	set_output upstream_sha "$LATEST_SHA"
	exit 0
fi

echo "==> Extracting the old and new upstream add-on trees"
git -C "$UPSTREAM_REPO" archive "$BASE_SHA" "$ADDON" | tar -x -C "$BASE_DIR"
git -C "$UPSTREAM_REPO" archive "$LATEST_SHA" "$ADDON" | tar -x -C "$LATEST_DIR"

# Build three normalized commits: the previous upstream tree (merge base), our
# current tree, and the latest upstream tree.  eol=lf matches this repository's
# imported snapshot and prevents line-ending-only conflicts.
git init --quiet --initial-branch=ours "$MERGE_REPO"
git -C "$MERGE_REPO" config user.name "Upstream Sync"
git -C "$MERGE_REPO" config user.email "upstream-sync@localhost"
printf '%s\n' \
	'* text=auto eol=lf' \
	'*.gif binary' \
	'*.jpeg binary' \
	'*.jpg binary' \
	'*.png binary' \
	'*.zip binary' > "$MERGE_REPO/.gitattributes"

replace_addon "$BASE_DIR"
git -C "$MERGE_REPO" commit --quiet -m "Previous upstream tree"
MERGE_BASE="$(git -C "$MERGE_REPO" rev-parse HEAD)"

replace_addon "$ROOT"
git -C "$MERGE_REPO" commit --quiet --allow-empty -m "Our changes"

git -C "$MERGE_REPO" switch --quiet --create theirs "$MERGE_BASE"
replace_addon "$LATEST_DIR"
git -C "$MERGE_REPO" commit --quiet --allow-empty -m "Latest upstream tree"

git -C "$MERGE_REPO" switch --quiet ours
echo "==> Three-way merging upstream into our add-on"
if ! git -C "$MERGE_REPO" merge --quiet --no-edit theirs; then
	conflicts="$(git -C "$MERGE_REPO" diff --name-only --diff-filter=U)"
	printf '\nUpstream sync has real conflicts:\n%s\n' "$conflicts" >&2
	if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
		{
			echo '### Upstream sync needs manual conflict resolution'
			echo
			echo '```text'
			printf '%s\n' "$conflicts"
			echo '```'
		} >> "$GITHUB_STEP_SUMMARY"
	fi
	exit 2
fi

# Materialize the index into an empty directory so Git applies eol=lf even to
# files that were unchanged during the merge.  Then update only the add-on and
# tracking SHA in the real checkout; root-level fork tooling stays untouched.
git -C "$MERGE_REPO" checkout-index --all --prefix="$MERGED_DIR/"
git rm -r --quiet --ignore-unmatch -- "$ADDON"
cp -a "$MERGED_DIR/$ADDON" "$ROOT/$ADDON"
printf '%s\n' "$LATEST_SHA" > "$STATE_FILE"
git add --all -- "$ADDON" "$STATE_FILE"

VERSION="$(sed -n 's/.*<addon .*version="\([^"]*\)".*/\1/p' "$ADDON/addon.xml" | head -n 1)"
echo "==> Merged upstream $ADDON ${VERSION:-unknown} ($LATEST_SHA)"
set_output changed true
set_output upstream_sha "$LATEST_SHA"
set_output version "${VERSION:-unknown}"
