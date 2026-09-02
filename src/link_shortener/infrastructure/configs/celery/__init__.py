"""
The block the worker is configured from.

Apart from the profiles next door because the reader is different: celery
reads this through ``config_from_object`` and knows none of their names,
and the application never reads these. Where a name stands on both sides
-- the broker URL, the result backend -- it is read a second time here,
because a worker starts without an application to ask.

What goes in is a value celery itself acts on -- a broker URL, a socket
bound, a serializer. A value the tasks read is a setting like any other and
belongs on the profile.
"""
