"""What a deployed profile allows a browser to read, before anyone configures it.

``CORS_ORIGINS`` defaults to ``http://localhost:5000`` in the base
configuration, which is the right answer for a run on a laptop. Inherited by
``production`` it was the wrong answer everywhere else, and it was not a
setting a deployment was ever told to revisit: the profile refuses to start
without five values, and this was not among them.

Measured on a deployed profile carrying the inherited default, with
``DOMAIN=maizlink.example``:

    Origin http://localhost:5000     -> Allow-Origin: http://localhost:5000
                                        Allow-Credentials: true
    Origin https://maizlink.example  -> no CORS headers (same-origin needs none)
    Origin https://evil.example      -> no CORS headers

So a page a visitor opened on that port -- anybody's page, on their own
machine -- could send requests carrying that visitor's cookies and read the
answers. The allowance served nobody: the service's own pages are
same-origin and never consult it.

Empty is not closed. ``csrf.py`` adds ``BASE_URL`` to the origins it
admits, so forms keep working with nothing named here; what is empty is the
list of *other* origins. Measured: with ``CORS_ORIGINS`` empty, a signed-in
form post from ``https://maizlink.example`` answered 201, and the same post
from ``https://evil.example`` answered 403.
"""

import pytest

from link_shortener.infrastructure.configs.app.base import BaseConfig
from link_shortener.infrastructure.configs.app.production import ProductionConfig
from link_shortener.infrastructure.configs.app.staging import StagingConfig


DEPLOYED = [ProductionConfig, StagingConfig]


class TestNeitherDeployedProfileInheritsTheLaptop:

    @pytest.mark.parametrize("profile", DEPLOYED)
    def test_no_origin_is_allowed_until_one_is_named(self, profile, monkeypatch):
        monkeypatch.delenv("CORS_ORIGINS", raising=False)

        assert profile().CORS_ORIGINS == []

    @pytest.mark.parametrize("profile", DEPLOYED)
    def test_the_laptop_origin_is_not_among_them(self, profile, monkeypatch):
        """
        Named rather than implied by the emptiness above: a later default of
        ``["*"]`` or ``["http://localhost:3000"]`` would pass a length check
        and be the same defect.
        """
        monkeypatch.delenv("CORS_ORIGINS", raising=False)
        origins = profile().CORS_ORIGINS

        assert not any("localhost" in o or "127.0.0.1" in o for o in origins)

    @pytest.mark.parametrize("profile", DEPLOYED)
    def test_a_deployment_can_still_name_its_own(self, profile, monkeypatch):
        """
        Empty is a default, not a refusal. A service with a separate
        front-end names its origin the way every other setting is named.
        """
        monkeypatch.setenv("CORS_ORIGINS", "https://app.example,https://admin.example")

        assert profile().CORS_ORIGINS == [
            "https://app.example",
            "https://admin.example",
        ]


class TestTheLaptopDefaultIsStillThereForTheLaptop:
    """
    The base default is not the defect -- inheriting it into a deployment
    was. A development run reaches the service on both spellings of the
    loopback, and that is what the base value is for.
    """

    def test_the_base_configuration_still_names_the_loopback(self, monkeypatch):
        monkeypatch.delenv("CORS_ORIGINS", raising=False)

        assert any(
            "localhost" in o or "127.0.0.1" in o
            for o in BaseConfig().CORS_ORIGINS
        )
