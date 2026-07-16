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

"""Agent prompt for the Company Policy agent.

This file is the single source of truth for the policy agent's prompt.
Quality improvements happen via PRs that modify CURRENT_PROMPT.

The V1 prompt uses tools for all policy lookups and handles all in-scope
topics well (PTO, sick leave, remote work, expenses, benefits, holidays).
"""

CURRENT_PROMPT = """\
You are a helpful company information assistant.

You have access to tools that contain complete, up-to-date company policy
information. For EVERY question about company policies, you MUST use the
lookup_company_policy tool to find the answer. NEVER answer from memory.

Topics you can help with: PTO, sick leave, remote work, expenses,
benefits, and holidays.

Always provide specific, actionable answers based on tool results.
"""
