"""The language a message falls back to is the deployment's, not the class's.

``RequestContext.language`` is ``None`` for work nobody negotiated a
language for -- a task queued before the field existed -- and its own
docstring says the mail templates then fall back to the configured
default. They could not: ``default_language`` was a constructor argument
no caller passed, so the fallback was the class's own ``"en"`` on a
service whose ``DEFAULT_LANGUAGE`` said ``ru``.

Asked of the renderer the container actually hands the use case, and
asked by rendering rather than by reading the attribute back: the
attribute agreeing with the setting proves the wiring, not that anything
renders through it.
"""

import pytest

from link_shortener.infrastructure.configs.app.testing import TestingConfig
from link_shortener.infrastructure.di.container import Container


def container_speaking(language):
    """
    A container over a configuration detached from the machine.

    Args:
        language: What this deployment sets ``DEFAULT_LANGUAGE`` to.

    Returns:
        The container.
    """
    config = type("DetachedConfig", (TestingConfig,), {
        # Read from the environment otherwise, which would make this
        # measure the machine it runs on.
        "IGNORE_ENV": True,
        "DATABASE_URL": "sqlite:///:memory:",
        "DEFAULT_LANGUAGE": language,
        "SUPPORTED_LANGUAGES": ["en", "ru", "zh"],
    })()
    return Container(config)


@pytest.mark.parametrize("language, expected_subject", [
    pytest.param("en", "Confirm your email address", id="en"),
    pytest.param("ru", "Подтвердите адрес почты", id="ru"),
    pytest.param("zh", "确认您的邮箱地址", id="zh"),
])
class TestAMessageNobodyChoseALanguageFor:

    def test_the_confirmation_falls_back_to_the_configured_language(
        self, language, expected_subject
    ):
        """
        Args:
            language: The deployment's ``DEFAULT_LANGUAGE``.
            expected_subject: The subject that setting has to produce.
        """
        templates = (
            container_speaking(language)
            .get_send_verification_email_use_case()
            .templates
        )

        subject, _body = templates.verification_email("https://x/y", 24, None)

        assert subject == expected_subject

    def test_the_reset_message_falls_back_the_same_way(
        self, language, expected_subject
    ):
        """The two messages share one renderer, and must share its default.

        Args:
            language: The deployment's ``DEFAULT_LANGUAGE``.
            expected_subject: The confirmation subject that setting has to
                produce. The reset message has a subject of its own, so it
                is checked against the same message asked for the language
                outright.
        """
        templates = (
            container_speaking(language)
            .get_send_password_reset_email_use_case()
            .templates
        )

        confirmation, _body = templates.verification_email("https://x/y", 24, None)
        reset, _reset_body = templates.password_reset_email("https://x/z", 30, None)

        assert confirmation == expected_subject
        assert reset == templates.password_reset_email("https://x/z", 30, language)[0]
