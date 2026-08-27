"""
The service, in four layers named after what each is allowed to know.

``domain`` holds the rules and knows nothing else. ``application`` puts
them in order as use cases and declares the ports it needs.
``infrastructure`` implements those ports against a database, a cache, a
queue, a mailer. ``web`` turns HTTP into calls on the layers below.
Dependencies point inwards only, so an adapter is added at the edge and a
rule is changed at the centre, and neither reaches the other except
through a port.

Beside those four sits ``app.py``, and nothing else belongs at this
level: a module here would be one no layer claims, which is another way
of saying nobody has decided what it is allowed to know.
"""
