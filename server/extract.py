"""LLM-powered DDL extraction from message text."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from openai import OpenAI

PROMPT_DIR = Path(__file__).parent.parent / "prompts"
EXTRACT_PROMPT = (PROMPT_DIR / "extract-ddl.md").read_text(encoding="utf-8")


def _get_client():
    return OpenAI(
        api_key=os.environ["LLM_API_KEY"],
        base_url=os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1"),
        timeout=30.0,
        max_retries=1,
    )


def extract_ddl(text: str) -> list[dict] | None:
    """Extract DDL info from raw message text. Returns list of DDL dicts or None."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt = EXTRACT_PROMPT.replace("{current_date}", today)

    client = _get_client()
    resp = client.chat.completions.create(
        model=os.environ.get("LLM_MODEL", "deepseek-chat"),
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": text},
        ],
        max_tokens=2000,
        temperature=0.0,
    )

    raw = resp.choices[0].message.content or ""
    return _parse_response(raw)


def _parse_response(raw: str) -> list[dict] | None:
    """Parse LLM response into structured DDL list."""
    raw = raw.strip()
    # Strip markdown code fences
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:]) if len(lines) > 1 else raw
    if raw.endswith("```"):
        raw = raw[:-3].strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Try to extract JSON from the text
        import re
        m = re.search(r'\[.*\]', raw, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group())
            except json.JSONDecodeError:
                return None
        else:
            return None

    if data is None or data == []:
        return None

    if isinstance(data, list):
        return data
    return None
