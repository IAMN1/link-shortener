"""
The questions the application asks of the store, written as SQL.

What goes in is a class satisfying one domain repository port, answering in
domain objects rather than in rows. Where a query is written is decided by
the port it answers, not by the tables it touches.

``sql_time.py`` is not one of them. It is the date arithmetic the two
engines spell differently, kept in one place because a repository that
spells it itself is a repository that is right on one engine only.
"""
