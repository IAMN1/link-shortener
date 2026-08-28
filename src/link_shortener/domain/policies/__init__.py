"""
Rules that belong to no single entity, and to no single caller either.

A rule comes here when the thing it is about is not one entity: what a
password may be, who may confer a privilege, which codes the service
cannot give away, how much of a guest's allowance is left. Left in the
use case that first needed it, such a rule is written a second time by
the second caller, and then the two disagree in one deployment without
anything failing. ``require_roles_are_assignable`` is here because it
lived in a service and registration, which builds its ``User`` directly,
walked past it.

Two members are abstract -- ``HashCalculator`` and ``CodeGenerator``.
The rule is the domain's (a hash must be stable, a code must satisfy
``ShortCode``); the algorithm is not, so the class states the rule and
``infrastructure`` supplies the arithmetic.
"""
