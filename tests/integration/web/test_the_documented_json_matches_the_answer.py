"""The JSON blocks in the documentation, against the bodies they illustrate.

Two of the four examples had drifted, and drifted the same way: fields were
added to a response and the example stayed as it was written. Neither is
visible from inside the document -- the JSON is still valid, still
plausible, and still describes a service this project once had.

`getting-started.md` and its Russian twin showed the answer to
`POST /api/v1/shorten` with seven fields where the service returns eleven:
`created_at`, `from_cache`, `last_accessed` and `owner_id` were missing. A
reader building against that example writes code that ignores four fields
it is being sent, and -- worse for `owner_id` and `from_cache` -- does not
learn they exist.

`operations.md` showed `GET /api/v1/admin/health` without `cache_configured`,
`database_schema`, `timed_out`, `journals_written`, `journals_unavailable`
and `worker`. That page is what an operator reads to decide what to monitor,
and `database_schema` is the field that tells a reachable-but-empty database
from a working one.

What is compared is the set of field names, not the values: the values are
timestamps, tokens and counters, and an example carrying real ones would
either be a lie or be regenerated on every run. The names are the contract.
"""

import json
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]

FENCE = re.compile(r"```json\n(.*?)```", re.S)


def json_blocks(rel: str):
    """Every fenced JSON block in one document, parsed."""
    body = (ROOT / rel).read_text(encoding="utf-8")
    out = []
    for block in FENCE.findall(body):
        # An example may elide a long value with an ellipsis; the names are
        # what this file compares, so the value is replaced rather than the
        # block skipped.
        cleaned = re.sub(r'"[^"]*…[^"]*"', '"…"', block)
        try:
            out.append(json.loads(cleaned))
        except json.JSONDecodeError:
            continue
    return out


def block_with(rel: str, key: str):
    """The example in one document that has a given key at its top level."""
    for parsed in json_blocks(rel):
        if isinstance(parsed, dict) and key in parsed:
            return parsed
    return None


class TestTheShortenExampleShowsEveryFieldTheServiceSends:

    @pytest.mark.parametrize(
        "rel", ["docs/getting-started.md", "docs/getting-started.ru.md"]
    )
    def test_the_example_names_exactly_the_fields_of_the_answer(self, rel, client):
        """
        Asked of the running application rather than of the schema class:
        a field the schema declares and the endpoint never sends is not
        what a reader meets, and neither is the reverse.
        """
        answer = client.post(
            "/api/v1/shorten", json={"url": "https://example.com/documented"}
        )
        assert answer.status_code in (200, 201), answer.get_data(as_text=True)

        example = block_with(rel, "short_code")
        assert example is not None, f"{rel} has no shorten example any more"

        assert set(example) == set(answer.get_json()), (
            f"{rel} shows {sorted(example)}, the service answers "
            f"{sorted(answer.get_json())}"
        )


class TestTheHealthExampleShowsEveryFieldTheEndpointReports:
    """
    Held against the OpenAPI document rather than against a live call,
    which needs an administrator and a seeded role. That document is not a
    second opinion: `test_api_docs.py` holds it against the real URL map,
    and the health body has tests of its own in both directions -- so a
    field that reaches the operator reaches this schema first.
    """

    def test_the_example_names_every_field_the_schema_requires(self, client):
        document = client.get("/api/openapi.json").get_json()
        schema = (
            document["paths"]["/api/v1/admin/health"]["get"]["responses"]["200"]
            ["content"]["application/json"]["schema"]
        )
        required = set(schema.get("required") or schema.get("properties", {}))

        example = block_with("docs/operations.md", "database")
        assert example is not None, "operations.md has no health example any more"

        missing = required - set(example)
        assert not missing, (
            f"docs/operations.md does not show {sorted(missing)}, which the "
            f"endpoint reports"
        )

    def test_the_example_invents_nothing(self, client):
        document = client.get("/api/openapi.json").get_json()
        schema = (
            document["paths"]["/api/v1/admin/health"]["get"]["responses"]["200"]
            ["content"]["application/json"]["schema"]
        )
        known = set(schema.get("properties", {})) | set(schema.get("required") or [])

        example = block_with("docs/operations.md", "database")
        invented = set(example) - known

        assert not invented, (
            f"docs/operations.md shows {sorted(invented)}, which the endpoint "
            f"does not report"
        )
