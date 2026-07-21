#!/usr/bin/env bash
# Full demo profile — ~1-2 h.
# 55 questions + held-out test split; rounds/candidates/targets
# agent-decided. The final numbers come from the disjoint test set.
# Extra args pass through to run_demo.sh.
exec bash "$(dirname "$0")/run_demo.sh" --full "$@"
