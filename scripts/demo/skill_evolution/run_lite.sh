#!/usr/bin/env bash
# Lite demo profile — ~17 min measured.
# 13 questions (1/category), 2 candidates, 1 round, supervisor target.
# Extra args pass through to run_demo.sh.
exec bash "$(dirname "$0")/run_demo.sh" --quick "$@"
