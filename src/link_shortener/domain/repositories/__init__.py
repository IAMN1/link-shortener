"""
What storage must be able to do, said without saying how.

Each class here is a port: the domain names the questions it needs
answered and the writes it needs made, and ``infrastructure/database``
answers them. That is what lets a use case be exercised against a fake
in a unit test and run against PostgreSQL unchanged.

A method belongs here when the domain needs the answer -- not when one
database makes it convenient. That is not a rule against aggregation:
``summary`` and ``buckets_between`` count in the query on purpose,
because a caller that fetched the rows to count them in Python would
move the whole table across the wire to do arithmetic the query planner
does better.

What a plain ``save``/``find`` interface cannot express is stated here
too, and it is load-bearing. The methods that decide and write in one
statement (``claim``, ``claim_for_rotation``, ``record_login``) exist
because a read followed by a write is a race; the ``lock_*`` methods
exist because counting and then writing is one as well.
"""
