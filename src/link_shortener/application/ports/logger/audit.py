from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, Sequence


class AuditEvent(Enum):
    """Every kind of event the audit trail records, and the only ones.

    The values are what lands in the ``event_type`` field of a record, so
    this enum is the vocabulary a reader filters by. It is one enum rather
    than a set of string literals scattered through the adapters because a
    literal typed twice is two event types the moment one of them is
    misspelt, and a search for ``LOGIN_FAILED`` would then quietly answer
    "none" for the half written ``LOGIN_FAILURE``.

    The three link events came first and their values are unchanged: the
    journals already on disk were written with these exact strings, and an
    enum that renamed them would divide the history of one event into two
    names at the moment of deployment.

    Which events belong here is settled by one rule: an act that changes
    who may do what leaves a record. That is what puts the deactivation of
    an account and the editing of a role's permissions in, and it is why
    they are separate members rather than one ``ADMIN_ACTION`` -- an
    investigator arrives asking "who was given administrator, and when",
    and a vocabulary that answers only "somebody administered something"
    sends them back to reading the whole file. The rule also decides what
    stays out: listing accounts, reading one, seeding the database. They
    change nothing, and a journal that records reads as loudly as writes
    buries the writes.
    """

    URL_CREATED = "URL_CREATED"
    URL_ACCESSED = "URL_ACCESSED"
    URL_DELETED = "URL_DELETED"

    LOGIN_SUCCEEDED = "LOGIN_SUCCEEDED"
    LOGIN_FAILED = "LOGIN_FAILED"
    # The end of one session, by the account that opened it. Not
    # ``LOGIN_ENDED``: the pair above is one act with two outcomes, and
    # this is a different act -- it is also what an operator reads to tell
    # a session that was closed from one that is still open, which the
    # sign-in alone cannot say.
    #
    # It belongs by the rule above read plainly: a session ceasing is a
    # change to who may do what. Until this existed the journal recorded
    # eleven sessions revoked and named none of them -- measured by
    # grepping the three journals for LOGOUT and SESSION after a run that
    # closed eleven.
    SESSION_ENDED = "SESSION_ENDED"

    # A refresh token that had already been spent came back.
    #
    # The single most security-relevant thing this service can notice: the
    # honest holder and a copy are indistinguishable at that moment, which
    # is why the chain is retired. It was retired in silence -- the code
    # revoked the chain, returned nothing, and wrote no line anywhere, so
    # the one signal that says "a credential of this account is loose"
    # reached nobody. Recorded whichever of the two presented it, because
    # that is the fact: this token was presented twice.
    REFRESH_TOKEN_REPLAYED = "REFRESH_TOKEN_REPLAYED"  # nosec B105

    # An account created by whoever will own it, at the public route.
    # ``USER_CREATED`` below is the operator's version and the two are not
    # one event with a field, by the convention this vocabulary already
    # follows for PASSWORD_CHANGED against USER_PASSWORD_RESET: an
    # investigator asking "did this account let itself in" reads a
    # different fact in each.
    #
    # Its absence was the plainest hole in the journal. Measured:
    # ``audit.log`` stood at 335 lines, ``POST /api/v1/auth/register``
    # answered 202, and it stood at 335 after -- while the same account
    # made at a shell wrote ``USER_CREATED``. The sweep that deletes
    # unconfirmed accounts writes ``UNVERIFIED_ACCOUNTS_SWEPT``, so the
    # journal could record an account's removal without ever having
    # recorded its arrival.
    REGISTERED = "REGISTERED"

    USER_CREATED = "USER_CREATED"
    USER_DELETED = "USER_DELETED"
    USER_ACTIVATED = "USER_ACTIVATED"
    USER_EMAIL_CONFIRMED = "USER_EMAIL_CONFIRMED"
    USER_DEACTIVATED = "USER_DEACTIVATED"
    # Accounts removed by the schedule rather than by anybody, which is
    # why it sits with the ``USER_*`` members and not with the roles: it
    # belongs by the rule above read at the outcome instead of at the
    # actor. An account ceasing to exist is the widest change to who may
    # do what there is, and ``USER_DELETED`` above records exactly that
    # when an operator does it. The sweep did it in silence -- measured,
    # the journal stood at 111 records before and 111 after a run that
    # deleted an account -- so the same fact was on the record through
    # one door and off it through the other.
    UNVERIFIED_ACCOUNTS_SWEPT = "UNVERIFIED_ACCOUNTS_SWEPT"

    # Links removed by the schedule, for the reason above it read about
    # links instead of accounts: ``URL_DELETED`` records an operator
    # removing one, and the sweep removed many in silence. Measured, the
    # journal did not move across ``maintenance clean-expired``.
    EXPIRED_LINKS_SWEPT = "EXPIRED_LINKS_SWEPT"

    # The security history itself, folded into day totals and then swept
    # past ``SECURITY_EVENT_RETENTION_DAYS``.
    #
    # The one act in this service that removes records from this journal,
    # and it left none in it -- measured, ``maintenance
    # roll-up-security-events`` moved ``audit.log`` by zero lines while
    # deleting rows from ``security_events``. NIST SP 800-53 AU-9 is about
    # exactly this: the audit trail has to be protected from the people
    # who can act on it, and a trail that can be pruned without the
    # pruning appearing in it protects nothing. It is also the reason
    # ``BEYOND_ADMIN_ALL`` exists in
    # ``infrastructure/auth/rbac_authorization_service.py``: it is what
    # keeps ``admin:all`` from granting ``audit:view`` along with
    # everything else.
    SECURITY_HISTORY_SWEPT = "SECURITY_HISTORY_SWEPT"

    # Stored addresses lowered to the form the service now looks accounts
    # up by. An address is how an account is identified and how it
    # recovers a password, so rewriting one is a change to who may act as
    # that account -- the rule this vocabulary is built on, read plainly.
    ADDRESSES_NORMALISED = "ADDRESSES_NORMALISED"
    ROLES_CHANGED = "ROLES_CHANGED"

    # The address proved itself, from the link that was mailed to it.
    # Named without the ``USER_`` prefix on the convention the members
    # above already follow: ``USER_*`` is an operator acting on somebody
    # else's account, and a bare name is the account acting for itself --
    # which is why LOGIN_SUCCEEDED, PASSWORD_CHANGED and PASSWORD_RESET
    # are spelt the way they are. USER_EMAIL_CONFIRMED beside it is the
    # operator's version of this act, and the difference between them is
    # the whole reason both exist: one is evidence, the other is somebody
    # asserting it.
    EMAIL_CONFIRMED = "EMAIL_CONFIRMED"

    # The name of an event, not a password. bandit reads any string
    # assigned to a name containing PASSWORD as a credential; the value
    # here is what a reader filters the journal by, and it has to be
    # this word.
    PASSWORD_CHANGED = "PASSWORD_CHANGED"  # nosec B105
    # The same mark and the same reason as the line above.
    PASSWORD_RESET = "PASSWORD_RESET"  # nosec B105
    # The operator's version of the act above, named by the convention the
    # members here already follow: a bare name is the account acting for
    # itself, ``USER_*`` is somebody acting on it. The two are not one
    # event with a field, for the reason PASSWORD_RESET gives against
    # folding itself into PASSWORD_CHANGED -- an investigator asking "did
    # the owner do this" reads a different fact in each. This one says
    # nobody proved they can read the mailbox: an operator at a shell
    # replaced the password of an account they do not own.
    USER_PASSWORD_RESET = "USER_PASSWORD_RESET"  # nosec B105

    ROLE_CREATED = "ROLE_CREATED"
    ROLE_DELETED = "ROLE_DELETED"
    ROLE_PERMISSIONS_CHANGED = "ROLE_PERMISSIONS_CHANGED"

    AUDIT_VIEWED = "AUDIT_VIEWED"

    # An attempt that was refused, which is the one kind of event here
    # that records something that did *not* happen. It belongs by the same
    # rule as the rest read the other way round: an act that would have
    # changed who may do what, stopped. What an investigation is opened
    # over is rarely a successful administrative action -- it is somebody
    # trying one they are not entitled to, repeatedly, and until this
    # existed the journal held no trace of that at all.
    PERMISSION_DENIED = "PERMISSION_DENIED"


class AuditLogger(ABC):
    """
    Interface for audit logging of significant events in the application.

    Audit logs are used for security, compliance, and monitoring purposes.
    Implementations may bind contextual fields (e.g., request ID, client IP)
    using the `bind` method and then log events with minimal arguments.

    All methods are designed to receive already resolved values (short_code,
    original_url) rather than domain objects to keep the interface decoupled
    from the domain layer.

    Two kinds of method live here. The link events are abstract, one method
    each, because each implementation masks their ``original_url`` itself
    and there is no shared place above them to do it. The security events
    are concrete and all funnel into one abstract ``log_security_event``:
    an implementation gains a single method for the whole family, and the
    next event costs a method here and no change to any adapter. What they
    buy over calling ``log_security_event`` directly is a signature --
    ``log_login_failed`` names ``email`` and ``reason``, so a field left out
    or misnamed is a type error rather than a record missing a column
    nobody notices until the search for it comes up empty.
    """

    @abstractmethod
    def bind(self, **kwargs) -> "AuditLogger":
        """
        Return a new audit logger instance with the provided fields bound.

        Bound fields are automatically included in every subsequent log call.
        This method is typically used to attach request context (request ID,
        remote address, user agent) to the logger.

        Args:
            **kwargs: Arbitrary key-value pairs to bind (e.g., request_id,
                remote_addr, user_agent).

        Returns:
            A new AuditLogger instance with the bound fields.
        """
        ...

    @abstractmethod
    def log_url_created(self, short_code: str, original_url: str, **kwargs) -> None:
        """
        Log the creation of a shortened URL.

        Args:
            short_code: The generated short code.
            original_url: The original long URL being shortened.
            **kwargs: Additional context (e.g., batch_id, is_new, from_cache).
        """
        ...

    @abstractmethod
    def log_url_accessed(self, short_code: str, original_url: str, **kwargs) -> None:
        """
        Log an access (redirect) event for a shortened URL.

        Args:
            short_code: The short code that was accessed.
            original_url: The original URL to which the user was redirected.
            **kwargs: Additional context (e.g., clicks count before increment).
        """
        ...

    @abstractmethod
    def log_url_deleted(self, short_code: str, original_url: str, **kwargs) -> None:
        """Log deletion of a shortened URL."""
        ...

    @abstractmethod
    def log_security_event(self, event: AuditEvent, **fields) -> None:
        """
        Record an event about an account rather than about a link.

        The one method every security event goes through. It takes no
        positional field of its own beyond the event, because the events in
        this family have no field in common: a login has an email and no
        short code, a role change has a pair of role lists and neither.

        An implementation is expected to mask what it writes -- ``email``
        in particular, which is why the field is passed under that name and
        not folded into a message string.

        Args:
            event: Which event this is. A member of ``AuditEvent``, so the
                ``event_type`` written to the journal comes from the one
                vocabulary a reader filters by.
            **fields: The event's own fields, merged over the bound ones.
        """
        ...

    def log_login_succeeded(
        self, target_user_id: str, email: str, **fields
    ) -> None:
        """
        Record a successful sign-in.

        The account goes in under ``target_user_id`` rather than
        ``user_id``, which is the name the request context already binds
        for whoever is making the request. At a sign-in those are usually
        the same person and usually nobody, since the caller is anonymous
        until this succeeds -- but not always: an already signed-in client
        may post credentials for another account, and written under the
        context's own name the event would overwrite who asked with who
        was asked about. It is also the name the administrative use cases
        use for the account an action is aimed at.

        Args:
            target_user_id: The account that signed in.
            email: Its address, masked by the implementation.
            **fields: Additional context.
        """
        self.log_security_event(
            AuditEvent.LOGIN_SUCCEEDED,
            target_user_id=target_user_id,
            email=email,
            **fields,
        )

    def log_expired_links_swept(self, links_deleted: int, **fields) -> None:
        """
        Record a sweep that removed links.

        Args:
            links_deleted: How many rows went.
            **fields: Additional context.
        """
        self.log_security_event(
            AuditEvent.EXPIRED_LINKS_SWEPT,
            links_deleted=links_deleted,
            **fields,
        )

    def log_security_history_swept(
        self, days_folded: int, events_deleted: int, **fields
    ) -> None:
        """
        Record a sweep of the security journal's own rows.

        Both numbers, because they answer different questions: folding
        loses nothing, sweeping is what removes evidence, and a record
        carrying only their sum could not tell an investigator which had
        happened.

        Args:
            days_folded: Finished days folded into totals.
            events_deleted: Raw rows removed past retention.
            **fields: Additional context.
        """
        self.log_security_event(
            AuditEvent.SECURITY_HISTORY_SWEPT,
            days_folded=days_folded,
            events_deleted=events_deleted,
            **fields,
        )

    def log_addresses_normalised(self, addresses_changed: int, **fields) -> None:
        """
        Record addresses rewritten in place.

        Args:
            addresses_changed: How many accounts now answer to a different
                spelling of their address.
            **fields: Additional context.
        """
        self.log_security_event(
            AuditEvent.ADDRESSES_NORMALISED,
            addresses_changed=addresses_changed,
            **fields,
        )

    def log_registered(self, target_user_id: str, email: str, **fields) -> None:
        """
        Record an account that registered itself.

        The account goes in under ``target_user_id`` for the reason
        ``log_login_succeeded`` gives: at a registration the caller is
        anonymous, and the new account is what the event is about.

        Args:
            target_user_id: The account that came into existence.
            email: Its address, masked by the implementation.
            **fields: Additional context.
        """
        self.log_security_event(
            AuditEvent.REGISTERED,
            target_user_id=target_user_id,
            email=email,
            **fields,
        )

    def log_session_ended(self, target_user_id: Optional[str], **fields) -> None:
        """
        Record one session closing.

        Args:
            target_user_id: The account whose session ended, when the
                request knew it. A client may sign out holding only a
                refresh token, which names the session rather than the
                account; the session is the fact either way, and this is
                left ``None`` rather than guessed.
            **fields: Additional context, ``session_id`` among them.
        """
        self.log_security_event(
            AuditEvent.SESSION_ENDED,
            target_user_id=target_user_id,
            **fields,
        )

    def log_refresh_token_replayed(
        self, target_user_id: str, **fields
    ) -> None:
        """
        Record a refresh token presented after it had been spent.

        Args:
            target_user_id: The account whose chain was retired.
            **fields: Additional context, the chain among them.
        """
        self.log_security_event(
            AuditEvent.REFRESH_TOKEN_REPLAYED,
            target_user_id=target_user_id,
            **fields,
        )

    def log_login_failed(self, email: str, reason: str, **fields) -> None:
        """
        Record a sign-in that was refused.

        ``reason`` distinguishes cases the HTTP response deliberately does
        not. A deactivated account and a wrong password are answered
        identically over the wire, so that a guesser learns nothing from
        the difference; the audit trail has the opposite obligation, since
        an operator reading it needs to tell "somebody is guessing
        passwords" from "a disabled account is still being used by
        something". The two readers are different people with different
        entitlements, and ``audit:view`` is what separates them.

        Args:
            email: The address the attempt was made against, masked by the
                implementation.
            reason: Why it was refused, in the application's own terms.
            **fields: Additional context.
        """
        self.log_security_event(
            AuditEvent.LOGIN_FAILED, email=email, reason=reason, **fields
        )

    def log_user_created(
        self, target_user_id: str, email: str, roles: Sequence[str], **fields
    ) -> None:
        """
        Record an account brought into being by an administrator.

        ``target_user_id`` for the same reason as on the sign-in events,
        and here the two are never the same person: ``user_id`` comes from
        the request context and is the administrator who asked. Written
        under that name the new account would overwrite them, and the
        record of who creates accounts would name only the accounts.

        Args:
            target_user_id: The new account.
            email: Its address, masked by the implementation.
            roles: Role names it was created with, which may be empty when
                the account was given the default.
            **fields: Additional context.
        """
        self.log_security_event(
            AuditEvent.USER_CREATED,
            target_user_id=target_user_id,
            email=email,
            roles=list(roles),
            **fields,
        )

    def log_user_deleted(
        self, target_user_id: str, links_deleted: int, **fields
    ) -> None:
        """
        Record an account removed, and how much went with it.

        ``links_deleted`` is part of the event rather than a detail: the
        links go with the account and the deletion is not reversible, so
        the count is the only remaining measure of what was destroyed.

        Args:
            target_user_id: The account that was removed.
            links_deleted: How many of its links went with it.
            **fields: Additional context.
        """
        self.log_security_event(
            AuditEvent.USER_DELETED,
            target_user_id=target_user_id,
            links_deleted=links_deleted,
            **fields,
        )

    def log_user_activated(self, target_user_id: str, **fields) -> None:
        """
        Record an account switched back on.

        Args:
            target_user_id: The account that was activated.
            **fields: Additional context.
        """
        self.log_security_event(
            AuditEvent.USER_ACTIVATED, target_user_id=target_user_id, **fields
        )

    def log_user_email_confirmed(
        self, target_user_id: str, already_confirmed: bool, **fields
    ) -> None:
        """
        Record an address marked confirmed on an operator's word.

        The act it records is a bypass: confirmation normally proves that
        whoever registered can read that mailbox, and this asserts it
        instead. What it grants is the ability to sign in, which is why
        it belongs here by the same rule as suspension and deletion --
        and it sits behind the same permission as both.

        ``already_confirmed`` because pressing the button twice is not an
        error and leaves a record either way: without it the journal
        cannot tell an address that was opened up from one that was
        already open, and only the first is a bypass of anything.

        Args:
            target_user_id: The account whose address was confirmed.
            already_confirmed: Whether it was confirmed before this.
            **fields: Additional context.
        """
        self.log_security_event(
            AuditEvent.USER_EMAIL_CONFIRMED,
            target_user_id=target_user_id,
            already_confirmed=already_confirmed,
            **fields,
        )

    def log_email_confirmed(self, target_user_id: str, **fields) -> None:
        """
        Record an address proven readable by whoever registered it.

        The act that turns an account which cannot sign in into one that
        can, which is what puts it here under the rule the enum states:
        an act that changes who may do what leaves a record. Its two
        neighbours on the self-service path -- a password changed and a
        password reset -- were recorded from the start; this one was not,
        so an investigator reading the journal for an account saw it
        appear at registration and then simply start signing in.

        No ``already_confirmed``, unlike ``log_user_email_confirmed``.
        That flag exists because an operator can press the button twice
        and the second press bypasses nothing; here a token can only be
        spent once, so a second attempt is refused before it reaches this
        line and there is no second outcome to distinguish.

        ``user_id`` is nobody. The request is anonymous -- the account
        cannot sign in yet, which is the point of the whole exchange --
        and the account it is about is ``target_user_id``, as on every
        other event here.

        Args:
            target_user_id: The account whose address was confirmed.
            **fields: Additional context.
        """
        self.log_security_event(
            AuditEvent.EMAIL_CONFIRMED, target_user_id=target_user_id, **fields
        )

    def log_user_deactivated(
        self, target_user_id: str, sessions_revoked: int, **fields
    ) -> None:
        """
        Record an account switched off, and the sessions it lost.

        The count matters because deactivation and sign-out are separate
        acts: an account disabled while three sessions were open is a
        different situation from one disabled while nobody held a token,
        and only this number tells them apart afterwards.

        Args:
            target_user_id: The account that was deactivated.
            sessions_revoked: How many refresh sessions were closed with it.
            **fields: Additional context.
        """
        self.log_security_event(
            AuditEvent.USER_DEACTIVATED,
            target_user_id=target_user_id,
            sessions_revoked=sessions_revoked,
            **fields,
        )

    def log_password_changed(self, target_user_id: str, sessions_revoked: int, **fields) -> None:
        """
        Record a password replaced by the account holder.

        Belongs here by the rule the vocabulary is built on: the password
        is what proves who may act as this account, so replacing it
        changes who may do what. It is also the event an investigation
        starts from -- an account taken over is an account whose password
        changed at a time its owner cannot account for, and without a
        record there is nothing to put a time against.

        ``sessions_revoked`` for the same reason it is carried on
        deactivation: a change made while four sessions were open closed
        four of them, and if one of those belonged to an intruder, the
        count is the only trace that anything was thrown out.

        The old and the new password are not fields here and must not
        become fields. Neither is the fact that this went through the
        forgotten-password route rather than the settings page -- that is
        a separate event, because the two are entered from different
        places and one of them needs no password at all.

        Args:
            target_user_id: The account whose password was replaced.
            sessions_revoked: How many refresh sessions were closed with it.
            **fields: Additional context.
        """
        self.log_security_event(
            AuditEvent.PASSWORD_CHANGED,
            target_user_id=target_user_id,
            sessions_revoked=sessions_revoked,
            **fields,
        )

    def log_password_reset(self, target_user_id: str, sessions_revoked: int, **fields) -> None:
        """
        Record a password replaced through the forgotten-password route.

        Its own event rather than a ``reason`` field on
        ``PASSWORD_CHANGED``, because the two are entered from different
        places and only one of them was made by somebody who knew the old
        password. An investigator asking "was this account taken over"
        reads them as different facts: a change is somebody who was
        already inside, a reset is somebody who proved they can read the
        mailbox and nothing else. Folded into one event, the question is
        answered by filtering on a field, and a filter written by hand is
        a filter that can be left off.

        No ``email`` field. The address is what the message went to and is
        already in the record of the request; repeating it here would put
        it in the audit trail once per reset for no question it answers.

        Args:
            target_user_id: The account whose password was replaced.
            sessions_revoked: How many refresh sessions were closed with it.
            **fields: Additional context.
        """
        self.log_security_event(
            AuditEvent.PASSWORD_RESET,
            target_user_id=target_user_id,
            sessions_revoked=sessions_revoked,
            **fields,
        )

    def log_user_password_reset(
        self, target_user_id: str, sessions_revoked: int, **fields
    ) -> None:
        """
        Record a password replaced by an operator, on somebody else's account.

        The third way a password changes in this service, and the only one
        that left no record. ``flask security reset-password`` is reached
        for an account believed to be compromised -- which is to say, at
        the start of exactly the investigation this journal exists to
        serve -- and the account it acts on then shows a password that
        changed at a time nobody can account for, with nothing saying an
        operator did it deliberately.

        Its own event rather than ``PASSWORD_RESET`` with a field, for the
        reason that member gives against folding itself into
        ``PASSWORD_CHANGED``: the reader's question is who did this, and
        an answer that depends on remembering to filter by a field is an
        answer that gets read wrong. Here nobody proved they can read the
        mailbox and nobody knew the old password.

        No actor is bound: a command run at a shell has no signed-in user
        to name. What the record carries instead is the ``request_id`` the
        command builds -- ``cli-reset-password`` -- which is what tells a
        reader this came from the console rather than from a request.

        ``sessions_revoked`` for the reason it is carried on the two
        members above: the count is the only trace that anything was
        thrown out, and on this path it is the whole point of the command.

        Args:
            target_user_id: The account whose password was replaced.
            sessions_revoked: How many refresh sessions were closed with it.
            **fields: Additional context.
        """
        self.log_security_event(
            AuditEvent.USER_PASSWORD_RESET,
            target_user_id=target_user_id,
            sessions_revoked=sessions_revoked,
            **fields,
        )

    def log_role_created(
        self, role: str, permissions: Sequence[str], **fields
    ) -> None:
        """
        Record a new role, and what it grants.

        Args:
            role: Name of the role.
            permissions: Permission names it was created with.
            **fields: Additional context.
        """
        self.log_security_event(
            AuditEvent.ROLE_CREATED,
            role=role,
            permissions=list(permissions),
            **fields,
        )

    def log_role_deleted(self, role: str, holders: int, **fields) -> None:
        """
        Record a role removed, and how many accounts it came off.

        The name alone left the record silent about reach. Deleting a role
        takes it off every account wearing it, in one statement and without
        touching any of them, so "role removed" read the same whether it
        stripped nobody or everybody -- and an investigator asking why an
        account stopped being able to do something finds nothing against
        that account, exactly as with ``ROLE_PERMISSIONS_CHANGED``.

        A count rather than the accounts themselves. The identities are
        recoverable from the ``ROLES_CHANGED`` records that put the role on
        each of them, while a list would put an unbounded field into a
        journal kept at ``maxsize 1G`` -- a role worn by a thousand
        accounts would write a line of some forty kilobytes, once, for a
        fact already written a thousand times.

        Args:
            role: Name of the role that was deleted.
            holders: How many accounts were wearing it, active or not.
            **fields: Additional context.
        """
        self.log_security_event(
            AuditEvent.ROLE_DELETED, role=role, holders=holders, **fields
        )

    def log_role_permissions_changed(
        self,
        role: str,
        permissions_before: Sequence[str],
        permissions_after: Sequence[str],
        holders: int,
        **fields,
    ) -> None:
        """
        Record a change to what a role grants, and how far it reached.

        The widest-reaching act in this vocabulary: it changes what every
        holder of the role may do, at once, without any of their accounts
        being touched. An investigator looking at why an account could
        suddenly do something will find nothing against that account --
        the change is here, and ``holders`` is how many accounts it moved.

        A count rather than a list, for the reason given on
        ``log_role_deleted``.

        Args:
            role: Name of the role whose permissions changed.
            permissions_before: Permission names it granted before.
            permissions_after: Permission names it grants now.
            holders: How many accounts wear the role, active or not.
            **fields: Additional context.
        """
        self.log_security_event(
            AuditEvent.ROLE_PERMISSIONS_CHANGED,
            role=role,
            permissions_before=list(permissions_before),
            permissions_after=list(permissions_after),
            holders=holders,
            **fields,
        )

    def log_roles_changed(
        self,
        target_user_id: str,
        roles_before: Sequence[str],
        roles_after: Sequence[str],
        **fields,
    ) -> None:
        """
        Record a change to what an account is entitled to.

        Both sides are written, not just the new one. "Now an
        administrator" and "was already an administrator" are the same
        record with only the second half, and which of the two happened is
        the entire question an investigator brings to this line.

        Args:
            target_user_id: The account whose roles changed, as against the
                ``user_id`` of whoever changed them.
            roles_before: Role names it held before.
            roles_after: Role names it holds now.
            **fields: Additional context.
        """
        self.log_security_event(
            AuditEvent.ROLES_CHANGED,
            target_user_id=target_user_id,
            roles_before=list(roles_before),
            roles_after=list(roles_after),
            **fields,
        )

    def log_unverified_accounts_swept(
        self, accounts_deleted: int, tokens_deleted: int, **fields
    ) -> None:
        """
        Record a sweep of registrations nobody confirmed.

        Counts rather than the accounts themselves, for the reason
        ``log_role_deleted`` gives against listing holders: a sweep after
        a bulk of registrations would put thousands of addresses into one
        field of one line, in a journal kept at a size. What the record
        answers is that the service removed accounts, how many, and when
        -- which is the question asked of it, because the actor here is a
        schedule and there is no operator to look up.

        Written only for a sweep that removed something. A schedule
        running hourly over a service with nothing to clean would
        otherwise write a line an hour saying so, and a journal of those
        is a journal nobody reads.

        Args:
            accounts_deleted: Registrations removed by this sweep.
            tokens_deleted: Confirmation tokens removed with them.
            **fields: Additional context.
        """
        self.log_security_event(
            AuditEvent.UNVERIFIED_ACCOUNTS_SWEPT,
            accounts_deleted=accounts_deleted,
            tokens_deleted=tokens_deleted,
            **fields,
        )

    def log_audit_viewed(
        self, journal: str, reason: str, filters: Optional[dict] = None, **fields
    ) -> None:
        """
        Record that somebody read a journal.

        Not written on every read: the page polls, and a record per poll
        would put twelve lines a minute into the journal being displayed --
        each of which is then displayed. ``reason`` is what the caller
        decided was worth recording, and the decision belongs there rather
        than here, since only the caller can see whether this read differs
        from the one before it.

        Args:
            journal: Which journal was read.
            reason: What made this read worth a record.
            filters: What the reader searched for, when they searched.
            **fields: Additional context.
        """
        self.log_security_event(
            AuditEvent.AUDIT_VIEWED,
            journal=journal,
            reason=reason,
            filters=filters or {},
            **fields,
        )

    def log_permission_denied(
        self,
        required: Sequence[str] = (),
        exceeded: Sequence[str] = (),
        **fields,
    ) -> None:
        """
        Record an attempt that was refused for want of a privilege.

        The only event here about something that did not happen, and the
        one an investigation most often starts from: a successful
        administrative action has a person behind it who meant to take it,
        while a refused one may be somebody finding out what they can
        reach.

        Written from one place -- the error handler, which is where a
        ``PermissionDeniedError`` raised on any route ends up -- rather
        than from each raiser. Writing it at each raise site is a record
        per raise site, and a missing one the first time somebody adds a
        raise and does not think of the journal -- the argument
        ``CountingAuditLogger`` is built on.

        Any *route*, and that is the limit of it: the CLI reaches
        ``DeleteLinkUseCase`` without a request and without an error
        handler, so a refusal there is logged by the use case and not
        recorded here. It is a narrow gap -- the CLI runs as whoever has
        a shell on the host, and what such a caller can do is not bounded
        by this application anyway.

        What was attempted is not an argument here: the address and the
        method are in the request context, which every caller binds before
        writing, and the record carries them as ``request_path`` and
        ``request_method`` like every other event. Passed again under
        shorter names they were simply written twice -- measured on the
        running stack, the first version of this record carried both
        ``"request_path"`` and ``"path"`` with the same value in each.

        The permission is an argument, because nothing else knows it: a
        caller repeatedly refused ``admin:all`` is a different story from
        one who wandered onto a page.

        Whichever of the two is empty is left out rather than written as
        an empty list, which is how ``_terms_of`` writes a search: a
        record should say what was asked, not list what was not. Every
        ordinary refusal carries ``required`` and no ``exceeded``, and an
        escalation attempt the other way round, so writing both always
        would put an empty field in every record of both kinds.

        Args:
            required: Permission names the caller would have needed.
                Several where any one of them would have done.
            exceeded: Permission names the caller tried to hand out
                without holding them -- an escalation attempt rather than
                an ordinary refusal.
            **fields: Additional context.
        """
        named = {
            name: list(value)
            for name, value in (("required", required), ("exceeded", exceeded))
            if value
        }
        self.log_security_event(
            AuditEvent.PERMISSION_DENIED, **named, **fields
        )

    @abstractmethod
    def is_healthy(self) -> bool:
        """Check if the audit logger is operational."""
        ...
