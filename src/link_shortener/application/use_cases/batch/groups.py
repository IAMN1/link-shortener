"""What a batch's input turns into once it has been read.

The grouper's output travelled through four components as a bare dict with
five string keys, and nothing checked any of them: declared ``List[Dict]``,
it reached mypy as ``Dict[Any, Any]``, so ``group["is_vaild"]`` passed both
gates in silence and failed at run time. Twenty-one such reads across five
files were held together by nothing but spelling.

Two types rather than one, because the dict was two records wearing one
shape: a valid group carried a hash and an address, an invalid one carried
``None`` in both and a refusal instead, and ``is_valid`` said which was
which. Splitting them retires the flag -- a ``UrlGroup`` has a hash the way
a ``RejectedUrl`` has a refusal, so nothing downstream asks first and
nothing downstream unwraps an ``Optional`` that was never empty.
"""

from dataclasses import dataclass, field
from typing import List

from link_shortener.application.dtos.refusal import Refusal
from link_shortener.domain import OriginalUrl, UrlHash


@dataclass
class UrlGroup:
    """The URLs of one batch that name the same address.

    One group becomes at most one link: the first URL is the one that gets
    created, and the rest come back marked as duplicates of it.

    Attributes:
        hash: The address's hash, which is what deduplication matches on.
        original_url: The address itself, validated.
        urls: The input strings that fell into this group, in input order.
    """

    hash: UrlHash
    original_url: OriginalUrl
    urls: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class RejectedUrl:
    """One URL the domain refused, and why.

    Attributes:
        url: The input string, echoed back to the caller as it arrived.
        refusal: Why it was refused, carried rather than worded -- the
            sentence is put into the reader's language at the boundary.
    """

    url: str
    refusal: Refusal
