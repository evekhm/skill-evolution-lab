#!/usr/bin/env bash
# Standard demo profile — ~30-40 min.
# 25 questions (2/category), 3 candidates, 1 round, supervisor target.
# Extra args pass through to run_demo.sh.
exec bash "$(dirname "$0")/run_demo.sh" --quick \
    --questions eval/data/questions/two_defect_quick.json \
    --candidates 3 "$@"
