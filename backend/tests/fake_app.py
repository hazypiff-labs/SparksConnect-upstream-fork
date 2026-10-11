"""ASGI entry point for the test server: the real app with the Claude call replaced by a deterministic fake.

Started by conftest.py (`uvicorn tests.fake_app:app`). Never import this in production code.
"""
import json
import re

import recommend
import server

app = server.app


def _venue_ids(prompt: str) -> list[str]:
    return re.findall(r'"venue_id": "([^"]+)"', prompt)


async def fake_llm_complete(system: str, prompt: str, model: str) -> str:
    """Three sparks of three stops each, reusing real venue ids from the prompt when there are any."""
    ids = _venue_ids(prompt) or [None]
    sparks = []
    for i in range(3):
        sparks.append(
            {
                "title": f"Test Spark {i + 1}",
                "emoji": "✨",
                "tagline": "Coffee → Walk → Dessert",
                "description": "A deterministic plan produced by the test LLM.",
                "primary_vibe": "Romantic",
                "vibe_tags": ["Romantic"],
                "estimated_cost": "$30",
                "estimated_duration": "2 hours",
                "why": "Because tests need stable output.",
                "dress_code": "Smart casual",
                "activities": [
                    {"name": name, "venue_id": ids[(i + j) % len(ids)], "start_time": f"{6 + j}:00 PM", "end_time": f"{7 + j}:00 PM", "estimated_cost": "$10", "note": "tip"}
                    for j, name in enumerate(("Coffee", "Walk", "Dessert"))
                ],
            }
        )
    return json.dumps({"sparks": sparks})


recommend.llm_complete = fake_llm_complete
