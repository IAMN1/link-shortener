"""
The shapes values take while crossing the application layer's own boundary.

A type belongs here when it is data and nothing else: it carries fields, it
knows how to be built from a domain entity or turned into a mapping, and it
decides nothing. Anything that makes a decision is a use case, a service or
a policy, and none of those live here.

Both directions, not only outwards. Most of these are what a use case hands
back, but ``CurrentUserInfo`` is what the web layer hands in, and the rule
is the same either way: the domain must not be passed across the boundary
raw, and the web layer's own schemas must not reach inside it.

``GetRecentLinksUseCase`` is the one that does not follow it -- it is
annotated ``List[Link]`` and hands the entities out. Its only caller is
``flask link recent``, which reads ``short_code.value`` and ``created_at``
off them to print a table, so nothing crosses an HTTP boundary; it is
stated here rather than left as a silent exception to a rule this file
states as absolute.

``Refusal`` is the member the rule admits least obviously. It never crosses
on its own -- it is carried inside a batch item -- but it is the same kind
of thing: a reason, in a shape the boundary can still translate, rather
than a finished sentence.
"""
