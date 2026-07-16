# Project: Knowledge Supervisor (Agent Quality Lab)

## Context Management (CRITICAL for long sessions)

When running experiments, traffic generation, or any command that produces
verbose output:

1. **Always redirect output to files**, then tail the summary:
   ```bash
   command_here > eval/some_log.log 2>&1
   tail -20 eval/some_log.log
   ```
2. **Never let raw HTTP/API logs enter the conversation.** Use `2>&1 | tail -N`.
3. **Don't re-read files already in context.** Use grep for specific lookups.
4. **After every major milestone**, update `STATUS.md` at the repo root with:
   - What was just completed
   - What's next
   - Key results (numbers, not raw data)
5. **If context is getting large** (you've done 3+ experiment cycles), commit
   your work, update STATUS.md, and tell the user: "Context is getting large.
   I've committed and updated STATUS.md. Start a new session to continue."

## Session Handoff

- `STATUS.md` at repo root is the handoff document. Read it at session start.
- Always update STATUS.md before ending a session.
- Memory files in `~/.claude/projects/.../memory/` have durable project context.

## Code Conventions

- Python scripts in `scripts/` must have `.sh` wrappers that source `.env`.
- Always use LLM-as-judge for quality scoring, never string matching.
- No `Co-Authored-By` lines in git commits.
- All V2/skill-evolution changes must keep V1 demo fully functional.
- Run autoformat and tests before pushing.
- Never push code without proving it works end-to-end locally first.
- No inline `python3 -c` blocks in `.sh` files.

## Evolution Test Cycle (invoke with: "run evolution test cycle")

When the user asks to run an evolution test cycle, follow this EXACT procedure.
Print timing for every step. Review every skill before proceeding.

**Setup:**
```
source .env
RUN_DIR="eval/runs/$(date +%Y-%m-%d_%H%M%S)_evolution"
mkdir -p "$RUN_DIR"
```

**Reusable V0 data (Do not regenerate V0 traffic unless asked explicitly):**
- V0 reference run: `eval/skill_evolution/reference_runs/v0_baseline_demo/`
- V0 traffic: `eval/skill_evolution/reference_runs/v0_baseline_demo/v0_traffic.json` (205q)
- V0 quality report: `eval/skill_evolution/reference_runs/v0_baseline_demo/v0_quality_report.json`
- Quick questions: `eval/data/questions/demo_quick.json` (22q)
- V0 skill baseline: `agents/enterprise/policy_agent/skill/SKILL.v0.md`

**Golden reference (target):** V0=60% → V1=94% → V2=98% (May 16 run)

**Scorer:** Use `score_conversations.py` (SDK scorer) for all scoring. It handles
ground truth, turn tagging, trajectory sampling, and quality scoring in a single pass.

### Steps:

1. **Score V0** (skip if scorer unchanged — reuse existing report)
   - `score_conversations.py -i results.json -o quality_report.json --tag-turns --trajectory-samples 100 --report`
   - Print: meaningful_rate, unhelpful_rate, total_sessions
   - Print: elapsed time

2. **Evolve V0→V1** (ALWAYS `--agentic`, use `--candidates 3` for best-of-N)
   - `evolve.py --agentic --model gemini-2.5-pro --max-workers 10 --candidates 3 --candidates-dir $RUN_DIR/v1_candidates`
   - Print: elapsed time, patch count, analyst count

3. **Review V1 skill** (MANDATORY before traffic)
   - Print: file size (expect 8-15KB), version, section headings
   - Check: keyword mappings table exists, anti-patterns section exists
   - Check: no excessive repetition, no bloat
   - Write summary: what's good, what's missing vs golden V1
   - If skill looks bad: STOP and tell user. Do NOT proceed.

4. **Deploy V1 + quick traffic** (22 questions, ~3 min). If asked to do a full, run all 205 questions.
   - Backup V0 skill first, deploy V1, run traffic generator
   - Print: elapsed time

5. **Score V1**
   - Print: meaningful_rate, delta from V0, elapsed time

6. **Evolve V1→V2** (ALWAYS `--agentic`)
   - Print: elapsed time, patch count

7. **Review V2 skill** (same checks as step 3)
   - Write summary comparing V2 vs V1

8. **Deploy V2 + quick traffic + score**
   - Print: meaningful_rate, delta from V1, elapsed time

9. **Restore V0 skill** (always restore after testing)

10. **Print final summary table:**
    ```
    | Version | Meaningful | Unhelpful | Delta | Time |
    ```

### Rules:
- NEVER skip skill review (steps 3 and 7)
- NEVER run without --agentic
- NEVER use full 205q set for iteration (use 22q quick)
- ALWAYS restore V0 skill at the end
- ALWAYS print elapsed time per step
- Full handbook: `docs/skill-evolution/QUICK_EVOLUTION_RUNBOOK.md`

## Key Paths

- Agent code: `agents/enterprise/` (policy_agent, knowledge_supervisor, hr_calculator)
- Workflow agents: `agents/workflow/` (skill_evolution_agent, remediation_agent, quality_agent, traffic_generator)
- Eval data & results: `eval/`
- Blog & docs: `docs/skill-evolution/`
- Skills (V0 baseline): `agents/enterprise/*/skill/SKILL.md`
- V0 baselines: `agents/enterprise/*/skill/SKILL.v0.md` (next to SKILL.md)
