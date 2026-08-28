"""
Acts on one link, named by its code or by its address.

Creating one, resolving one, reading what is known about one, deleting one,
recording that one was opened. Every act here takes a code or a URL from the
caller, which is the line against ``use_cases/admin/links``, where an
operator acts on whatever rows match a rule.

Who may do it is decided per act rather than per directory: a redirect is
open to anybody, a listing is an account's own, a deletion asks about
ownership.
"""
