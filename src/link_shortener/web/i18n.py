"""
Which language a request is answered in.

One function decides it -- ``select_language`` -- and everything that needs
the answer asks that function: Flask-Babel for the catalogue, the layout for
``<html lang>``, the error handler for the sentence it puts in ``message``.
A second implementation anywhere would be a second answer, and the two would
part company at exactly the request where it matters.

The order is: the cookie, then ``Accept-Language``, then the configured
default.

The cookie outranks the header because it is the only one of the two the
visitor chose on purpose. The header is what their browser was installed
with, and a visitor who picked a language from the menu has said something
the browser's default cannot overrule.

Nothing here is stored in the address. The cookie is the same mechanism the
theme and the collapsed sidebar already use: read by the server while the
page is being built, so the page arrives already in the right language.
State read from ``localStorage`` arrives after the first paint, and the page
visibly changes under the reader.
"""

from pathlib import Path
from typing import Dict, List, Optional

from babel import Locale, UnknownLocaleError
from flask import Flask, current_app, has_request_context, request
from flask_babel import Babel, gettext, pgettext

from link_shortener.domain.exceptions import DomainError

LANGUAGE_COOKIE_NAME = "lang"
"""Name of the cookie holding a deliberate choice of language.

Read here and written by the interface. Named as a constant rather than
spelled out at each site so that the reader and the writer cannot disagree
about it -- which is how the theme cookie is spelled in two places today.
"""


def supported_languages() -> List[str]:
    """
    Languages this deployment offers, normalised.

    Returns:
        Lower-cased language tags, best first. Empty entries are dropped:
        ``SUPPORTED_LANGUAGES=en,,ru`` is a typo, not a request for a
        language with no name.
    """
    configured = current_app.config.get("SUPPORTED_LANGUAGES") or []
    return [tag.strip().lower() for tag in configured if tag and tag.strip()]


def default_language() -> str:
    """
    Language for a caller who asked for none.

    Returns:
        The configured default, lower-cased.
    """
    return str(current_app.config.get("DEFAULT_LANGUAGE", "en")).strip().lower()


def language_from_cookie() -> Optional[str]:
    """
    The deliberate choice, if there is one and it is still on offer.

    A cookie naming a language this deployment does not have is ignored
    rather than refused. It is not a hostile input -- it is what a visitor
    is left holding after ``SUPPORTED_LANGUAGES`` is narrowed, or after they
    edited it by hand. Answering 400 to it would lock them out of the site
    with no way back that does not involve clearing cookies.

    Returns:
        The chosen language, or ``None`` when nothing usable was sent.
    """
    raw = request.cookies.get(LANGUAGE_COOKIE_NAME)
    if not raw:
        return None

    chosen = raw.strip().lower()
    return chosen if chosen in supported_languages() else None


def select_language() -> str:
    """
    Decide the language for the request being handled.

    Also the locale selector Flask-Babel is given, so the catalogue and the
    ``lang`` attribute can never name different languages.

    Outside a request -- the mail worker renders templates with no request
    anywhere near it -- there is nothing to negotiate with, and the default
    is the honest answer rather than a crash.

    Returns:
        A language tag from ``SUPPORTED_LANGUAGES``.
    """
    if not has_request_context():
        return default_language()

    chosen = language_from_cookie()
    if chosen:
        return chosen

    # Werkzeug matches a region against a bare tag on its own -- `ru-RU`
    # from a browser finds `ru` here -- and answers None for a language
    # that is not on offer and for a header it could not parse. Measured
    # against both, so none of that is reimplemented above.
    negotiated = request.accept_languages.best_match(supported_languages())
    return negotiated or default_language()


def translate_error(error: DomainError) -> str:
    """
    Put a domain refusal into the language of the request.

    The other side of ``domain.i18n.N_``: the domain marked the sentence
    and carried the values beside it, and this is the one place that turns
    the pair back into a sentence a person reads.

    A translation is a file an operator can edit, so it is treated as input
    rather than as code: a catalogue entry naming a placeholder the error
    does not carry -- ``%(short_code)s`` where the error says ``code`` --
    raises ``KeyError`` here, and this runs inside the error handler, on
    the path that answers 404 and 500. Failing here would answer a missing
    page with a crash, and the crash handler would call this again. The
    English sentence is a poor answer for a Russian reader and a far better
    one than that.

    Args:
        error: The refusal, carrying its template and its values.

    Returns:
        The sentence, translated where the catalogue had it and English
        where it did not.
    """
    translated = gettext(error.template)

    if not error.params:
        return translated

    try:
        return translated % error.params
    except (KeyError, TypeError, ValueError):
        return error.message


def language_name(tag: str) -> str:
    """
    What speakers of a language call it, in that language.

    Asked of Babel rather than kept in a table here. A table would be a
    second list of languages beside ``SUPPORTED_LANGUAGES``, and adding a
    language to one and not the other is the whole of how such a pair goes
    wrong -- silently, with the menu showing a bare tag.

    A tag Babel does not know is handed back as it came. That is a
    deployment naming a language nobody has a catalogue for, which is odd
    but not fatal, and a menu entry reading ``xx`` says more about what
    happened than a blank one.

    Args:
        tag: Language tag, e.g. ``ru``.

    Returns:
        The language's own name for itself, or the tag when Babel has no
        entry for it.
    """
    try:
        locale = Locale.parse(tag, sep="-")
    except (UnknownLocaleError, ValueError):
        return tag

    return locale.get_display_name(locale) or tag


def language_options() -> List[Dict[str, object]]:
    """
    Everything the language control needs to draw itself.

    Returns:
        One entry per offered language, in configured order, each carrying
        the tag, the short code the control shows, the language's own name
        for itself, and whether it is the one in force.
    """
    chosen = select_language()

    return [
        {
            "tag": tag,
            "code": tag.split("-")[0].upper(),
            "name": language_name(tag),
            "current": tag == chosen,
        }
        for tag in supported_languages()
    ]


def script_strings() -> Dict[str, str]:
    """
    The sentences the page scripts write onto a page after it has arrived.

    A script runs in the browser, long after ``gettext`` had its chance, so
    a string inside a ``.js`` file is in whatever language it was typed in
    and no catalogue can reach it. The strings therefore live here, are
    translated on the server while the page is being built, and travel to
    the browser inside the page as JSON.

    Here rather than in the templates because there is one list of them:
    ``layout/base.html`` prints whatever this returns, so adding a string
    is one edit and neither the layout nor the scripts hold a second copy
    of the list.

    Substitutions are named -- ``%(code)s``, not ``%s`` -- for the reason
    the domain's messages are: a translator moving a value to the other
    end of the sentence needs to know which value it is, and a positional
    marker does not say.

    The keys are the whole contract with the scripts, and it is a contract
    that breaks quietly: ``t()`` answers an unknown key with the key
    itself, so a rename here puts ``no_links_yet`` on the page where a
    sentence belongs. ``tests/unit/web/test_translations.py`` reads the
    keys from this function and the ``t('...')`` calls out of the scripts
    and fails on a key either side is missing.

    Returns:
        Key to translated sentence, in the language of the request.
    """
    return {
        "unreachable": gettext("The service could not be reached."),
        "request_failed": gettext("Request failed (%(status)s)"),
        "failed": gettext("Failed"),
        "login_failed": gettext("Login failed"),
        "registration_failed": gettext("Registration failed"),
        "confirmation_failed": gettext("Confirmation failed"),
        "could_not_send": gettext("Could not send"),
        "not_found": gettext("Not found"),
        "refused": gettext("Refused"),
        "type_address_first": gettext("Type the address first, then ask again."),
        "working": gettext("Working…"),
        "looking": gettext("Looking…"),
        "confirming": gettext("Confirming…"),
        "deleted": gettext("Deleted."),
        "confirm_delete_link": gettext("Delete link %(code)s?"),
        "confirm_delete_link_of_account": gettext(
            "Delete link %(code)s? It belongs to this account."
        ),
        "no_links": gettext("No links"),
        "no_links_yet": gettext("No links yet"),
        "no_links_visited": gettext("No links have been visited yet"),
        "never": gettext("never"),
        "results": gettext("Results"),
        "link": gettext("Link"),
        "extended": gettext("Extended"),
        # With a context, because English spells this the same as the
        # caption under a date and the two are not the same word anywhere
        # else. The column heading "Created" means *when*, and Chinese
        # already translates it 创建时间 -- "time of creation", which is
        # not what a card saying "this link has just been made" says.
        # `pgettext` is how gettext tells one msgid's two meanings apart;
        # sharing the entry would force one of the two to be wrong.
        "status_created": pgettext("a link that was just made", "Created"),
        "status_existing": pgettext("a link that already existed", "Existing"),
        "copy": gettext("Copy"),
        "delete": gettext("Delete"),
        "delete_this_link": gettext("Delete this link"),
        "delete_token_note": gettext("Only from this page, and only now."),
        "traffic_withheld": gettext(
            "This link's traffic is shown to whoever made it."
        ),
        "stat_clicks": gettext("Clicks"),
        # No context on this one, deliberately: it is the same caption the
        # tables already use for the date a link was made, and it should
        # keep sharing their entry rather than start a second one that a
        # translator has to keep in step by hand.
        "stat_created": gettext("Created"),
        "stat_last_access": gettext("Last Access"),
        "stat_never": gettext("Never"),
        "stat_days_old": gettext("Days Old"),
        "stat_clicks_per_day": gettext("Clicks/Day"),
        "popular": gettext("Popular"),
        "recent": gettext("Recent"),
        # The charts. `charts.js` draws every one of these after the page
        # has arrived, so none of them can come from a template.
        "chart_total": gettext("Total"),
        "chart_humans": gettext("People"),
        "chart_bots": gettext("Robots"),
        "chart_no_visits": gettext("No visits in this span"),
        "chart_no_visits_hint": gettext("Try a wider span"),
        "chart_failed": gettext("The figures could not be loaded"),
        # What the smaller categories are collapsed into when a ring runs
        # out of colours. Its own entry rather than the existing "other"
        # anything, because this one is a row in a legend and has to read
        # as a group of things.
        "chart_other": gettext("Others"),
        # Both faces of one control, named for where it goes rather than
        # for what is on screen.
        "chart_show_bars": gettext("As bars"),
        "chart_show_ring": gettext("As a ring"),
        # How fresh the figures are. Abbreviated units, which is why there
        # is no plural machinery here: "5 s" and "1 s" are spelled the same
        # in all three catalogues, and a translator who needs the full word
        # can write it -- the substitution carries the number either way.
        "chart_updated_now": gettext("updated just now"),
        "chart_updated_seconds": gettext("updated %(count)s s ago"),
        "chart_updated_minutes": gettext("updated %(count)s min ago"),
        "chart_every": gettext("every %(interval)s"),
        "chart_polling_off": gettext("auto-refresh off"),
        # The way from the table of links to one link's own page. Drawn by
        # `my_links.js` per row, so it cannot come from the template.
        "chart_link_stats": gettext("Stats"),
        # The journal viewer. It reuses the freshness sentences above
        # rather than starting a second set: "updated 40 s ago" is the same
        # sentence about the same kind of reading, and two entries would be
        # two things for a translator to keep in step.
        "journal_empty": gettext("Nothing has been written to this journal"),
        "journal_failed": gettext("The journal could not be read"),
        # Marks a line that is not a record: a write torn by rotation, or
        # something a library printed itself. It is shown as it was found
        # rather than dropped, and this says which.
        "journal_unparsed": gettext("not a record"),
        # Written as a label with a colon rather than as a sentence, and
        # that is a grammar decision rather than a stylistic one. "1 lines
        # from error.log" is wrong in English and "1 строк" is wrong in
        # Russian, which needs three plural forms; the count reaches the
        # page in the browser, where `ngettext` cannot follow it. A label
        # takes a number of any size in all three languages.
        "journal_lines_read": gettext("Lines: %(count)s · %(files)s"),
        # Said instead of `journal_empty` when a search matched nothing:
        # "nothing has been written to this journal" is a different fact,
        # and the wrong one to leave a reader with after they searched.
        "journal_no_matches": gettext("Nothing here matched that search"),
        # A label with a colon for the reason `journal_lines_read` is one:
        # both numbers reach the page in the browser, where `ngettext`
        # cannot follow them, and Russian needs three forms for each.
        "journal_found": gettext("Found: %(found)s · scanned: %(scanned)s"),
        # Said when the search stopped because its window ran out rather
        # than because the journal did. Without it, "nothing found" reads
        # as "this never happened" when it means "not in what was read".
        "journal_window_ended": gettext(
            "Not searched further back than this."
        ),
        "journal_begins": gettext("This is the start of the journal."),
        "journal_more": gettext("Older lines exist."),
        "journal_archives_reach": gettext(
            "Archives reach back to %(name)s."
        ),
        # The security counters under the journal viewer. Three series and
        # everything else summed, because fourteen event types would be
        # fourteen colours nobody can tell apart.
        "counts_signed_in": gettext("Signed in"),
        "counts_refused": gettext("Refused"),
        "counts_roles": gettext("Roles changed"),
        "counts_other": gettext("Other events"),
        # A label with a colon rather than a sentence, for the reason
        # `journal_lines_read` is one: the dates reach the page in the
        # browser, and a sentence around them would need agreement no
        # `gettext` call here can see.
        "counts_span": gettext("Counted: %(since)s — %(until)s"),
        "counts_chart_label": gettext("Security events over time"),
        "counts_failed": gettext("The counters could not be read"),
        "answering": gettext("answering"),
        "not_answering": gettext("not answering"),
        "unknown": gettext("unknown"),
    }


def init_babel(app: Flask) -> Babel:
    """
    Wire Flask-Babel to the selector above and expose it to templates.

    Args:
        app: The application to register on.

    Returns:
        The Babel extension, held by the caller only so that a test can
        reach it; the application does not need it afterwards.
    """
    # Named rather than left to the default. The default is resolved from
    # the application's root path, so it follows this package around
    # silently -- and the catalogues have to be somewhere `package-data`
    # ships them from, which is a decision that should be written down
    # rather than inferred.
    app.config.setdefault(
        "BABEL_TRANSLATION_DIRECTORIES",
        str(Path(__file__).resolve().parent / "translations"),
    )

    babel = Babel(
        app,
        locale_selector=select_language,
        default_locale=str(app.config.get("DEFAULT_LANGUAGE", "en")),
    )

    @app.context_processor
    def inject_language():
        """Give the layout the same answer the catalogue was chosen by."""
        return {
            "current_language": select_language(),
            "supported_languages": supported_languages(),
            "language_options": language_options,
            "language_cookie_name": LANGUAGE_COOKIE_NAME,
            # The function, not its result. A context processor runs for
            # every render, and most of them are not a page -- an included
            # fragment, a mail body. Translating forty-odd sentences to
            # hand them to a template that never asks is work done for
            # nothing; called from the layout, it happens where it is used.
            "script_strings": script_strings,
        }

    return babel
