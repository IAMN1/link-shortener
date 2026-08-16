"""
Marking a sentence for translation without translating it here.

The domain says what went wrong; it does not know who is asking or in what
language, and it must not learn -- importing Flask-Babel here would make
the innermost layer depend on the web framework, and would break the
worker and the CLI, which raise these same errors with no request anywhere
near them.

So the domain marks and the boundary translates. ``N_`` returns its
argument unchanged: at runtime nothing happens at all. What it does is
make the sentence visible to ``pybabel extract``, which scans for calls by
name -- and ``N_`` is one of the names it already knows, so no extraction
flag has to be remembered for this to work.

The sentence a marked error carries is still English, and that is what the
logs keep. Translation happens once, in ``web.i18n.translate_error``, at
the point where the request -- and therefore the reader -- is known.

Sentences with a value in them are marked as a template with a named
placeholder rather than built by an f-string::

    raise LinkNotFoundError(short_code)   # template: "Link with code (%(code)s) not found"

An f-string is finished before anyone can translate it: by the time the
boundary sees ``"Link with code (abc123) not found"`` there is no catalogue
entry with that text in it, ``gettext`` hands the string straight back, and
the page renders in English with nothing anywhere reporting a fault.

Named placeholders rather than positional ones, because a translator moves
them: Russian and Chinese both put the code in a different place in the
sentence, and ``%s`` cannot be moved past another ``%s``.
"""


def N_(message: str) -> str:
    """
    Mark a sentence as translatable and return it unchanged.

    Args:
        message: English sentence, the msgid it will be looked up by.

    Returns:
        The same string, untouched.
    """
    return message
