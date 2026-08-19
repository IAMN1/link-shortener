from pathlib import Path
from typing import Optional, Tuple

from babel.support import NullTranslations, Translations
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from link_shortener.application.ports.mail_templates import MailTemplates


TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "web" / "templates" / "email"
"""Where the message templates live.

Counted inside the package rather than up to a project root, and the
difference matters: the image installs the package into ``site-packages``
and the project tree is not there at all. This walk only ever crosses
directories the package itself owns, so it resolves the same in both
places -- provided the files are shipped, which is what the
``web/templates/**/*.txt`` line in ``pyproject.toml`` is for.
"""

CATALOGUE_DIR = Path(__file__).resolve().parents[2] / "web" / "translations"
"""The same catalogues the pages are drawn from.

One set of files, not a second set for mail. A message and the page it
links to are the same voice, and two catalogues would let them drift --
and would ask a translator to translate "Confirm your email address"
twice, in two files, with no way to see that they are the same sentence.
"""


class JinjaMailTemplates(MailTemplates):
    """
    Renders outgoing messages from templates on disk.

    Plain text, and the environment says so by leaving autoescaping off.
    Turning it on would be the safe-looking choice and the wrong one here:
    HTML escaping inside a text/plain body corrupts the very thing the
    message exists to carry, turning an ``&`` in a URL into ``&amp;`` and
    an apostrophe into ``&#39;``.

    Attributes:
        environment: The environment for the default language. One is kept
            per language, because a catalogue is installed on an
            environment rather than passed to a render -- see
            ``_environment``.
    """

    def __init__(
        self,
        template_dir: Path = TEMPLATE_DIR,
        catalogue_dir: Path = CATALOGUE_DIR,
        default_language: str = "en",
    ):
        """
        Args:
            template_dir: Directory holding the message templates.
            catalogue_dir: Directory holding the compiled catalogues.
            default_language: Language for a message nobody chose one for
                -- a task queued by the CLI, or a context from before this
                field existed.
        """
        self.catalogue_dir = catalogue_dir
        self.default_language = default_language
        self.template_dir = template_dir
        self._catalogues: dict = {}
        self._environments: dict = {}
        self.environment = self._environment(default_language)

    def _build_environment(self) -> Environment:
        """
        One Jinja environment, configured but with no catalogue installed.

        Returns:
            A fresh environment reading from ``template_dir``.
        """
        return Environment(
            # The messages are translated like the pages, and a plain
            # environment has no `{% trans %}` at all -- an untranslated
            # template renders, and one carrying the tag raises
            # TemplateSyntaxError at send time, inside a worker.
            extensions=["jinja2.ext.i18n"],
            loader=FileSystemLoader(str(self.template_dir)),
            # A text/plain body: escaping would break the link the message
            # exists to carry. See the class docstring.
            autoescape=False,  # nosec B701
            # A missing variable renders as an empty string by default,
            # which for these templates means mailing somebody a message
            # with a blank where the link should be. Raising instead turns
            # that into a failure the logs can show.
            undefined=StrictUndefined,
            keep_trailing_newline=True,
        )

    def _environment(self, language: Optional[str]) -> Environment:
        """
        The environment whose catalogue is the one this language needs.

        One per language, built once and never reconfigured after that.
        The alternative -- installing the catalogue on a shared
        environment before each render -- is what this replaces, and it
        was a race rather than a style: ``install_gettext_translations``
        writes ``gettext`` into ``Environment.globals``, an overlay shares
        that dictionary rather than copying it, and with
        ``CELERY_ENABLED=false`` the message goes out on the request
        thread. Two registrations in different languages then interleave
        install and render, and one message leaves with the other's
        catalogue -- measured with two threads of 300 renders each, and
        the subject and the body of one message can disagree.

        The environment is put in the map only once its catalogue is
        installed, so a second thread finding it there finds it ready.
        Two threads racing to build the same one build two and each uses
        the one it built, which costs a parse and is otherwise the same
        answer.

        Args:
            language: Language tag, or ``None`` for the default.

        Returns:
            The environment for that language.
        """
        tag = (language or self.default_language).strip().lower()

        environment = self._environments.get(tag)
        if environment is None:
            environment = self._build_environment()
            environment.install_gettext_translations(  # type: ignore[attr-defined]
                self._catalogue(tag), newstyle=True
            )
            self._environments[tag] = environment

        return environment

    def _catalogue(self, language: Optional[str]):
        """
        Load the catalogue a message is rendered through, once per language.

        Args:
            language: Language tag, or ``None`` for the default.

        Returns:
            The translations object. ``NullTranslations`` when there is no
            catalogue for that language -- which is the right answer for
            English, whose msgids are the English text, and a survivable
            one for a deployment offering a language nobody compiled: the
            message goes out in English rather than not going out.
        """
        tag = (language or self.default_language).strip().lower()

        if tag not in self._catalogues:
            found = Translations.load(str(self.catalogue_dir), [tag])
            self._catalogues[tag] = found or NullTranslations()

        return self._catalogues[tag]

    def _render(self, name: str, language: Optional[str], **context) -> str:
        """
        Render one template with the catalogue for this language installed.

        Args:
            name: Template file name.
            language: Language tag, or ``None`` for the default.
            **context: What the template needs.

        Returns:
            The rendered text.
        """
        # The language picks the environment; nothing is installed here.
        # One worker process sends to people who chose different
        # languages, and a single environment reconfigured per render
        # cannot hold two of them at once. See `_environment`.
        return self._environment(language).get_template(name).render(**context)

    def verification_email(
        self,
        confirm_url: str,
        ttl_hours: int,
        language: Optional[str] = None,
    ) -> Tuple[str, str]:
        """
        Render the message that carries a confirmation link.

        Args:
            confirm_url: Absolute URL that confirms the address.
            ttl_hours: How long that URL stays usable.
            language: Language tag chosen by the request that asked for
                this message.

        Returns:
            Tuple of (subject, body), both plain text. The subject is
            stripped of its trailing newline, because a header cannot
            carry one -- ``EmailMessage`` refuses the whole message if it
            does, and that refusal would arrive as a failed registration
            rather than as the template mistake it is.
        """
        subject = self._render("verification_subject.txt", language)
        body = self._render(
            "verification_body.txt",
            language,
            confirm_url=confirm_url,
            ttl_hours=ttl_hours,
        )
        return subject.strip(), body

    def account_exists_email(
        self, sign_in_url: str, language: Optional[str] = None
    ) -> Tuple[str, str]:
        """
        Render the message sent when the address is already registered.

        Args:
            sign_in_url: Absolute URL of the sign-in page.
            language: Language tag chosen by the request that asked for
                this message.

        Returns:
            Tuple of (subject, body), both plain text. The subject is
            stripped for the same reason as above.
        """
        subject = self._render("account_exists_subject.txt", language)
        body = self._render(
            "account_exists_body.txt", language, sign_in_url=sign_in_url
        )
        return subject.strip(), body
