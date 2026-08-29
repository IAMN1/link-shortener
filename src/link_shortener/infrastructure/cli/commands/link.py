from typing import List, Optional

from link_shortener.application import (
    RequestContext, DeleteLinkUseCase,
    GetLinkInfoUseCase, GetRecentLinksUseCase, ShortLinkResponse
)
from link_shortener.application.use_cases.links.create_short_link import CreateShortLinkUseCase

from link_shortener.domain import Link, LinkNotFoundError


def create_link(
    use_case: CreateShortLinkUseCase, url: str, context: RequestContext, code: Optional[str] = None
) -> ShortLinkResponse:
    """
    Create a new short link.

    Args:
        use_case: CreateShortLinkUseCase instance.
        url: The original URL to shorten.
        context: Request context.
        code: Optional custom short code.

    Returns:
        The created link as the use case describes it.

    Raises:
        ValidationError: If the URL or the chosen code is invalid.
        LinkCodeTakenError: If the chosen code is already in use.
    """
    return use_case.execute(url, context, ttl_seconds=0, custom_code=code)


def delete_link(
    use_case: DeleteLinkUseCase, short_code: str, context: RequestContext
) -> bool:
    """
    Delete a short link by its code.

    Ownership is not enforced: the CLI runs as an operator with direct
    access to the database and the configuration, so a permission check
    here would guard nothing that ``psql`` does not already open.

    Args:
        use_case: DeleteLinkUseCase instance.
        short_code: The short code string.
        context: Request context.

    Returns:
        True if deletion was successful, False if link not found or invalid.
    """
    return use_case.execute(short_code, context, enforce_ownership=False)

def get_link_info(
    use_case: GetLinkInfoUseCase, short_code: str, context: RequestContext
) -> Optional[ShortLinkResponse]:
    """
    Retrieve basic information about a short link.

    Args:
        use_case: GetLinkInfoUseCase instance.
        short_code: The short code string.
        context: Request context.

    Returns:
        The use case's own response, or ``None`` when no link carries that
        code -- a code the format rules refuse included. Handed back whole
        rather than flattened into a dictionary: the fields are already
        named and typed, and copying them into strings only moves the
        names somewhere a checker cannot see them.

    Raises:
        LinkExpiredError: If a link carries the code but its lifetime is
            over. Deliberately not flattened into ``None``: that value
            already says "no link carries this code", and an expired link
            is one the caller can still list and still delete. The caller
            answers for it -- ``link info`` says so and exits 1, the way
            the redirect and the API answer 410 rather than 404.
    """
    # One refusal turned into a value, because only one of the two the use
    # case raises means "there is nothing here": ``_code_to_look_up``
    # answers ``LinkNotFoundError`` for a malformed code as well as for an
    # unused one, and says so in its own docstring -- "a malformed code
    # raises no ValueError here".
    #
    # There was a second clause catching ``ValueError`` beneath this one.
    # It could not run: ``ShortCode`` refuses a bad code with
    # ``ValidationError``, which descends from ``DomainError`` and not
    # from ``ValueError`` -- and the use case does not let it out anyway.
    # What it did instead was tell the next reader that this call can fail
    # in a way it cannot.
    try:
        return use_case.execute(short_code, context)
    except LinkNotFoundError:
        return None

def list_links(
    use_case: GetRecentLinksUseCase, limit: int, context: RequestContext
) -> List[Link]:
    """
    Return a list of the most recently created links.

    Args:
        use_case: GetRecentLinksUseCase instance.
        limit: Maximum number of links to return.
        context: Request context.

    Returns:
        The links themselves, newest first. Not flattened into
        dictionaries: the caller prints two fields of each, and turning
        entities into strings here would put the value objects' own
        formatting into this module.
    """
    return use_case.execute(limit, context)
