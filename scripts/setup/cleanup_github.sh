#!/usr/bin/env bash
# Cleanup script: close and delete all PRs and issues in a GitHub repo.
# Usage: ./scripts/setup/cleanup_github.sh [owner/repo]
# Defaults to the repo detected by `gh repo view` in the current directory.

set -euo pipefail

REPO="${1:-$(gh repo view --json nameWithOwner -q '.nameWithOwner')}"

echo "=== Cleaning up GitHub repo: $REPO ==="
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
