"""What a role may be described as, asked of the rule rather than a schema.

The other half of ``test_role_name_policy``, and it was missing for the
same reason the rule was: the bound lived in the admin API's Pydantic
field, and roles arrive by a second route -- ``flask db
load-custom-roles``, which reads a YAML file -- that never meets it.

Measured on the running stack before the rule existed: a 256-character
description in such a file came back as
``sqlalchemy.exc.DataError: (psycopg.errors.StringDataRightTruncation)
value too long for type character varying(255)``, a traceback out of the
driver, where the same file's malformed *name* is refused with a sentence
naming the field. SQLite does not check the width at all, so the suite
alone would never have shown it.
"""

import pytest

from link_shortener.domain import ValidationError
from link_shortener.domain.policies.role_policy import (
    ROLE_DESCRIPTION_MAX_LENGTH, require_valid_role_description,
)


class TestDescriptionsTheRuleAccepts:

    @pytest.mark.parametrize("description", [
        None,
        "",
        "Regular registered user",
        "Роль для контент-менеджеров",
        "d" * ROLE_DESCRIPTION_MAX_LENGTH,
    ])
    def test_a_description_the_column_holds_passes(self, description):
        require_valid_role_description(description)

    def test_the_shipped_descriptions_pass(self):
        """The rule must not refuse what the service itself ships."""
        import yaml

        from link_shortener.infrastructure.database.seed import (
            DEFAULT_RBAC_CONFIG_PATH,
        )

        with open(DEFAULT_RBAC_CONFIG_PATH, encoding="utf-8") as handle:
            shipped = yaml.safe_load(handle)

        for role in shipped["roles"]:
            require_valid_role_description(role.get("description"))


class TestDescriptionsTheRuleRefuses:

    def test_one_character_past_the_column_is_refused(self):
        with pytest.raises(ValidationError) as refusal:
            require_valid_role_description(
                "d" * (ROLE_DESCRIPTION_MAX_LENGTH + 1)
            )

        assert refusal.value.field == "description"
        assert str(ROLE_DESCRIPTION_MAX_LENGTH) in refusal.value.message

    @pytest.mark.parametrize("description, why", [
        (123, "``len()`` raises TypeError on it, which names no field"),
        (True, "a bare `yes` in YAML parses to a boolean"),
        (["a", "b"], "``len()`` measures two and the list goes to the column"),
        ({"text": "x"}, "the same, one key long"),
    ])
    def test_something_that_is_not_text_is_refused(self, description, why):
        """
        A YAML file can put anything at all under ``description``, which
        is the door this rule stands at. Refused rather than measured:
        ``len()`` raises on some of these and quietly succeeds on the
        rest, and neither is an answer naming the field.
        """
        with pytest.raises(ValidationError) as refusal:
            require_valid_role_description(description)

        assert refusal.value.field == "description", why
