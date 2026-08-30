"""
The shortener's load profile.

To run it (the stack has to be up, see docs/development.md):

    uv sync --group load
    uv run locust -f tests/load/locustfile.py --headless \
        -u 60 -r 20 -t 60s -H http://localhost:5000

Four scenarios, each in a class of its own; choose with `--class-picker` or
by naming `RedirectUser`/`CreateUser`/`HealthUser`/`MixedUser` at the end of
the command line.

The profile names the client address itself, a different one per request.
The rate limiter counts by address (200 a minute for a redirect, 30 for a
creation), so load from a single address runs into the counter at the third
request a second: what would be measured is the limiter, not the service.
Measured: 20 users behind one address produced 85% of answers as 429 -- a
run without an address per request measures the limiter and nothing else.

An address per request models "many different callers"; it does not walk
around the check. The limiter stays in the path and still costs one INCR in
Redis per request. That is the case worth measuring: saturation by a single
caller is what the limiter defends against, while pools and timeouts are
needed where the callers are many.

The address arrives in an ``X-Forwarded-For`` header, and the deployment
under measurement declares the address locust comes from as trusted
(``TRUSTED_PROXIES``). That is the same path a client address takes from
behind a balancer in service.

pytest does not collect this file: its name does not match ``python_files``.
"""

import itertools
import random

from locust import HttpUser, between, constant, events, task


SEED_LINKS = 200
"""How many links are created first, so the redirect has somewhere to go."""

_addresses = itertools.count(1)
"""The counter each user takes its own address from."""

SHORT_CODES: list[str] = []
"""The codes created during seeding. Shared by every user."""


def _next_address() -> str:
    """
    Hand out the next address from the 10.0.0.0/8 block.

    Returns:
        An address in dotted notation, a different one on every call.
    """
    n = next(_addresses)
    return f"10.{(n >> 16) & 0xFF}.{(n >> 8) & 0xFF}.{n & 0xFF}"


@events.test_start.add_listener
def seed_links(environment, **_kwargs):
    """
    Create the links the redirect will walk.

    Without this step the redirect would measure a miss: a code that does
    not exist is a 404 out of the cache, not the path "find the link, count
    the visit, answer".

    Args:
        environment: locust's environment; the base address comes from it.
    """
    import requests

    base = environment.host.rstrip("/")
    SHORT_CODES.clear()
    with requests.Session() as session:
        for i in range(SEED_LINKS):
            response = session.post(
                f"{base}/api/v1/shorten",
                json={"url": f"https://example.com/load-{i}"},
                headers={"X-Forwarded-For": _next_address()},
                timeout=10,
            )
            if response.status_code in (200, 201):
                SHORT_CODES.append(response.json()["short_code"])

    if not SHORT_CODES:
        raise RuntimeError(
            "not one link was created: check TRUSTED_PROXIES and "
            "GUEST_LINK_LIMIT in the env file of the stack under measurement"
        )


class RedirectUser(HttpUser):
    """Redirects only -- the hottest path of the service."""

    wait_time = constant(0)

    @task
    def follow(self) -> None:
        """Follow a short code chosen at random."""
        code = random.choice(SHORT_CODES)
        self.client.get(
            f"/{code}",
            name="GET /<code>",
            headers={"X-Forwarded-For": _next_address()},
            allow_redirects=False,
        )


class CreateUser(HttpUser):
    """Creating links only -- the costliest path: a write plus an invalidation."""

    wait_time = constant(0)

    def on_start(self) -> None:
        """Set up the counter the distinct addresses come from."""
        self.counter = 0

    @task
    def shorten(self) -> None:
        """Shorten an address that has not been seen before."""
        self.counter += 1
        self.client.post(
            "/api/v1/shorten",
            json={"url": f"https://example.com/{self.counter}-{id(self)}"},
            headers={"X-Forwarded-For": _next_address()},
            name="POST /api/v1/shorten",
        )


class HealthUser(HttpUser):
    """/health only -- the path the container's healthcheck polls."""

    wait_time = constant(0)

    @task
    def health(self) -> None:
        """Ask after the state of the dependencies."""
        self.client.get("/health", name="GET /health")


class MixedUser(HttpUser):
    """
    The mixture in the proportion a shortener actually works in.

    Nine redirects per creation, and one health poll per hundred requests: a
    link is created once and opened many times.
    """

    wait_time = between(0, 0.05)

    def on_start(self) -> None:
        """Set up the counter the distinct addresses come from."""
        self.counter = 0

    @task(90)
    def follow(self) -> None:
        """Follow a short code chosen at random."""
        code = random.choice(SHORT_CODES)
        self.client.get(
            f"/{code}",
            name="GET /<code>",
            headers={"X-Forwarded-For": _next_address()},
            allow_redirects=False,
        )

    @task(9)
    def shorten(self) -> None:
        """Shorten an address that has not been seen before."""
        self.counter += 1
        self.client.post(
            "/api/v1/shorten",
            json={"url": f"https://example.com/{self.counter}-{id(self)}"},
            headers={"X-Forwarded-For": _next_address()},
            name="POST /api/v1/shorten",
        )

    @task(1)
    def health(self) -> None:
        """Ask after the state of the dependencies."""
        self.client.get("/health", name="GET /health")
