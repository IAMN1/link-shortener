"""
Who may do what, written as data an operator can edit.

A package rather than a plain directory, because the file is read at run
time and therefore has to travel with the code: ``pyproject`` names it in
``package-data``, and before it did, the production image answered ``RBAC
configuration file not found`` while the file sat in the repository.

What goes in is the schedule of permissions and the roles built from them
-- the part of authorisation a deployment may change without touching
Python. The rules that decide whether a given actor may do a given thing
are code and live in the domain.
"""
