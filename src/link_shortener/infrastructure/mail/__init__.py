"""
Turning a message into something a submission server accepts.

What goes in is the delivery and the rendering it needs: a mailer that
satisfies the port, and the templates a message is built from. Whether a
message is worth sending is decided by the use case that asks; whether
anything leaves the process at all is decided by a setting, and a
deployment that sends nothing gets a mailer that says so rather than one
that fails.
"""

from .null_mailer import NullMailer
from .smtp_mailer import SMTPMailer

__all__ = [
    'NullMailer',
    'SMTPMailer',
]
