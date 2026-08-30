"""An empty ``TRUSTED_PROXIES`` says two things, and only one of them is fine.

``get_client_ip()`` reads ``X-Forwarded-For`` only from an address named in
``TRUSTED_PROXIES``, and falls back to the connection's own address
otherwise. That is the right rule -- believing the header from anyone hands
every caller a fresh identity per request -- but the empty list it starts
with has two readings that the value cannot tell apart:

* this service is reached directly, and the connecting address *is* the
  client. Correct, and a real deployment.
* there is a proxy in front and nobody named it, so the connecting address
  is the proxy and every visitor in the world is one caller.

Measured on the second, with ``GUEST_LINK_LIMIT=3``, six visitors from six
addresses through one balancer:

    TRUSTED_PROXIES=[]            -> 201, 201, 201, 429, 429, 429
    TRUSTED_PROXIES=['10.0.0.1']  -> 201, 201, 201, 201, 201, 201

The fourth visitor is refused on his first link. Nothing in the service
looks broken; the quota is simply spent by strangers.

A warning rather than a refusal, because the first reading is legitimate --
and a warning rather than silence, because the second one looks like a
working service until somebody complains.
"""

from link_shortener.web.app_factory import create_app

from tests.unit.web.conftest import TestConfig


NEEDLE = "TRUSTED_PROXIES is empty"


def _deployed(**settings):
    """
    A configuration a deployment could actually hold.

    Not merely ``TESTING = False``: switching that on its own turns on the
    rule that a deployed profile runs on PostgreSQL, and the configuration
    is refused before the warning under test is ever reached. The URL names
    a host nothing resolves, which is fine -- the engine is built on first
    use and no request is made here.
    """
    config = TestConfig()
    config.TESTING = False
    config.DEBUG = False
    config.DATABASE_URL = "postgresql+psycopg://u:p@db.invalid:5432/shortener"
    for name, value in settings.items():
        setattr(config, name, value)
    return config


def _warnings(logger):
    return [message for level, message, _ in logger.messages if level == "warning"]


class TestADeployedProfileIsToldAboutIt:

    def test_the_warning_names_the_setting_and_what_it_costs(
        self, test_logger, monkeypatch
    ):
        """
        A deployed profile is one that is neither DEBUG nor TESTING --
        the same reading `_deployed_backend_errors` uses. It is not read
        from the profile's name: a configuration handed over as an object
        carries no `ENV`, so a check on the name is silent for every
        caller that builds its configuration in code.
        """
        from link_shortener.infrastructure.di.container import Container

        monkeypatch.setattr(Container, "get_logger", lambda self, *a, **kw: test_logger)

        create_app(config=_deployed(TRUSTED_PROXIES=[]))

        said = [w for w in _warnings(test_logger) if NEEDLE in w]
        assert said, f"nothing warned about it; warnings were {_warnings(test_logger)}"
        assert "X-Forwarded-For" in said[0]

    def test_naming_a_proxy_settles_it(self, test_logger, monkeypatch):
        from link_shortener.infrastructure.di.container import Container

        monkeypatch.setattr(Container, "get_logger", lambda self, *a, **kw: test_logger)

        create_app(config=_deployed(TRUSTED_PROXIES=["10.0.0.1"]))

        assert not [w for w in _warnings(test_logger) if NEEDLE in w]


class TestALocalRunIsNotNagged:
    """
    A development run reaches the service directly and has no proxy to
    name. A warning there is one an operator learns to scroll past, which
    is how the ones that matter stop being read.
    """

    def test_nothing_is_said_on_a_local_profile(self, test_logger, monkeypatch):
        from link_shortener.infrastructure.di.container import Container

        monkeypatch.setattr(Container, "get_logger", lambda self, *a, **kw: test_logger)

        config = TestConfig()          # TESTING = True
        config.TRUSTED_PROXIES = []
        create_app(config=config)

        assert not [w for w in _warnings(test_logger) if NEEDLE in w]
