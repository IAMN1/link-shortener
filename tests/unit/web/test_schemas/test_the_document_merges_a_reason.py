"""
Folding "and it can also answer this" into a response already declared.

``_merge_response`` has four cases and the hand-written table reaches two
of them: as ``PATHS`` stands, every response the merge sees either
declares nothing at all or declares a description that does not already
spell the reason out. The other two are branches a table entry decides,
and an entry is one line of hand-written YAML-shaped Python away.

They are held here rather than by planting entries in ``PATHS``: the
merge is a pure function of what it is handed, and building a document
around a planted entry would test the table instead of the merge.

The property that matters in all four is the same one
``test_the_document_does_not_share_one_header_object_with_itself``
holds for the whole document: what comes back is never the object that
went in. The caller writes ``headers`` onto the result, and ``PATHS`` is
a module-level constant -- a result that is the declared object is a
document that grows a header every time one is built.
"""

from link_shortener.web.schemas.openapi import _merge_response


REASON = "the throttle refused it"


class TestAResponseThatDeclaresNothingYet:

    def test_an_operation_with_no_such_response_gets_the_error_shape(self):
        merged = _merge_response(None, REASON)

        assert merged["description"] == "The throttle refused it"
        assert "content" in merged, merged

    def test_a_response_with_no_description_gets_the_reason_as_one(self):
        declared = {
            "content": {"text/csv": {"schema": {"type": "string"}}},
        }

        merged = _merge_response(declared, REASON)

        assert merged["description"] == "The throttle refused it"

    def test_what_it_already_carried_is_carried_through(self):
        """The reason the merge exists rather than a rebuild: a response
        can carry a content type that is not JSON, and rebuilding it
        through ``_error`` replaced that with the error shape."""
        declared = {
            "content": {"text/csv": {"schema": {"type": "string"}}},
        }

        merged = _merge_response(declared, REASON)

        assert merged["content"] == declared["content"]

    def test_the_declared_object_is_not_the_one_handed_back(self):
        declared = {"content": {"text/csv": {"schema": {"type": "string"}}}}

        merged = _merge_response(declared, REASON)
        merged["headers"] = {"Retry-After": {}}

        assert "headers" not in declared
        assert "description" not in declared


class TestAResponseThatAlreadySaysIt:

    def test_a_description_that_spells_the_reason_out_is_left_alone(self):
        declared = {"description": f"Refused because {REASON}."}

        merged = _merge_response(declared, REASON)

        assert merged["description"] == declared["description"]

    def test_it_is_still_a_copy(self):
        """The branch that returns "unchanged" is the one where handing
        back the declared object is most tempting -- and the caller writes
        into what it gets."""
        declared = {"description": f"Refused because {REASON}."}

        merged = _merge_response(declared, REASON)
        merged["headers"] = {"Retry-After": {}}

        assert "headers" not in declared


class TestAResponseThatSaysSomethingElse:

    def test_the_reason_is_appended_to_what_was_there(self):
        declared = {"description": "The link was not found"}

        merged = _merge_response(declared, REASON)

        assert merged["description"] == (
            f"The link was not found; or {REASON}"
        )

    def test_the_declared_object_is_untouched(self):
        declared = {"description": "The link was not found"}

        _merge_response(declared, REASON)

        assert declared["description"] == "The link was not found"


class TestTheSentenceIsCapitalisedOnce:
    """The reason arrives lower-case, because it is also used mid-sentence."""

    def test_a_reason_standing_alone_starts_with_a_capital(self):
        assert _merge_response(None, REASON)["description"][0] == "T"

    def test_a_reason_appended_to_a_sentence_does_not(self):
        merged = _merge_response({"description": "Not found"}, REASON)

        assert merged["description"].endswith(REASON)
