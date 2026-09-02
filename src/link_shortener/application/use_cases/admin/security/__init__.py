"""
Acts that keep the security-event table useful and finite.

The same two halves as the visit roll-up -- fold the finished days, then
sweep the rows they were computed from -- kept apart from it because the two
tables fill at different rates and an operator's cron line should name the
one it deletes from.
"""
