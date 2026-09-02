"""
The data shapes of the access-control model itself.

A role and a permission go here rather than beside the other DTOs because
they describe who may do what, not who somebody is or what a link is. The
account that wears a role is ``UserResponse`` one directory up; what the
role grants is here.
"""
