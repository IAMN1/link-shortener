"""
The configuration the application itself runs on.

A setting earns a place here by being declared on a profile: one class per
environment, the descriptors that read a value when it is asked for rather
than when the class is imported, and the factory that decides which profile
a process gets. Everything else here exists to choose a profile, read one,
or refuse a broken one.

``migration_url.py`` is the exception, and it is here because it reads those
same profiles. Alembic is handed one string and no configuration object, so
that string is built from a profile that is deliberately checked no further
than the database settings a migration actually uses.
"""
