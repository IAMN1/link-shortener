"""
Running on generated secrets is a configuration, not an accident -- but a
silent one was hiding a failure that reads as a bug elsewhere.

``SECRET_KEY`` and ``SHORT_CODE_PEPPER`` fall back to a random value
generated once per process, at import. ``validate()`` deliberately
tolerates that outside production, so a development deployment with more
than one worker gives each worker a different key. Tokens issued by one are
rejected by the others as invalid and cache entries written by one are
refused by the rest, and the operator sees intermittent 401s with nothing
in the logs pointing at the cause.
"""


from link_shortener.infrastructure.configs.app.base import BaseConfig


class TestTheConfigKnowsWhenItsSecretsAreGenerated:
    """The condition is reportable, so it can be reported."""

    # BaseConfig rather than TestingConfig: the testing profile pins both
    # secrets to fixed strings, so it can never exhibit the condition under
    # test. Using it here would have made every one of these pass without
    # touching the code they are about.
    def test_a_generated_key_is_named(self, monkeypatch):
        monkeypatch.delenv("SECRET_KEY", raising=False)
        monkeypatch.delenv("SHORT_CODE_PEPPER", raising=False)

        config = BaseConfig()

        assert "SECRET_KEY" in config.default_secrets_in_use()
        assert "SHORT_CODE_PEPPER" in config.default_secrets_in_use()

    def test_a_configured_key_is_not_named(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "a-real-key-from-the-environment")
        monkeypatch.setenv("SHORT_CODE_PEPPER", "a-real-pepper")

        config = BaseConfig()

        assert config.default_secrets_in_use() == []

    def test_the_default_is_per_process_not_per_config(self, monkeypatch):
        """
        Two configs in one process agree; two processes would not.

        This is the property that makes the warning worth emitting: the
        value is fixed at import, so it is shared by everything inside one
        worker and by nothing outside it.
        """
        monkeypatch.delenv("SECRET_KEY", raising=False)

        first, second = BaseConfig(), BaseConfig()

        assert first.SECRET_KEY == second.SECRET_KEY
        assert first.SECRET_KEY == BaseConfig._default_secret_key
