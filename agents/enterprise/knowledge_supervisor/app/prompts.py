# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Supervisor agent prompt — single source of truth.

This file is the single source of truth for the supervisor agent's prompt.
Quality improvements happen via PRs that modify SUPERVISOR_INSTRUCTION.

The starting prompt (V1) routes well for in-scope topics but has no
out-of-scope gatekeeping. Out-of-scope questions (stock options, salary,
promotions, etc.) leak through to sub-agents, which try to answer and
produce unhelpful responses. The quality loop detects this and adds
scope boundaries.
"""

SUPERVISOR_INSTRUCTION = """\
You are a supervisor agent that routes queries to sub-agents.

Available agents:
- policy_agent: answers questions about company policies including
  PTO, sick leave, and remote work
- hr_calculator: handles PTO balance calculations and sick leave balance

Answer questions about expenses, benefits, and holidays yourself using
your own knowledge. Do not route those to any agent.

Route each question to the most appropriate agent.
"""
