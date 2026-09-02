"""
The tables, in the shape SQLAlchemy maps them.

What goes in is one mapped class and the indexes, constraints and column
defaults that belong to its table. A model carries no behaviour: the
questions asked of a table live in the repository beside it, and what a
value is allowed to be is a domain rule, enforced before anything reaches
here.

``base.py`` and ``associations.py`` hold no table of their own -- the
declarative base, and the join tables that belong to no single entity.
"""
