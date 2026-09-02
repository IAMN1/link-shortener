"""What a role may be called, said once and read by the form.

The rule is `role_policy`'s: two to fifty characters of
``[A-Za-z0-9_-]``. The admin schema is built from those constants, and the
form was not -- it stated ``minlength="2"`` and nothing else, so ``my
role`` left the browser happy, went out, and came back ``400`` with the
page having promised otherwise.

This is the same drift the password floor was found in, closed the same
way: the server hands the numbers and the pattern to the template, and the
markup names them instead of restating them. Both ends are held here,
because either alone is a check that agrees with itself.
"""

import re
from pathlib import Path

import pytest

from link_shortener.domain.policies.role_policy import (
    ROLE_NAME_MAX_LENGTH, ROLE_NAME_MIN_LENGTH, ROLE_NAME_PATTERN,
)


TEMPLATES = (
    Path(__file__).resolve().parents[3] / "src/link_shortener/web/templates"
)

ROLE_NAME_FIELD = re.compile(
    r'<input[^>]*id="name"[^>]*>', re.S
)
"""The role-name input, wherever a template draws one."""


@pytest.fixture
def rendering_app():
    """An application whose templates are the real ones.

    Not the shared ``app`` fixture: the web unit conftest replaces every
    template with a stub, so a check reading rendered markup would pass
    whatever the pages say.
    """
    from link_shortener.web.app_factory import create_app
    from tests.unit.web.conftest import TestConfig

    return create_app(config=TestConfig())


def role_name_fields():
    """Every role-name input in the role templates, with its file."""
    return [
        (str(path.relative_to(TEMPLATES)), field)
        for path in sorted(TEMPLATES.rglob("*role*.html"))
        for field in ROLE_NAME_FIELD.findall(
            path.read_text(encoding="utf-8")
        )
    ]


class TestTheFormStatesTheWholeRule:

    def test_there_is_a_role_name_field_to_check(self):
        """The premise: without it every assertion below is vacuous."""
        assert role_name_fields()

    @pytest.mark.parametrize(
        "attribute",
        ["minlength", "maxlength", "pattern"],
    )
    def test_each_bound_is_named_and_not_written_out(self, attribute):
        """A literal here is a second copy of the rule. Only three of the
        four halves were stated at all, and the one that was -- the floor
        -- was a literal."""
        pattern = re.compile(
            rf'{attribute}="\{{\{{\s*role_name_\w+\s*\}}\}}"'
        )

        for name, field in role_name_fields():
            assert pattern.search(field), f"{name}: {field}"


class TestTheServerSuppliesThem:

    def test_the_three_names_carry_the_policy(self, rendering_app):
        """The other end of the same wire."""
        with rendering_app.test_request_context("/"):
            supplied = {}
            for processor in rendering_app.template_context_processors[None]:
                supplied.update(processor())

        assert supplied["role_name_min_length"] == ROLE_NAME_MIN_LENGTH
        assert supplied["role_name_max_length"] == ROLE_NAME_MAX_LENGTH
        assert supplied["role_name_pattern"] == ROLE_NAME_PATTERN.strip("^$")

    def test_the_pattern_reaches_the_browser_without_its_anchors(
        self, rendering_app
    ):
        """HTML anchors a ``pattern`` itself, so ``^`` and ``$`` would be
        matched literally -- a name would have to start with a caret."""
        with rendering_app.test_request_context("/"):
            supplied = {}
            for processor in rendering_app.template_context_processors[None]:
                supplied.update(processor())

        offered = supplied["role_name_pattern"]

        assert not offered.startswith("^")
        assert not offered.endswith("$")
        assert re.fullmatch(offered, "editor")
        assert not re.fullmatch(offered, "my role")


class TestTheRuleAndTheFormAgreeOnRealNames:
    """The premise of the whole file: what the markup offers has to admit
    and refuse what the policy admits and refuses."""

    @pytest.mark.parametrize("name", ["editor", "a-b_c1", "ab"])
    def test_a_name_the_policy_takes_passes_the_pattern(
        self, rendering_app, name
    ):
        from link_shortener.domain.policies.role_policy import (
            require_valid_role_name,
        )

        require_valid_role_name(name)

        with rendering_app.test_request_context("/"):
            supplied = {}
            for processor in rendering_app.template_context_processors[None]:
                supplied.update(processor())

        assert re.fullmatch(supplied["role_name_pattern"], name)

    @pytest.mark.parametrize("name", ["my role", "a/b", "a.b", "x" * 51])
    def test_a_name_the_policy_refuses_is_refused_by_the_form(
        self, rendering_app, name
    ):
        from link_shortener.domain.exceptions import ValidationError
        from link_shortener.domain.policies.role_policy import (
            require_valid_role_name,
        )

        with pytest.raises(ValidationError):
            require_valid_role_name(name)

        with rendering_app.test_request_context("/"):
            supplied = {}
            for processor in rendering_app.template_context_processors[None]:
                supplied.update(processor())

        too_long = len(name) > supplied["role_name_max_length"]
        assert too_long or not re.fullmatch(
            supplied["role_name_pattern"], name
        ), name
