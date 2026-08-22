from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from link_shortener.domain import DomainError


@dataclass(frozen=True)
class Refusal:
    """Why one item of a batch was not done, in a form the boundary can read.

    A batch answers 200 with a verdict per item, so a refusal here is not
    raised -- it is carried, alongside the items that succeeded. Carried as
    a finished sentence, it arrived at the boundary with nothing to look up:
    ``str(error)`` is English by the time anybody could translate it, and
    the batch endpoint answered a Russian reader in English while the
    single-link endpoint beside it, refusing the very same URL for the very
    same reason, answered in Russian.

    So this carries what a ``DomainError`` carries -- the code, the English
    sentence, the msgid and the values -- and ``web.i18n.translate_error``
    reads either. The English ``message`` stays because the CLI and
    ``application.log`` have no reader to negotiate a language with, which
    is the reason the domain keeps one too.

    Attributes:
        code: Machine-readable reason, the same vocabulary the error
            envelope uses.
        message: The sentence in English.
        template: The msgid the boundary looks the sentence up by.
        params: What the placeholders in the template stand for.
        retry_after_seconds: When the refusal clears, for the refusals that
            do. A raised one says this in a ``Retry-After`` header, which a
            200 has no way of carrying: a batch that spent the guest's
            allowance halfway through refused the rest of the items and
            told nobody it was a refusal that clears in a day -- while the
            very same refusal, raised for the whole batch, said so. A
            header cannot say it per item, so the item says it.
    """

    code: str
    message: str
    template: str
    params: Dict[str, Any] = field(default_factory=dict)
    retry_after_seconds: Optional[int] = None

    @classmethod
    def from_error(cls, error: DomainError) -> "Refusal":
        """
        Carry a domain refusal without flattening it into a sentence.

        Args:
            error: The refusal the domain raised.

        Returns:
            The same refusal, in a shape a DTO may hold.
        """
        return cls(
            code=error.code,
            message=error.message,
            template=error.template,
            params=dict(error.params),
            # Read the way the error handler reads it off a raised one, so
            # the two answers cannot disagree about how long to wait.
            retry_after_seconds=getattr(error, "retry_after_seconds", None),
        )

    @classmethod
    def of(cls, message: str, code: str = "DOMAIN_ERROR", **params: Any) -> "Refusal":
        """
        Build a refusal the application itself words.

        For the one case that is not a domain rule: the service failed to
        store something. The sentence is marked with ``N_`` at the call
        site, so it is a msgid like any other.

        Args:
            message: The marked sentence, which is also the msgid.
            code: Machine-readable reason.
            **params: Values the sentence names.

        Returns:
            A refusal carrying its own msgid.
        """
        return cls(code=code, message=message % params if params else message,
                   template=message, params=dict(params))
