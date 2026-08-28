"""
Reading a figure: counting, never changing.

Totals for the service, an account's own activity, the visits behind the
charts, the state of the dependencies. Nothing here writes, and nothing here
decides anything about a link or an account -- which is what separates a
figure on a dashboard from the act it describes.

What an auditor reads is not here but in ``use_cases/security``, and the
line is who may read it: nothing in this directory answers to
``audit:view``. The permissions here are the ordinary ones a reader already
holds for what the figure is about -- its own links, the service's totals,
the health an operator watches.
"""
