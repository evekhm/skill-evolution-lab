#!/usr/bin/env bash
# Cleanup script: close and DELETE all PRs and issues in a GitHub repo.
#
# DESTRUCTIVE AND IRREVERSIBLE: deleted issues and PRs cannot be restored.
#
# Usage:
#   ./scripts/setup/cleanup_github.sh --repo owner/repo          # interactive confirm
#   ./scripts/setup/cleanup_github.sh --repo owner/repo --yes    # non-interactive
#
# The target repository must be named explicitly — there is deliberately no
# default from the current directory. An earlier version defaulted to
# whatever repo the cwd resolved to and destroyed with no confirmation
# (review #54 finding 13); one wrong directory would have erased a real
# repo's issue history.

set -euo pipefail

REPO=""
ASSUME_YES=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo) REPO="${2:-}"; shift 2 ;;
        --yes)  ASSUME_YES=1; shift ;;
        -*)     echo "Unknown flag: $1"; exit 1 ;;
        *)
            echo "ERROR: the target repo must be passed explicitly as --repo owner/repo."
            echo "       (No positional args, no cwd default — this script deletes history.)"
            exit 1
            ;;
    esac
done

if [ -z "$REPO" ]; then
    echo "ERROR: --repo owner/repo is required. There is no default:"
    echo "       this script permanently deletes every issue and PR in the target."
    exit 1
fi
if ! [[ "$REPO" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
    echo "ERROR: '$REPO' does not look like owner/repo."
    exit 1
fi

# Show what is about to be destroyed before asking for consent.
OPEN_PRS=$(gh pr list --repo "$REPO" --state open --limit 500 --json number -q 'length')
CLOSED_PRS=$(gh pr list --repo "$REPO" --state closed --limit 500 --json number -q 'length')
OPEN_ISSUES=$(gh issue list --repo "$REPO" --state open --limit 500 --json number -q 'length')
CLOSED_ISSUES=$(gh issue list --repo "$REPO" --state closed --limit 500 --json number -q 'length')

echo "=== DESTRUCTIVE cleanup of GitHub repo: $REPO ==="
echo "  Will close and PERMANENTLY DELETE:"
echo "    Pull requests: $OPEN_PRS open + $CLOSED_PRS closed"
echo "    Issues:        $OPEN_ISSUES open + $CLOSED_ISSUES closed"
echo "  Deleted issues and PRs CANNOT be restored."
echo ""

if [ -z "$ASSUME_YES" ]; then
    if [ ! -t 0 ]; then
        echo "ERROR: no TTY for confirmation. Re-run with --yes to skip the prompt"
        echo "       (only in automation that has already verified the target)."
        exit 1
    fi
    read -r -p "Type the repository name ($REPO) to confirm deletion: " CONFIRM
    if [ "$CONFIRM" != "$REPO" ]; then
        echo "Confirmation did not match. Nothing was touched."
        exit 1
    fi
fi

echo ""

# --- Close and delete all Pull Requests ---
echo "--- Closing all open PRs ---"
gh pr list --repo "$REPO" --state open --limit 500 --json number -q '.[].number' | while read -r pr; do
  echo "  Closing PR #$pr"
  gh pr close "$pr" --repo "$REPO" --delete-branch 2>/dev/null || true
done

echo "--- Deleting all closed PRs (via GraphQL) ---"
gh pr list --repo "$REPO" --state closed --limit 500 --json number -q '.[].number' | while read -r pr; do
  echo "  Deleting PR #$pr"
  # Get the node ID for GraphQL deletion
  node_id=$(gh pr view "$pr" --repo "$REPO" --json id -q '.id' 2>/dev/null) || continue
  gh api graphql -f query="mutation { deleteIssue(input: {issueId: \"$node_id\"}) { clientMutationId } }" 2>/dev/null || echo "    (could not delete PR #$pr — may need admin rights)"
done

# --- Close and delete all Issues ---
echo ""
echo "--- Closing all open issues ---"
gh issue list --repo "$REPO" --state open --limit 500 --json number -q '.[].number' | while read -r issue; do
  echo "  Closing issue #$issue"
  gh issue close "$issue" --repo "$REPO" 2>/dev/null || true
done

echo "--- Deleting all closed issues (via GraphQL) ---"
gh issue list --repo "$REPO" --state closed --limit 500 --json number -q '.[].number' | while read -r issue; do
  echo "  Deleting issue #$issue"
  node_id=$(gh issue view "$issue" --repo "$REPO" --json id -q '.id' 2>/dev/null) || continue
  gh api graphql -f query="mutation { deleteIssue(input: {issueId: \"$node_id\"}) { clientMutationId } }" 2>/dev/null || echo "    (could not delete issue #$issue — may need admin rights)"
done

echo ""
echo "=== Done ==="
