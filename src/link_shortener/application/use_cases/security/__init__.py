"""
Reading what the service recorded about attempts on itself.

Sign-ins that failed, refusals, changes to who may do what -- counted out of
the security-event table rather than read out of a file, which is what
separates this from ``use_cases/journals`` next door. Both answer to
``audit:view``; this one answers in numbers a chart can draw, and the other
in lines.
"""
