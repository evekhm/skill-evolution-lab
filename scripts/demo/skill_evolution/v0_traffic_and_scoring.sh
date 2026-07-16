#!/usr/bin/env bash
# V0 Traffic Generation + Scoring
#
# Restores V0 skills for ALL agents, generates multi-turn traffic
# with the specified persona, scores it, and prints quality summary.
#
# Usage:
#   bash scripts/demo/skill_evolution/v0_traffic_and_scoring.sh
#   bash scripts/demo/skill_evolution/v0_traffic_and_scoring.sh --persona alex
#   bash scripts/demo/skill_evolution/v0_traffic_and_scoring.sh --persona morgan
#   bash scripts/demo/skill_evolution/v0_traffic_and_scoring.sh --persona alex --quick

exec bash scripts/demo/skill_evolution/run_demo.sh --v0-only "$@"
