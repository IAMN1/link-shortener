"""What the two password forms promise, against what the service enforces.

An HTML `minlength` is a promise: the browser refuses to submit anything
shorter, so whatever it does submit the page has said is acceptable. Both
password forms wrote that promise out as `6` while
`MIN_PASSWORD_LENGTH` was `8` -- a seven-character password passed the
browser and came back refused, from a form that had just accepted it.

This is the third copy of that number. The first two were found the same
way: `CreateUserRequest` said six against a policy of eight, and its
docstring records the fix -- "The floor comes from the domain policy
rather than a number typed here". The markup was not looked at then.

Read out of the rendered pages rather than asserted against the source,
because what a template says and what a browser receives are two things,
and it is the second one that makes the promise.
"""

import re

import pytest

from link_shortener.domain.policies.password_policy import MIN_PASSWORD_LENGTH


PASSWORD_FIELD = re.compile(
    r'<input[^>]*type="password"[^>]*>', re.IGNORECASE
)
"""Every password input on a page, however its attributes are ordered."""

MINLENGTH = re.compile(r'minlength="(\d+)"')


def password_floors(html):
    """
    The `minlength` of every password field on a page.

    Args:
        html: The rendered page.

    Returns:
        List of the floors found, as integers. A field carrying no
        `minlength` contributes nothing -- that is a missing promise
        rather than a wrong one, and the check below says which pages
        must carry one.
    """
    return [
        int(found.group(1))
        for field in PASSWORD_FIELD.findall(html)
        for found in [MINLENGTH.search(field)] if found
    ]


@pytest.fixture()
def rendering_app():
    """
    An application whose templates are the real ones.

    Not the shared ``app`` fixture: the web unit conftest replaces every
    template with a stub, so a check reading rendered markup would pass
    here whatever the pages say.
    """
    from link_shortener.web.app_factory import create_app
    from tests.unit.web.conftest import TestConfig

    return create_app(config=TestConfig())


MINLENGTH_FROM_SERVER = re.compile(
    r'minlength="\{\{\s*min_password_length\s*\}\}"'
)
"""The floor as a template reads it: from the one name the server sets."""


def _password_fields():
    """Every password input in every template, with the file it is in."""
    from pathlib import Path

    templates = (
        Path(__file__).resolve().parents[3]
        / "src/link_shortener/web/templates"
    )
    return [
        (str(path.relative_to(templates)), field)
        for path in sorted(templates.rglob("*.html"))
        for field in PASSWORD_FIELD.findall(path.read_text(encoding="utf-8"))
    ]


def _new_password_fields():
    """Only the ones that set a password, as the browsers mark them."""
    return [
        (name, field)
        for name, field in _password_fields()
        if 'autocomplete="new-password"' in field
    ]


class TestTheFormTheBrowserIsSent:
    """Read off the wire, because that is what makes the promise."""

    def test_the_register_form_promises_the_policy(self, rendering_app):
        page = rendering_app.test_client().get("/register")

        floors = password_floors(page.get_data(as_text=True))

        assert floors, "the register page promises no floor at all"
        assert set(floors) == {MIN_PASSWORD_LENGTH}, (
            f"the page promises {floors}, the policy enforces "
            f"{MIN_PASSWORD_LENGTH}"
        )


class TestTheNumberHasOneHome:

    def test_no_template_writes_the_floor_itself(self):
        """
        The check above renders with the real value supplied, so a
        template hard-coding the same digit would pass it. What must not
        exist is a second home for the number -- and the second form,
        ``dashboard/create_user.html``, is behind a login that a unit
        test has no business standing up.
        """
        from pathlib import Path

        root = Path(__file__).resolve().parents[3]
        templates = root / "src/link_shortener/web/templates"
        written = [
            str(path.relative_to(templates))
            for path in templates.rglob("*.html")
            for field in PASSWORD_FIELD.findall(path.read_text(encoding="utf-8"))
            if MINLENGTH.search(field)
            and MINLENGTH.search(field).group(1).isdigit()
        ]

        assert not written, (
            f"these templates write the password floor as a literal: {written}"
        )

    def test_every_field_that_sets_a_new_password_promises_the_floor(self):
        """
        Asked of the rule rather than of the pages that had the fault.

        Named pages was what this check did first, and it named the two
        whose ``minlength`` was wrong -- ``6`` against a policy of ``8``.
        The two pages that set a new password and promised *nothing*
        (``public/reset_password.html`` and ``dashboard/security.html``,
        four fields between them) were not on the list and were not
        looked at: a floor absent is the same undelivered promise as a
        floor too low, arriving quietly.

        ``autocomplete="new-password"`` is what the browsers themselves
        use to mean "this field sets a password", so a form added later
        is held to this without a line here.
        """
        for name, field in _new_password_fields():
            assert MINLENGTH_FROM_SERVER.search(field), f"{name}: {field}"

    def test_the_scan_found_the_fields(self):
        """The check above passes trivially if the pattern stops matching."""
        found = {name for name, _ in _new_password_fields()}

        assert found >= {
            "public/register.html",
            "dashboard/create_user.html",
            "public/reset_password.html",
            "dashboard/security.html",
        }, found

    def test_signing_in_promises_nothing(self):
        """
        The other side, and the reason the rule reads ``new-password``.

        A sign-in field carrying the floor would refuse to submit the
        password of an account made before the policy was raised -- a
        page locking somebody out of their own account over a rule that
        applies to setting a password, not to typing an existing one.
        """
        for name, field in _password_fields():
            if 'autocomplete="current-password"' not in field:
                continue

            assert not MINLENGTH.search(field), f"{name}: {field}"

    def test_the_server_supplies_it(self, rendering_app):
        """The other end of the same wire."""
        with rendering_app.test_request_context("/"):
            supplied = {}
            for processor in rendering_app.template_context_processors[None]:
                supplied.update(processor())

        assert supplied.get("min_password_length") == MIN_PASSWORD_LENGTH
