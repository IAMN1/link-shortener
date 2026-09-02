"""
Where a command meets the framework that runs it.

What goes in is the part that cannot be written without naming a CLI
library: the option declarations, everything printed, and what the shell
reads back as an exit code. The work itself is next door and knows none of
it.

The directory is that seam rather than a collection of frameworks. What
an adapter added here would be is another way of reaching the same
command bodies -- never a second set of commands, and never a command
only one adapter can run.
"""
