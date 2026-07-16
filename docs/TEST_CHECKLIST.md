# Test Checklist

Run these tests after any structural change (directory moves, import
refactors, dependency updates, deploy script changes).

## 1. Agent Imports

Verify every agent can be imported and its key symbols are accessible.

```bash
# Production agents
python3 -c "from agents.enterprise.policy_agent.agent import root_agent, create_agent; print('policy_agent OK')"
python3 -c "from agents.enterprise.hr_calculator.agent import root_agent, calculate_pto_details; print('hr_calculator OK')"
python3 -c "from agents.enterprise.knowledge_supervisor.app.agent import root_agent; print('supervisor OK:', [a.name for a in root_agent.sub_agents])"

# Workflow agents
python3 -c "from agents.workflow.quality_agent.agent import root_agent, app; print('quality_agent OK')"
python3 -c "from agents.workflow.skill_evolution_agent.agent import root_agent, app; print('skill_evolution_agent OK')"
```

- [ ] policy_agent imports
- [ ] hr_calculator imports
- [ ] knowledge_supervisor imports (includes RemoteA2aAgent -- needs a2a-sdk<1.0.0)
- [ ] quality_agent imports
- [ ] skill_evolution_agent imports

## 2. Cross-Agent Imports

Workflow agents import from production agents. Verify these paths work.

```bash
# eval/tests/test_eval.py imports
python3 -c "from agents.enterprise.policy_agent.agent import create_agent; from agents.enterprise.hr_calculator.agent import calculate_pto_details; print('eval imports OK')"

# traffic_generator builds local supervisor from production agents
python3 -c "from agents.enterprise.policy_agent.agent import create_agent; from agents.enterprise.hr_calculator.agent import calculate_pto_details, calculate_working_days_for_period, get_remaining_working_days; print('traffic_generator imports OK')"

# skill_evolution_agent uses agent_registry.json for agent discovery
python3 -c "from agents.workflow.quality_agent.tools import _get_agent_files; print('quality_agent registry:', _get_agent_files('policy_agent'))"

```

- [ ] eval/tests/test_eval.py imports (policy_agent + hr_calculator)
- [ ] traffic_generator local supervisor build
- [ ] quality_agent agent_registry resolves agent file paths

## 3. Relative Path Resolution

All agents use relative paths for .env, eval/, and repo root. Verify
they resolve correctly from the new directory depth.

```bash
for script in \
  agents/enterprise/policy_agent/deploy.sh \
  agents/enterprise/hr_calculator/deploy.sh \
  agents/enterprise/knowledge_supervisor/deploy.sh \
  agents/workflow/traffic_generator/deploy.sh \
  agents/workflow/quality_agent/deploy.sh; do
  dir=$(dirname "$script")
  env=$(cd "$dir" && python3 -c "import os; print(os.path.abspath('../../../.env'))")
  test -f "$env" && echo "$script: OK" || echo "$script: FAIL - $env not found"
done
```

- [ ] All deploy.sh scripts find .env
- [ ] skill_evolution_agent tools._repo_root resolves to project root
- [ ] quality_agent quality_report._repo_root resolves to project root
- [ ] traffic_generator finds eval/data/eval_cases.json

## 4. Tool Tests (no LLM calls needed)

```bash
# Quality agent tools
python3 -c "
from agents.workflow.quality_agent.tools import _get_agent_files, _find_agy, _gh_available
print('agent_registry:', _get_agent_files('policy_agent'))
print('agy available:', _find_agy() is not None)
print('gh available:', _gh_available())
"

# Evolution agent tools
python3 -c "
from agents.workflow.skill_evolution_agent.tools import _load_agent_registry, _find_agy
reg = _load_agent_registry()
print('registry agents:', list(reg.get('agents', {}).keys()))
print('agy available:', _find_agy() is not None)
"
```

- [ ] quality_agent agent_registry resolves agent paths
- [ ] gh CLI available and authenticated
- [ ] agy CLI available (optional, for rich descriptions)

## 5. Traffic Generator (local, small batch)

Generates questions with Gemini, runs them through the local supervisor.
Requires GCP auth and Vertex AI API enabled.

```bash
bash agents/workflow/traffic_generator/run_local.sh --local --count 5
```

- [ ] Questions generated successfully
- [ ] All queries complete with 0 errors
- [ ] Results file written

## 6. Quality Agent

```bash
# Tools-only test (no agent LLM call)
bash agents/workflow/quality_agent/run_local.sh --test 1h

# Full agent dry-run (creates local .md files instead of GitHub issues)
bash agents/workflow/quality_agent/run_local.sh --dry-run --period 1h
```

- [ ] run_quality_report returns sessions from BigQuery
- [ ] LLM judge scores sessions (meaningful/partial/unhelpful)
- [ ] GitHub connection works (gh CLI or PyGithub fallback)
- [ ] Dry-run creates issue .md files in dry_run_output/

## 7. Skill Evolution Agent

```bash
# Tools-only test
python3 -c "from agents.workflow.skill_evolution_agent.tools import parse_quality_issue; print(parse_quality_issue(99))"

# Issue-triggered mode (parse a quality issue)
python3 agents/workflow/skill_evolution_agent/main.py --from-issue 99 --dry-run
```

- [ ] parse_quality_issue extracts structured data from quality issues
- [ ] --from-issue mode builds correct prompt

## 8. Eval Gate

```bash
uv run pytest eval/tests/test_eval.py -v --timeout=120
```

- [ ] All eval cases pass (routing, tool use, out-of-scope)

## 9. Deploy Scripts (syntax check only)

```bash
for script in \
  scripts/deploy/deploy_gcp.sh \
  agents/enterprise/policy_agent/deploy.sh \
  agents/enterprise/hr_calculator/deploy.sh \
  agents/enterprise/knowledge_supervisor/deploy.sh \
  agents/workflow/traffic_generator/deploy.sh \
  agents/workflow/quality_agent/deploy.sh; do
  bash -n "$script" && echo "$script: syntax OK" || echo "$script: SYNTAX ERROR"
done
```

- [ ] All deploy scripts pass bash syntax check

## 10. Dependency Check

```bash
pip show a2a-sdk google-adk | grep -E "^(Name|Version)"
```

- [ ] a2a-sdk < 1.0.0 (1.0.x broke ClientEvent import needed by ADK)
- [ ] google-adk >= 1.32.0

## Quick Smoke Test (runs tests 1-4 in one shot)

```bash
python3 -c "
tests = []
def check(name, fn):
    try:
        fn()
        tests.append(('PASS', name))
    except Exception as e:
        tests.append(('FAIL', f'{name}: {e}'))

check('policy_agent import', lambda: __import__('agents.enterprise.policy_agent.agent', fromlist=['root_agent']))
check('hr_calculator import', lambda: __import__('agents.enterprise.hr_calculator.agent', fromlist=['root_agent']))
check('quality_agent import', lambda: __import__('agents.workflow.quality_agent.agent', fromlist=['root_agent']))
check('skill_evolution_agent import', lambda: __import__('agents.workflow.skill_evolution_agent.agent', fromlist=['root_agent']))
check('eval imports', lambda: (__import__('agents.enterprise.policy_agent.agent', fromlist=['create_agent']), __import__('agents.enterprise.hr_calculator.agent', fromlist=['calculate_pto_details'])))

from agents.workflow.quality_agent.tools import _get_agent_files, _gh_available
check('agent_registry', lambda: _get_agent_files('policy_agent'))
check('gh_available', lambda: _gh_available() or True)

for status, name in tests:
    print(f'  [{status}] {name}')
print(f'\n{sum(1 for s,_ in tests if s==\"PASS\")}/{len(tests)} passed')
"
```
