"""``GET /api/v1/links/<code>/qr`` over the assembled application.

The renderer is held on its own in
``tests/unit/web/test_the_square_encodes_the_short_address.py``. What is
held here is the wiring around it: that the code is resolved before an
image is drawn, that the address drawn is the one the API itself hands out,
and that the answer is an image rather than the service's JSON envelope.

The resolution matters more than it looks. Drawing first and asking later
would answer a square for a code that leads nowhere -- valid, scannable,
and pointing at a 404 the moment somebody prints it.
"""

import re


def a_link(client) -> dict:
    """
    Create a link anonymously and return the creation response.

    Args:
        client: Test client.

    Returns:
        The parsed body, which carries ``short_code`` and ``short_url``.
    """
    answer = client.post(
        "/api/v1/shorten",
        json={"url": "https://example.com/a-destination-worth-printing"},
    )
    assert answer.status_code in (200, 201), answer.get_data(as_text=True)
    return answer.get_json()


class TestItAnswersAnImage:
    """The shape of a successful answer."""

    def test_it_is_svg(self, client):
        link = a_link(client)

        answer = client.get(f"/api/v1/links/{link['short_code']}/qr")

        assert answer.status_code == 200
        assert answer.mimetype == "image/svg+xml"

    def test_the_body_is_an_svg_document(self, client):
        link = a_link(client)

        body = client.get(
            f"/api/v1/links/{link['short_code']}/qr"
        ).get_data(as_text=True)

        assert body.startswith("<svg ")

    def test_it_is_not_the_json_envelope(self, client):
        """Every other route on this blueprint answers JSON; this one must not."""
        link = a_link(client)

        answer = client.get(f"/api/v1/links/{link['short_code']}/qr")

        assert not answer.is_json

    def test_the_title_names_the_code(self, client):
        """What a screen reader announces, and what a hover shows."""
        link = a_link(client)

        body = client.get(
            f"/api/v1/links/{link['short_code']}/qr"
        ).get_data(as_text=True)

        assert f"<title>{link['short_code']}</title>" in body


class TestTheAddressDrawnIsTheAddressHandedOut:
    """The one decision the whole feature rests on."""

    def test_the_square_is_the_one_for_the_short_url(self, client):
        """Rendered independently from the API's own ``short_url``.

        If the view ever assembled the address itself, or reached for the
        destination, the two documents would differ and this fails. It is
        the only check that can tell those apart -- both would be valid
        images.
        """
        from link_shortener.web.qr import render_svg

        link = a_link(client)

        served = client.get(
            f"/api/v1/links/{link['short_code']}/qr"
        ).get_data()

        assert served == render_svg(
            link["short_url"], title=link["short_code"]
        )

    def test_the_destination_is_nowhere_in_the_document(self, client):
        """A square carrying the destination bypasses the link entirely.

        The path is not in the SVG as text either way -- a QR code is a
        drawing, not a string -- so this is checked against the rendered
        alternative rather than by searching the bytes.
        """
        from link_shortener.web.qr import render_svg

        link = a_link(client)

        served = client.get(
            f"/api/v1/links/{link['short_code']}/qr"
        ).get_data()

        assert served != render_svg(
            "https://example.com/a-destination-worth-printing",
            title=link["short_code"],
        )


class TestACodeThatLeadsNowhere:
    """What is answered before anything is drawn."""

    def test_an_unknown_code_is_a_404(self, client):
        answer = client.get("/api/v1/links/nosuchcode/qr")

        assert answer.status_code == 404

    def test_the_refusal_is_the_services_own_envelope(self, client):
        """The image mimetype must not be claimed for a refusal."""
        answer = client.get("/api/v1/links/nosuchcode/qr")

        assert answer.is_json
        assert answer.get_json()["error"] == "LINK_NOT_FOUND"


class TestItMayBeCachedByAnybody:
    """Why this route's caching differs from its neighbours'."""

    def test_the_answer_is_publicly_cacheable(self, client):
        """Nothing about the caller is in the image.

        The two endpoints beside it withhold fields depending on who is
        asking, so their answers are private. This one has no such field,
        which is what makes a shared cache correct rather than merely
        convenient.
        """
        link = a_link(client)

        answer = client.get(f"/api/v1/links/{link['short_code']}/qr")

        assert "public" in answer.headers.get("Cache-Control", "")

    def test_it_is_not_cached_for_ever(self, client):
        """``BASE_URL`` moves when a deployment is renamed."""
        link = a_link(client)

        answer = client.get(f"/api/v1/links/{link['short_code']}/qr")
        age = re.search(r"max-age=(\d+)", answer.headers["Cache-Control"])

        assert age and 0 < int(age.group(1)) <= 86400
