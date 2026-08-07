"""
Short codes the service cannot give away, because it answers to them itself.

The redirect route is ``/<short_code>``, one path segment, and it shares that
space with every top-level page the service serves. Werkzeug prefers a
static rule to a dynamic one, so a link whose code is ``health`` is not a
hijacked health check -- it is a link that never resolves, because
``/health`` answers first. Either way the caller was handed a code that does
not work, and only a custom code can produce one: generated codes are random
and the chance is negligible, while a person picking a code picks words.

Only names that could actually be a code are listed. A short code is 6 to 10
characters from ``[a-zA-Z0-9_-]``, so ``/login`` and ``/api`` are out of
reach by being too short, and nothing needs to be said about them. A test
holds this list against the application's real URL map, so a route added
later is a failing test rather than a code nobody can use.
"""

RESERVED_CODES = frozenset({
    "health",
    "console",
    "static",
    "logout",
    "register",
    "refresh",
    "dashboard",
    "favicon",
    "robots",
    "sitemap",
    "metrics",
    "openapi",
    "swagger",
})
"""Lower-cased. Comparison folds case: codes are case-sensitive to the
router, but a person asking for ``Health`` means the word, and handing them
a link that half the tooling normalizes into a route is not an answer.
"""


def is_reserved(code: str) -> bool:
    """
    Tell whether a code would collide with the service's own paths.

    Args:
        code: Candidate short code.

    Returns:
        ``True`` if the code must not be issued.
    """
    return code.lower() in RESERVED_CODES
