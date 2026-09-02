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


class TestTheBuiltDocumentSaysEachReasonOnce:
    """
    The guard above is exact-substring, and the table is written by hand.

    Six operations declared a 415 of their own worded ``"A body that is
    not declared application/json"`` while the fold writes ``"a body that
    is not declared as JSON"`` -- different words for one reason, so the
    guard missed and the published description read *"A body that is not
    declared application/json; or a body that is not declared as JSON"*.
    That is exactly the stutter ``_merge_response`` exists to prevent,
    arriving through the wording rather than through the logic, and no
    test of the built document could see it because none read one.
    """

    def test_every_415_says_it_once(self):
        """
        415 has exactly one reason in this document -- the folded one --
        so a description carrying "; or" there is that reason said twice.
        The 400 beside it legitimately joins two: a hand-written sentence
        about *this* operation's body and the folded one about undeclared
        input, which are different facts.
        """
        from link_shortener.web.schemas.openapi import build_openapi

        doubled = []
        for path, operations in build_openapi("https://x.test")["paths"].items():
            for method, operation in operations.items():
                if not isinstance(operation, dict):
                    continue
                said = operation.get("responses", {}).get("415", {})
                said = said.get("description", "")
                if "; or" in said:
                    doubled.append((method.upper(), path, said))

        assert doubled == [], doubled


class TestAnOperationIsNotPromisedARefusalItCannotMake:
    """
    ``/auth/refresh`` and ``/auth/logout`` read their body through
    ``optional_json_object``, which answers ``{}`` for a request that is
    not offered as JSON rather than refusing it. The 415 was folded in on
    "does this operation have a request body", which is a different
    question -- so the document promised both a refusal neither can make.
    """

    def test_the_two_lenient_operations_declare_no_415(self):
        from link_shortener.web.schemas.openapi import build_openapi

        paths = build_openapi("https://x.test")["paths"]

        for path in ("/api/v1/auth/refresh", "/api/v1/auth/logout"):
            operation = paths[path]["post"]
            assert "requestBody" in operation, path
            assert "415" not in operation["responses"], path

    def test_a_strict_operation_still_declares_one(self):
        """The other half: the fold must not have been switched off."""
        from link_shortener.web.schemas.openapi import build_openapi

        paths = build_openapi("https://x.test")["paths"]

        assert "415" in paths["/api/v1/shorten"]["post"]["responses"]
        assert "415" in paths["/api/v1/auth/verify"]["post"]["responses"]
