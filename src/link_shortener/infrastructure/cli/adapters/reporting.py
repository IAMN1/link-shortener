"""
One door for the refusals a command can raise.

Most commands here catch what they can go wrong with and print a sentence:
``Failed to create user: Password must be at least 8 characters``, exit 1.
Two did not, and an operator met a Python traceback instead --

    flask security reset-password --email x@example.com --password 12
      ... fourteen frames ...
      link_shortener.domain.exceptions.ValidationError: Password must be
      at least 8 characters

    flask db load-custom-roles /tmp/roles.yaml
      ... frames ...
      yaml.scanner.ScannerError: mapping values are not allowed here

-- for the same class of mistake the command beside them words as a
sentence. Neither reached any journal either: ``grep -c`` for both
messages answered 0 in ``error.log``, ``application.log`` and
``audit.log``, while ordinary refusals from inside a use case land in
``error.log`` as usual. So a failed command was visible only to whoever
was standing at the terminal.

Written as a group class rather than as a decorator on the two commands
that were found. A decorator is a thing to remember; the next command
that raises a domain error would arrive without it, and the same defect
would come back under a different name. Every group in this CLI is built
on this one, so a command cannot be added outside it.

What is deliberately *not* caught is everything else. A ``KeyError`` or a
broken socket is a defect in this service, and its traceback is the
report -- turning those into a tidy sentence would hide the one thing
worth seeing.
"""

import click
import yaml

from link_shortener.domain.exceptions import DomainError


REFUSALS = (DomainError, yaml.YAMLError)
"""What a command may raise that is the operator's business, not a bug.

``DomainError`` is this service saying no -- a password too short, a role
name that is not a name, a code already taken. ``yaml.YAMLError`` is the
file the operator pointed at being malformed, which is the same kind of
fact about their input and arrives from a library that cannot raise ours.
"""


class ReportingGroup(click.Group):
    """
    A command group whose refusals arrive as sentences.

    Attributes:
        The same as ``click.Group``; nothing is added.
    """

    def invoke(self, ctx: click.Context):
        """
        Run the command, and word a refusal instead of raising it.

        Args:
            ctx: The Click context for this invocation.

        Returns:
            Whatever the command returned.

        Raises:
            SystemExit: With code 1 when the command refused. Anything
                else the command raises is left alone.
        """
        try:
            return super().invoke(ctx)
        except REFUSALS as refusal:
            click.echo(f"\n{refusal}", err=True)
            raise SystemExit(1) from refusal
