"""Which containers wait for the migration before they start writing.

`migrations` runs `alembic upgrade head` and is the only thing that puts
the schema in place. Two services then write to that schema: `app` serves
requests, and `celery_worker` drains the queue — click counts, the nightly
roll-ups, the record of every mail sent.

`docs/getting-started.md` says so in as many words — "`migrations` runs
`alembic upgrade head` and has to exit `0` before `app` **and
`celery_worker`** are started" — and the diagram beside it draws the same
edge to both. Only `app` had it. Measured on a run whose migration failed
against a reused volume: `app` stayed `Created`, and the worker was `Up`
beside it, already consuming.

Read out of the compose file rather than asserted against a copy of it,
so a dependency dropped in editing fails here rather than at the next
deployment that starts from nothing.
"""

from pathlib import Path

import pytest
import yaml


COMPOSE = Path(__file__).resolve().parents[3] / "dockers/docker-compose.yml"

WRITERS = ("app", "celery_worker")
"""The services that write to the schema `migrations` applies."""


@pytest.fixture(scope="module")
def services():
    """The compose file's services, as declared.

    Read raw rather than through `docker compose config`: this must be
    answerable without a Docker daemon, and what is under test is the
    declaration, not an interpolation of it.
    """
    document = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    found = document.get("services", {})
    assert found, f"{COMPOSE} declares no services"
    return found


class TestEveryWriterWaitsForTheMigration:

    def test_the_writers_are_all_there(self, services):
        """
        A typo in a service name would make every check below vacuous.
        """
        missing = [name for name in WRITERS if name not in services]

        assert not missing, f"{COMPOSE} no longer declares {missing}"

    @pytest.mark.parametrize("service", WRITERS)
    def test_it_waits_for_migrations_to_finish(self, services, service):
        waits_for = services[service].get("depends_on") or {}

        assert "migrations" in waits_for, (
            f"{service} does not wait for `migrations`, so it can start "
            f"against a database with no schema — and it writes"
        )
        assert (
            waits_for["migrations"].get("condition")
            == "service_completed_successfully"
        ), (
            f"{service} waits for `migrations` on "
            f"{waits_for['migrations'].get('condition')!r}; only "
            f"`service_completed_successfully` means the schema is there"
        )

    @pytest.mark.parametrize("service", WRITERS)
    def test_the_wait_is_not_optional(self, services, service):
        """
        `required: false` is how the infrastructure services are made
        optional under a profile that is off. The migration carries no
        profile and is never absent, so an optional wait here would be a
        wait that a profile could switch off.
        """
        wait = (services[service].get("depends_on") or {})["migrations"]

        assert wait.get("required", True) is not False, (
            f"{service}'s wait for `migrations` is marked optional"
        )
