"""An example in the document is read before anything else in it.

A schema's `example` is what a reader copies, what a generated client
sends, and what a page is built against before any real answer arrives.
An example that contradicts its own model is therefore worse than none:
it is wrong in the one place nobody thinks to check, and no request ever
made will disagree with it.

Two were. `SecurityCountsResponse` opens by saying every series has the
same number of buckets, and published `buckets: 28` beside series of
three. `ExtendedLinkInfoResponse` published a `deletion_token` field the
model does not have, copied from `ShortLinkResponse` next to it.
"""

from link_shortener.application.utils.chart_spans import PERIODS
from link_shortener.web.schemas.link import (
    ExtendedLinkInfoResponse, ShortLinkResponse,
)
from link_shortener.web.schemas.security import SecurityCountsResponse


def example_of(model) -> dict:
    """The example a model publishes, out of its own config."""
    return model.model_config["json_schema_extra"]["example"]


class TestTheSecurityCountsExampleKeepsItsOwnInvariant:

    def test_every_series_is_as_long_as_the_bucket_count(self):
        """The invariant the module opens with, asked of its own example:
        a page sizes its axis from `buckets` and reads `series`, so two
        different lengths there are two different charts."""
        example = example_of(SecurityCountsResponse)

        for name, series in example["series"].items():
            assert len(series) == example["buckets"], name

    def test_the_bucket_count_is_the_one_that_span_really_has(self):
        """`buckets` is not free: the period decides it."""
        example = example_of(SecurityCountsResponse)

        assert example["period"] in PERIODS
        assert example["buckets"] == PERIODS[example["period"]][1]

    def test_each_total_is_its_series_added_up(self):
        """The figures beside the chart and the chart itself come from one
        answer, which is the whole reason they are read together."""
        example = example_of(SecurityCountsResponse)

        for name, series in example["series"].items():
            assert sum(series) == example["totals"][name], name


class TestAnExampleNamesNoFieldItsModelLacks:

    def test_every_example_key_is_a_field_of_its_model(self):
        """`ExtendedLinkInfoResponse` published `deletion_token`, which
        only its neighbour has: a copied example, and a field a client
        built from the document would look for and never receive."""
        for model in (
            ShortLinkResponse, ExtendedLinkInfoResponse,
            SecurityCountsResponse,
        ):
            stray = set(example_of(model)) - set(model.model_fields)
            assert stray == set(), f"{model.__name__}: {stray}"
