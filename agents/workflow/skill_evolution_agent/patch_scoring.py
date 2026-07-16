#!/usr/bin/env python3
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

"""Patch quality scoring for skill evolution.

Scores analyst patches on relevance, specificity, and generalizability
before consolidation. Allows the consolidator to prioritize high-quality
patches and filter out noise, reducing stochasticity in the evolution
pipeline.

Usage:
    from agents.workflow.skill_evolution_agent.patch_scoring import score_and_rank_patches

    scored = score_and_rank_patches(client, model_id, patches, current_skill)
    # scored = [(patch_text, score_dict), ...] sorted by composite score
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

PATCH_SCORER_PROMPT = """\
You are a Patch Quality Scorer for a skill evolution system. You evaluate
proposed skill patches on three dimensions.

Score each dimension 1-5:

1. RELEVANCE (1-5): Does this patch address a real, reproducible failure
   pattern? Or is it too specific to one question?
   - 5: Addresses a common failure pattern seen across many questions
   - 3: Addresses a real issue but somewhat niche
   - 1: Overly specific to one question or addresses a non-issue

2. SPECIFICITY (1-5): Is the proposed fix concrete and actionable?
   - 5: Exact text to add, clear section placement, ready to integrate
   - 3: Good direction but needs refinement
   - 1: Vague, hand-wavy, or just restates the problem

3. GENERALIZABILITY (1-5): Will this fix help with similar future questions?
   - 5: Covers a class of questions (e.g., all synonym mappings)
   - 3: Covers a specific subcategory
   - 1: Only fixes the exact question that was analyzed

Output format (JSON only):
{
  "relevance": <1-5>,
  "specificity": <1-5>,
  "generalizability": <1-5>,
  "composite": <float 0.0-1.0>,
  "rationale": "<one sentence>"
}

The composite score should be (relevance + specificity + generalizability) / 15.
"""


def score_patch(
    client: genai.Client,
    model_id: str,
    patch: str,
    current_skill: str,
) -> dict:
    """Score a single patch on quality dimensions.

    Returns:
        Dict with relevance, specificity, generalizability, composite, rationale.
    """
    prompt = (
        f"<current_skill>\n{current_skill}\n</current_skill>\n\n"
        f"<patch>\n{patch}\n</patch>\n\n"
        f"Score this patch. Output ONLY the JSON object."
    )

    response = client.models.generate_content(
        model=model_id,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=PATCH_SCORER_PROMPT,
            temperature=0.1,
            response_mime_type="application/json",
        ),
    )

    try:
        scores = json.loads(response.text.strip())
        # Ensure composite is calculated correctly
        r = scores.get("relevance", 3)
        s = scores.get("specificity", 3)
        g = scores.get("generalizability", 3)
        scores["composite"] = (r + s + g) / 15.0
        return scores
    except (json.JSONDecodeError, AttributeError):
        return {
            "relevance": 3,
            "specificity": 3,
            "generalizability": 3,
            "composite": 0.6,
            "rationale": "Could not parse scorer output",
        }


def score_and_rank_patches(
    client: genai.Client,
    model_id: str,
    patches: list[str],
    current_skill: str,
    min_score: float = 0.4,
    max_workers: int = 10,
) -> list[tuple[str, dict]]:
    """Score all patches and return ranked list with scores.

    Args:
        client: Genai client.
        model_id: Model for scoring calls.
        patches: List of patch texts from analysts.
        current_skill: Current SKILL.md content.
        min_score: Minimum composite score to keep (0-1). Default 0.4.
        max_workers: Max parallel scoring threads.

    Returns:
        List of (patch_text, score_dict) tuples, sorted by composite
        score descending. Patches below min_score are filtered out.
    """
    if not patches:
        return []

    logger.info("Scoring %d patches for quality...", len(patches))

    scored = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(score_patch, client, model_id, patch, current_skill): i
            for i, patch in enumerate(patches)
        }
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                score = fut.result()
                scored.append((patches[idx], score))
                logger.debug(
                    "  Patch %d: composite=%.2f (%s)",
                    idx + 1, score["composite"], score.get("rationale", ""),
                )
            except Exception as e:
                logger.warning("  Patch %d scoring FAILED: %s", idx + 1, e)
                # Keep patch with neutral score
                scored.append((patches[idx], {
                    "composite": 0.6,
                    "rationale": f"Scoring failed: {e}",
                }))

    # Filter by minimum score
    pre_filter = len(scored)
    scored = [(p, s) for p, s in scored if s["composite"] >= min_score]
    filtered = pre_filter - len(scored)
    if filtered:
        logger.info(
            "Quality filter removed %d/%d patches (min_score=%.2f)",
            filtered, pre_filter, min_score,
        )

    # Sort by composite score descending
    scored.sort(key=lambda x: x[1]["composite"], reverse=True)

    if scored:
        top = scored[0][1]["composite"]
        bottom = scored[-1][1]["composite"]
        logger.info(
            "Patch scoring complete: %d patches kept, "
            "scores range %.2f - %.2f",
            len(scored), bottom, top,
        )

    return scored


def annotate_patches_for_consolidator(
    scored_patches: list[tuple[str, dict]],
) -> list[str]:
    """Annotate patches with quality scores for the consolidator.

    Adds a quality header to each patch so the consolidator can
    prioritize high-scoring patches during merge.

    Returns:
        List of annotated patch strings.
    """
    annotated = []
    for patch, score in scored_patches:
        header = (
            f"[Quality Score: {score['composite']:.2f} — "
            f"relevance={score.get('relevance', '?')}, "
            f"specificity={score.get('specificity', '?')}, "
            f"generalizability={score.get('generalizability', '?')}]\n\n"
        )
        annotated.append(header + patch)
    return annotated
