import click
from flask import current_app
from flask.cli import with_appcontext

from link_shortener.application import RequestContext
from link_shortener.domain import Email
from link_shortener.infrastructure.cli.commands.database import init_db as init_db_logic
from link_shortener.infrastructure.cli.commands.database import drop_db as drop_db_logic
from link_shortener.infrastructure.cli.commands.database import seed_db as seed_db_logic
from link_shortener.infrastructure.cli.commands.database import load_base_roles_from_cfg as load_base_roles_logic
from link_shortener.infrastructure.cli.commands.database import load_custom_roles_from_cfg as load_custom_roles_logic
from link_shortener.infrastructure.cli.commands.database import check_db_connection as check_db_logic
from link_shortener.infrastructure.cli.commands.database import migrate_db as migrate_db_logic
from link_shortener.infrastructure.cli.commands.stats import refresh_stats as refresh_stats_logic
from link_shortener.infrastructure.cli.commands.stats import get_stats as get_stats_logic
from link_shortener.infrastructure.cli.commands.maintenance import clean_expired_links as clean_expired_logic
from link_shortener.infrastructure.cli.commands.maintenance import clean_expired_sessions as clean_sessions_logic
from link_shortener.infrastructure.cli.commands.maintenance import (
    clean_unverified_accounts as clean_unverified_logic,
)
from link_shortener.infrastructure.cli.commands.maintenance import (
    find_addresses_needing_normalising as find_mixed_case_logic,
)
from link_shortener.infrastructure.cli.commands.maintenance import normalise_addresses as normalise_logic
from link_shortener.infrastructure.cli.commands.maintenance import what_the_database_said
from link_shortener.infrastructure.cli.commands.link import delete_link as delete_link_logic
from link_shortener.infrastructure.cli.commands.link import get_link_info as link_info_logic
from link_shortener.infrastructure.cli.commands.link import list_links as list_links_logic
from link_shortener.infrastructure.cli.commands.cache import check_redis_connection as check_redis_logic
from link_shortener.infrastructure.cli.commands.cache import get_cache_info as cache_info_logic
from link_shortener.infrastructure.cli.commands.cache import clear_cache as clear_cache_logic
from link_shortener.infrastructure.cli.commands.admin import create_admin as create_admin_logic


# ------------------------------------------------------------------
# Database commands group
# ------------------------------------------------------------------
@click.group(name="db")
def db_group():
    """Database management commands (init, drop, seed, roles, check, migrate)"""
    pass

@db_group.command("init")
@with_appcontext
def init_db():
    "Create database tables (only if USE_ALEMBIC is False)."
    container = current_app.container
    db_manager = container.get_db_manager()
    use_alembic = current_app.config.get("USE_ALEMBIC", True)
    try:
        init_db_logic(db_manager, use_alembic)
    except RuntimeError as e:
        click.echo(f"ERROR: {e}", err=True)
        raise SystemExit(1)


@db_group.command("drop")
@click.option("--yes", is_flag=True, help="Confirm dropping all tables")
@with_appcontext
def drop_db(yes):
    """Drop all database tables (DANGEROUS)."""
    if not yes:
        click.confirm("Are you sure you want to drop all tables?", abort=True)
    container = current_app.container
    db_manager = container.get_db_manager()
    use_alembic = current_app.config.get("USE_ALEMBIC", True)
    try:
        drop_db_logic(db_manager, use_alembic, confirm=True)
    except RuntimeError as e:
        click.echo(f"ERROR: {e}", err=True)
        raise SystemExit(1)

@db_group.command("seed")
@click.option("--count", default=10, help="Number of test links to create")
@with_appcontext
def seed_db(count):
    """Fill database with test links."""
    container = current_app.container
    context = RequestContext(request_id="cli-seed")
    use_case = container.get_seed_database_use_case()
    try:
        result = seed_db_logic(use_case, count, context)
    except Exception as e:
        # Not the guest limit: seeding goes through the regular create
        # use case, but with a context carrying no address, and both the
        # guest quota and the guest expiry are keyed on one. A CLI call is
        # neither counted nor expired -- it creates permanent,
        # unattributed links, by design.
        click.echo(f"ERROR: seeding failed: {e}", err=True)
        raise SystemExit(1)

    click.echo(f"Created {result.created} test links")
    if result.existing:
        click.echo(f"{result.existing} of the requested URLs already existed")

@db_group.command("load-base-roles")
@with_appcontext
def load_roles():
    """Seed default roles and permissions from YAML config."""
    container = current_app.container
    db_manager = container.get_db_manager()
    load_base_roles_logic(db_manager=db_manager)

@db_group.command("load-custom-roles")
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--update-existing", is_flag=True, help="Update existing roles and permissions")
@with_appcontext
def load_custom_roles(file_path, update_existing):
    """Load roles and permissions from a YAML file."""
    container = current_app.container
    db_manager = container.get_db_manager()
    load_custom_roles_logic(db_manager, file_path, update_existing)
    click.echo(f"Roles and permissions loaded from {file_path}")

@db_group.command("check")
@with_appcontext
def check_db():
    """Check database connection health."""
    container = current_app.container
    failure = check_db_logic(container.get_db_manager())
    if failure is None:
        click.echo("Database connection is healthy.")
    else:
        # Non-zero exit: this command is meant to be usable from monitoring
        # and CI, where a failure that returns 0 is indistinguishable from ok.
        #
        # The reason is named. Without it this command said the same
        # sentence for a wrong password, an unreachable host and a
        # database that does not exist -- on the one command an operator
        # runs precisely to tell those apart.
        click.echo(f"Database connection failed: {failure}", err=True)
        raise SystemExit(1)

@db_group.command("status")
@with_appcontext
def db_status():
    """Alias for 'db check' - check database connection."""
    container = current_app.container
    failure = check_db_logic(container.get_db_manager())
    if failure is None:
        click.echo("Database connection is healthy.")
    else:
        click.echo(f"Database connection failed: {failure}", err=True)
        raise SystemExit(1)

@db_group.command("migrate")
@with_appcontext
def migrate_db():
    """Apply database migrations using Alembic."""
    use_alembic = current_app.config.get("USE_ALEMBIC", True)
    if not use_alembic:
        # No point naming a database this branch will not touch, and not a
        # free thing to do either: the URL carries the host and the user.
        migrate_db_logic(use_alembic)
        return
    migrate_db_logic(use_alembic, _echo_target())

# ------------------------------------------------------------------
# Stats commands group
# ------------------------------------------------------------------
@click.group(name="stats")
def stats_group():
    """Statistics management commands."""
    pass


@stats_group.command("show")
@with_appcontext
def stats_show():
    """Display service statistic in console"""
    container = current_app.container
    stats = get_stats_logic(container.get_get_service_stats_use_case())
    click.echo("\n\t\t\tSERVICE STATISTICS")
    click.echo("=" * 80)
    click.echo(f"\t\t\tTotal URLs:      {stats['total_urls']}")
    click.echo(f"\t\t\tTotal clicks:    {stats['total_clicks']}")
    click.echo(f"\t\t\tAvg clicks/URL:  {stats['avg_clicks_per_url']}")
    click.echo("\n\t\t\tTOP 5 POPULAR LINKS:")
    for i, (code, clicks, _url) in enumerate(stats['popular_links'], 1):
        click.echo(f"\t\t\t{i}. {code} - {clicks} clicks")
    click.echo("=" * 80)

@stats_group.command("refresh")
@with_appcontext
def stats_refresh():
    """Force refresh of cached statistics"""
    container = current_app.container
    stats = refresh_stats_logic(
        container.get_get_service_stats_use_case(), container.get_cache()
    )
    click.echo("\n\t\t\tSTATISTIC REFRESHED IN CACHE:")
    click.echo("=" * 80)
    click.echo(f"\t\t\tTotal URL's: {stats['total_urls']}")
    click.echo(f"\t\t\tTotal clicks: {stats['total_clicks']}")
    click.echo(f"\t\t\tAvg clicks per URL: {stats['avg_clicks_per_url']}")
    click.echo("=" * 80)

# ------------------------------------------------------------------
# Maintenance commands group
# ------------------------------------------------------------------
@click.group(name="maintenance")
def maintenance_group():
    """Maintenance and health check commands."""
    pass

@maintenance_group.command("clean-expired")
@with_appcontext
def clean_expired():
    """Delete links whose expiry has passed.

    Takes no threshold: an expired link is expired. There is no --days
    option, and a cron line still passing one will fail rather than sweep
    something else.
    """
    # `--days` belonged to a different sweep -- everything untouched for
    # N days, permanent links included -- and was removed rather than
    # redefined, so an old cron line fails loudly instead of quietly
    # deleting links nobody asked it to. A redirect to an expired link
    # already answers 410, which is why no threshold is wanted here.
    container = current_app.container
    context = RequestContext(request_id="cli-clean")
    use_case = container.get_clean_expired_links_use_case()
    deleted = clean_expired_logic(use_case, context)
    click.echo(f"Deleted {deleted} expired links.")

@maintenance_group.command("clean-sessions")
@with_appcontext
def clean_sessions():
    """Delete refresh sessions whose tokens have already expired."""
    container = current_app.container
    deleted = clean_sessions_logic(container.get_uow_factory())
    click.echo(f"Deleted {deleted} expired refresh sessions.")

@maintenance_group.command("normalize-emails")
@click.option(
    "--apply",
    "apply_changes",
    is_flag=True,
    help="Write the change. Without it, nothing is modified.",
)
@with_appcontext
def normalize_emails(apply_changes):
    """Lower stored addresses that predate address normalisation.

    An address is now held in lower case, so an account written earlier
    as Case@Example.com is no longer found by a lookup for it: its owner
    cannot sign in, and registering the address again would make a second
    account for the same mailbox.

    Reports by default and changes nothing; pass --apply to write.
    Addresses that would collide with another account once lowered are
    reported and left alone, because merging two accounts is a decision
    about whose links, roles and sessions survive.

    Each address is written in its own transaction, so one that cannot be
    written leaves the rest migrated. Exits non-zero if the accounts
    cannot be read at all, if the database refused an address, if writing
    one failed, or if the run was interrupted with work still to do. Two
    outcomes are not failures and exit 0: a conflicting pair, which only
    its owners can untangle, and a row somebody else deleted or renamed
    while this ran -- neither is something a second run would fix.
    """
    db_manager = current_app.container.get_db_manager()

    # Wrapped like `db init` and `db drop` next door, so an unreachable
    # database prints "ERROR: ..." and exits 1 rather than a traceback.
    try:
        rows = find_mixed_case_logic(db_manager)
    except Exception as e:
        # First line only, like the writing path: SQLAlchemy renders the
        # statement into the rest of the message.
        click.echo(
            f"ERROR: could not read the accounts: "
            f"{what_the_database_said(e)}",
            err=True,
        )
        raise SystemExit(1)

    if not rows:
        click.echo("Every stored address is already lower case.")
        return

    clashing = [r for r in rows if r["clashes"]]
    fixable = [r for r in rows if not r["clashes"]]

    for row in fixable:
        click.echo(f"  {row['email']} -> {Email.normalise(row['email'])}")
    for row in clashing:
        click.echo(
            f"  {row['email']}: another account also lowers to "
            f"{Email.normalise(row['email'])}; left alone",
            err=True,
        )

    if not apply_changes:
        click.echo(
            f"{len(fixable)} to change, {len(clashing)} in conflict. "
            f"Nothing written; pass --apply to write."
        )
        return

    # The very rows that were just listed, rather than a second read of
    # the table: read twice, the report and the counts would describe
    # different moments.
    result = normalise_logic(db_manager, rows)
    click.echo(f"Lowered {result['changed']} addresses.")
    if result["skipped"]:
        click.echo(
            f"{result['skipped']} left in conflict and untouched.", err=True
        )
    if result["refused"]:
        # Not a conflict this command could see when it looked: the row
        # was taken between the report and the write.
        click.echo(
            f"{result['refused']} were taken by another account between "
            f"the report and the write; they are conflicts now, and the "
            f"next run will list them as such and touch nothing.",
            err=True,
        )
    if result["moved"]:
        # Two causes, one line: the row was deleted, or its address was
        # changed by its owner while this ran. Either way the write
        # matched nothing, and neither is this command's to undo.
        click.echo(
            f"{result['moved']} were deleted or changed by somebody else "
            f"between the report and the write, and were left alone.",
            err=True,
        )
    if result["failed"]:
        # No verdict on whether running again helps: this bucket holds a
        # locked database and a value too long for the column alike. The
        # database's own words go to the operator instead.
        click.echo(
            f"{result['failed']} could not be written and were left as "
            f"they are. The database gave:",
            err=True,
        )
        for reason in result["reasons"]:
            click.echo(f"  {reason}", err=True)
    # Only when something is actually left: an interrupt arriving after
    # the last address was written interrupts nothing. The remainder is
    # what says so -- every other path attempts every address it was
    # given.
    unfinished = result["remaining"] > 0
    if unfinished:
        click.echo(
            f"Interrupted. {result['remaining']} addresses were not "
            f"attempted; running again picks them up.",
            err=True,
        )

    # Non-zero when this run could not do what it was asked, like
    # `db check`. Two outcomes stay at 0: a conflict, which only an owner
    # can untangle, and a `moved` row, which is gone or already correct.
    # Either would put a schedule into permanent alarm over something no
    # run can change.
    if result["failed"] or result["refused"] or unfinished:
        raise SystemExit(1)

@maintenance_group.command("clean-unverified")
@with_appcontext
def clean_unverified():
    """Delete registrations nobody confirmed, and dead tokens with them.

    Meant for a schedule, beside clean-expired and clean-sessions.
    Nothing calls it on its own, so without a cron line an unconfirmed
    registration holds its address for good -- which is the thing
    UNVERIFIED_ACCOUNT_TTL_HOURS exists to prevent.
    """
    container = current_app.container
    context = RequestContext(request_id="cli-clean-unverified")
    use_case = container.get_clean_unverified_accounts_use_case()
    deleted = clean_unverified_logic(use_case, context)
    click.echo(f"Deleted {deleted} unconfirmed accounts.")

@maintenance_group.command("check-redis")
@with_appcontext
def check_redis():
    """Check Redis connection (if Redis cache is used)."""
    container = current_app.container
    redis_expected = current_app.config.get("REDIS_ENABLED", False) and \
        current_app.config.get("CACHE_ENABLED", True)

    if check_redis_logic(container.get_cache()):
        click.echo("Redis connection is healthy.")
    elif not redis_expected:
        # Deliberately disabled cache is not a failure.
        click.echo("Redis is disabled by configuration.")
    else:
        click.echo("Redis connection failed.", err=True)
        raise SystemExit(1)

@maintenance_group.command("health")
@with_appcontext
def maintenance_health():
    """Run all health checks (database + Redis)."""
    container = current_app.container

    # Check database
    db_ok = check_db_logic(container.get_db_manager()) is None
    click.echo(f"Database: {'OK' if db_ok else 'FAILED'}")

    # Check Redis. A deliberately disabled cache is not a failure: the
    # documented local setup runs with REDIS_ENABLED=false and an in-memory
    # cache, and reporting FAILED there made a healthy install look broken
    # (and any exit-code based monitoring go red).
    redis_expected = current_app.config.get("REDIS_ENABLED", False) and \
        current_app.config.get("CACHE_ENABLED", True)

    if not redis_expected:
        click.echo("Redis: SKIPPED (disabled by configuration)")
        redis_ok = True
    else:
        redis_ok = check_redis_logic(container.get_cache())
        click.echo(f"Redis: {'OK' if redis_ok else 'FAILED'}")

    if not (db_ok and redis_ok):
        raise SystemExit(1)

# ------------------------------------------------------------------
# Cache commands group
# ------------------------------------------------------------------
@click.group(name="cache")
def cache_group():
    """Cache management commands."""
    pass

@cache_group.command("clear")
@click.option("--stats-only", is_flag=True, help="Clear only statistics cache")
@with_appcontext
def cache_clear(stats_only):
    """Clear the cache (all or only stats)."""
    container = current_app.container
    clear_cache_logic(container.get_cache(), stats_only=stats_only)

@cache_group.command("stats")
@with_appcontext
def cache_stats():
    """Show cache statistics (hits, memory, etc.)."""
    container = current_app.container
    info = cache_info_logic(container.get_cache())
    if "error" in info:
        click.echo(f"{info['error']}")
    else:
        click.echo("\n\t\t\tCache Statistics:")
        click.echo("=" * 80)
        for key, value in info.items():
            click.echo(f"\t\t\t{key}: {value}")
        click.echo("=" * 80)

# ------------------------------------------------------------------
# Link commands group
# ------------------------------------------------------------------
@click.group(name="link")
def link_group():
    """Manage individual short links."""
    pass


@link_group.command("delete")
@click.argument("short_code")
@with_appcontext
def link_delete(short_code):
    """Delete a short link by its code."""
    container = current_app.container
    context = RequestContext(request_id="cli-delete")
    use_case = container.get_delete_link_use_case()

    click.echo("=" * 80)
    deleted = delete_link_logic(use_case, short_code, context)
    if deleted:
        click.echo(f"\t\t\tLink '{short_code}' has been deleted")
    else:
        click.echo(f"Link '{short_code}' not found or invalid.", err=True)
    click.echo("=" * 80)
    if not deleted:
        raise SystemExit(1)

@link_group.command("info")
@click.argument("short_code")
@with_appcontext
def link_info(short_code):
    """Show information about a short link."""

    container = current_app.container
    context = RequestContext(request_id="cli-info")
    use_case = container.get_get_link_info_use_case()
    info = link_info_logic(use_case, short_code, context)
    
    if info:
        click.echo(f"\n\t\t\tLink: {info['short_code']}")
        click.echo("=" * 80)
        click.echo(f"\t\t\tOriginal URL: {info['original_url']}")
        click.echo(f"\t\t\tClicks: {info['clicks']}")
        click.echo(f"\t\t\tCreated: {info['created_at']}")
        click.echo(f"\t\t\tLast accessed: {info['last_accessed'] or 'never'}")
    else:
        click.echo("=" * 80)
        click.echo(f"\t\t\tLink '{short_code}' not found.", err=True)
    click.echo("=" * 80)
    if not info:
        raise SystemExit(1)


@link_group.command("list")
@click.option("--limit", default=10, help="Number of recent links to show")
@with_appcontext
def link_list(limit):
    """List the most recent short links."""
    container = current_app.container
    context = RequestContext(request_id="cli-list")
    use_case = container.get_get_recent_links_use_case()
    links = list_links_logic(use_case, limit, context)

    if not links:
        click.echo("=" * 80)
        click.echo("\t\t\tNo links found.")
    else:
        click.echo(f"\n\t\t\tRecent {len(links)} links:")
        click.echo("=" * 80)
        for link in links:
            click.echo(f"\t\t\t{link['short_code']} - {link['clicks']} clicks - {link['created_at'][:10]}")
    click.echo("=" * 80)

@link_group.command("create")
@click.option("--url", required=True, help="Original URL to shorten")
@click.option(
    "--code",
    default=None,
    help=(
        "Custom short code (6-10 of A-Z a-z 0-9 _ -), except the handful "
        "the service answers to itself. Generated if omitted."
    ),
)
@with_appcontext
def link_create(url, code):
    """Create a new short link.

    A URL this command already shortened gets its existing link back
    rather than a second one, and the report says so. --code is then not
    issued, which is reported too. Links made by a signed-in account or
    by a web visitor are a separate matter and are never returned here.
    """
    # This docstring is what `--help` prints, so the reasoning lives here
    # rather than in it.
    #
    # The command said "Short link created successfully!" either way --
    # with "Is new: False" four lines below it, contradicting the headline
    # nobody reads past. An operator shortening a URL a colleague had
    # already shortened was told they had just made the link they were in
    # fact being handed. It matters beyond the wording: the code printed
    # is then not the one `--code` asked for, and a script reading the
    # headline as "this is mine now" would delete a link somebody else is
    # using.
    # An empty --code is a script whose variable did not get filled in --
    # `--code "$CODE"` is how it arrives -- and `if code and ...` cannot
    # tell it from the option not being passed at all, so a code would be
    # generated, nothing said, and the script would go on with a code it
    # did not choose.
    #
    # Refused rather than treated as "generate one": that reading is
    # available by leaving the option out, and it is not the one an
    # operator who typed --code meant.
    if code is not None and not code.strip():
        click.echo(
            "Error: --code was given an empty value. Leave the option out "
            "to have a code generated, or pass the code you want.",
            err=True,
        )
        raise SystemExit(1)

    from link_shortener.infrastructure.cli.commands.link import create_link as create_link_logic
    container = current_app.container
    context = RequestContext(request_id="cli-create")
    use_case = container.get_create_short_link_use_case()

    try:
        result = create_link_logic(use_case, url, context, code)
        headline = (
            "Short link created successfully!"
            if result["is_new"]
            else "This URL was already shortened -- returning that link."
        )
        click.echo("=" * 80)
        click.echo(f"\t\t\t{headline}")
        click.echo(f"\t\t\tShort code: {result['short_code']}")
        click.echo(f"\t\t\tOriginal URL: {result['original_url']}")
        click.echo(f"\t\t\tShort URL: {result['short_url']}")
        click.echo(f"\t\t\tIs new: {result['is_new']}")
        click.echo("=" * 80)

        # Said out loud, on stderr, because nothing else in the report
        # mentions it. Deduplication is decided before the chosen code is
        # looked at, so a code that was explicitly asked for is simply
        # not used -- and the command still exits 0.
        #
        # What the code does instead is deliberately not stated. This
        # path never looked at it, so whether it is free or belongs to
        # somebody else is not known here: saying "it remains free" was
        # wrong against a code already held by another link,
        # which the same argument on a new URL refuses outright.
        if code and result["short_code"] != code:
            click.echo(
                f"Note: --code {code} was not issued. This URL was already "
                f"shortened as {result['short_code']}, and that is the link "
                f"above; nothing was created for {code}.",
                err=True,
            )
    except Exception as e:
        click.echo(f"Error creating link: {e}", err=True)
        raise SystemExit(1)

# ------------------------------------------------------------------
# Security commands group
# ------------------------------------------------------------------
@click.group(name="security")
def security_group():
    """Security management commands (secrets, users, roles, tokens)"""
    pass

@security_group.command("generate-secrets")
def security_generate_secrets():
    """Generate new SECRET_KEY and SHORT_CODE_PEPPER."""
    from link_shortener.infrastructure.cli.commands.security import generate_secrets as gen_secrets
    secrets = gen_secrets()
    click.echo("=" * 80)
    click.echo("Generated secrets (add to .env file):")
    click.echo(f"SECRET_KEY={secrets['SECRET_KEY']}")
    click.echo(f"SHORT_CODE_PEPPER={secrets['SHORT_CODE_PEPPER']}")
    click.echo("=" * 80)
    click.echo("\nWARNING: Keep these values secure and never commit them to version control.")

@security_group.command("check-secrets")
def security_check_secrets():
    """Check if required secrets are configured."""
    from link_shortener.infrastructure.cli.commands.security import check_secrets
    status = check_secrets()
    click.echo("\nSecret Configuration Status:")
    click.echo("=" * 40)
    for secret, configured in status.items():
        status_text = "OK" if configured else "MISSING"
        click.echo(f"{secret}: {status_text}")
    click.echo("=" * 40)

    if not all(status.values()):
        click.echo("\nRun 'flask security generate-secrets' to generate missing secrets.")
        raise SystemExit(1)

@security_group.command("list-users")
@with_appcontext
def security_list_users():
    """List all users with their roles."""
    from link_shortener.infrastructure.cli.commands.security import list_users
    container = current_app.container
    users = list_users(container.get_uow_factory())

    if not users:
        click.echo("No users found.")
        return

    click.echo(f"\n{'ID':<36} {'Email':<30} {'Active':<8} {'Roles'}")
    click.echo("=" * 100)
    for user in users:
        roles_str = ", ".join(user["roles"]) if user["roles"] else "none"
        click.echo(f"{user['id']:<36} {user['email']:<30} {str(user['is_active']):<8} {roles_str}")

@security_group.command("list-roles")
@with_appcontext
def security_list_roles():
    """List all roles with their permissions."""
    from link_shortener.infrastructure.cli.commands.security import list_roles
    container = current_app.container
    roles = list_roles(container.get_uow_factory())

    if not roles:
        click.echo("No roles found.")
        return

    click.echo(f"\n{'ID':<36} {'Name':<20} {'Description':<30} {'Permissions'}")
    click.echo("=" * 120)
    for role in roles:
        perms_str = ", ".join(role["permissions"]) if role["permissions"] else "none"
        click.echo(f"{role['id']:<36} {role['name']:<20} {(role['description'] or ''):<30} {perms_str}")

@security_group.command("reset-password")
@click.option("--email", prompt=True, help="User email")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True, help="New password")
@with_appcontext
def security_reset_password(email, password):
    """Reset a user's password."""
    from link_shortener.infrastructure.cli.commands.security import reset_password
    container = current_app.container
    user_service = container.get_user_management_service()

    if reset_password(container.get_uow_factory(), user_service, email, password):
        click.echo(f"Password reset successfully for {email}")
    else:
        click.echo(f"User {email} not found.", err=True)
        raise SystemExit(1)

@security_group.command("validate-token")
@click.argument("token")
@with_appcontext
def security_validate_token(token):
    """Validate a JWT token and show its claims."""
    from link_shortener.infrastructure.cli.commands.security import validate_token
    container = current_app.container
    auth_service = container.get_authentication_service()
    
    result = validate_token(auth_service, token)

    if result["valid"]:
        # The type is named in the verdict, not buried among the claims. A
        # bare "VALID" said the same thing about an access token and a
        # refresh token, and they are not interchangeable: a refresh token
        # opens no endpoint, and reading "VALID" against one was a way to
        # conclude the opposite.
        token_type = result.get("type") or "unknown"
        click.echo(f"\nToken is VALID (type: {token_type})")
        click.echo("=" * 40)
        click.echo(f"User ID: {result.get('user_id')}")
        click.echo(f"Email: {result.get('email')}")
        click.echo(f"Roles: {', '.join(result.get('roles', []))}")
        click.echo(f"Expires: {result.get('exp')}")
        # Вид токена, а не пароль.
        if token_type != "access":  # nosec B105
            click.echo(
                f"\nNote: this is a {token_type} token -- it authenticates "
                "no request. Only an access token does."
            )
    else:
        click.echo(f"\nToken is INVALID: {result.get('error')}", err=True)
        raise SystemExit(1)

# ------------------------------------------------------------------
# Top-level commands
# ------------------------------------------------------------------
@click.command("create-admin")
@click.option("--email", default=None, help="Admin email")
@click.option("--password", default=None, help="Admin password")
@click.option(
    "--non-interactive",
    is_flag=True,
    help="Refuse rather than prompt when --email or --password is missing",
)
@with_appcontext
def create_admin(email, password, non_interactive):
    """Create an admin user.

    Asks for --email and --password if they are not given, unless
    --non-interactive is passed, in which case it refuses instead. A
    password it asks for is typed twice; one given as --password is not.
    """
    # This docstring is what `--help` prints, so the reasoning lives here
    # rather than in it.
    #
    # The prompts are issued in the body rather than by
    # `click.option(prompt=...)`, which is what makes `--non-interactive`
    # mean anything. Declared as a prompting option, `--email` is asked for
    # before the body runs and before any flag can be consulted: the flag
    # was read by nothing at all, and a provisioning script that passed it
    # stops at "Email:" and dies on the closed stdin with
    # `Aborted!` -- the one situation it exists to prevent. Its help said
    # "Skip confirmation prompts", which named something that was never
    # here either: this command asks for values, and confirms nothing.
    missing = [
        name
        for name, value in (("--email", email), ("--password", password))
        if not value
    ]
    if missing and non_interactive:
        # Named together, not one per run: a script fixed on the first
        # complaint would come back only to be stopped by the second.
        click.echo(
            f"{' and '.join(missing)} required with --non-interactive",
            err=True,
        )
        raise SystemExit(1)

    if not email:
        email = click.prompt("Email")
    if not password:
        # Asked twice, like `create-user` and `security reset-password`
        # next door. The input is hidden, so a typo is invisible and
        # nothing downstream can catch one: the account is created, the
        # command reports success, and the password that was meant is not
        # the password that was stored. There is no recovery either --
        # signing in needs the password, and resetting it needs an admin.
        #
        # Only the prompted path confirms. A `--password` on the command
        # line was read from a script or a secret store, is visible to
        # whoever wrote it, and asking a script to type it twice is how
        # `--non-interactive` gets stuck at a prompt again.
        password = click.prompt(
            "Password", hide_input=True, confirmation_prompt=True
        )

    container = current_app.container
    user_service = container.get_user_management_service()
    uow_factory = container.get_uow_factory()
    try:
        admin_email = create_admin_logic(
            uow_factory=uow_factory,
            user_service=user_service,
            role_name="admin",
            email=email,
            password=password,
        )
        click.echo(f"Admin user {admin_email} created successfully.")
    except Exception as e:
        click.echo(f"Failed to create admin: {e}", err=True)
        raise SystemExit(1)


@click.command("create-user")
@click.option("--email", prompt=True, help="User email")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True, help="User password")
@click.option("--role", required=True, help="Role name to assign (e.g., admin, user, analyst)")
@with_appcontext
def create_user(email, password, role):
    """Create a new user with a specified role."""
    from link_shortener.infrastructure.cli.commands.admin import create_user as create_user_logic
    container = current_app.container
    user_service = container.get_user_management_service()
    uow_factory = container.get_uow_factory()
    try:
        result = create_user_logic(
            uow_factory=uow_factory,
            user_service=user_service,
            email=email,
            password=password,
            role_names=[role],
        )
        click.echo(f"User {result['email']} created successfully (active: {result['is_active']}).")
    except Exception as e:
        click.echo(f"Failed to create user: {e}", err=True)
        raise SystemExit(1)

# ------------------------------------------------------------------
# Alembic commands group
# ------------------------------------------------------------------
@click.group(name="alembic")
def alembic_group():
    """Alembic migration management (status, history, upgrade, downgrade, migrate)"""
    pass


def _configured_database_url() -> str:
    """
    Return the database URL the running application is configured with.

    Alembic runs in a subprocess that inherits the ambient environment, not
    the application's configuration. Handing the URL over keeps the two in
    agreement; without it a command issued under one profile could report on,
    or migrate, the database of another.

    Returns:
        SQLAlchemy-compatible database URL.
    """
    return current_app.container.config.get_database_url()


def _echo_target() -> str:
    """
    Announce which database the command is about to work on.

    A migration command that says only "Migrations applied." leaves the
    operator no way to tell a real upgrade from a no-op against the wrong
    database. The password is masked -- this goes to a terminal and often
    into a deployment log.

    Returns:
        The database URL to hand to alembic.
    """
    url = _configured_database_url()
    click.echo(f"Database: {current_app.container.config.display_database_url}")
    return url


def _require_alembic_enabled() -> str:
    """
    Refuse a schema change when the schema is not managed by Alembic.

    ``USE_ALEMBIC`` picks one of two ways to build the schema, and the two
    must not be mixed: ``flask db init`` creates the tables straight from
    the models and writes no revision, so a database built that way and
    then migrated tries to create tables that already exist. ``db init``,
    ``db drop`` and ``db migrate`` have always honoured the flag; this
    group did not, so the very path the flag exists to close stayed open.

    Returns:
        The database URL to hand to alembic.

    Raises:
        SystemExit: If Alembic is switched off for this configuration.
    """
    if not current_app.config.get("USE_ALEMBIC", True):
        click.echo(
            "USE_ALEMBIC is disabled. The schema is managed from the models "
            "-- use 'flask db init' to create it and 'flask db drop' to "
            "remove it.",
            err=True,
        )
        raise SystemExit(1)
    return _echo_target()


@alembic_group.command("status")
@with_appcontext
def alembic_status():
    """Show current migration status."""
    from link_shortener.infrastructure.cli.commands.alembic import AlembicCommands
    success, output = AlembicCommands.status(_echo_target())
    click.echo(output, err=not success)
    if not success:
        raise SystemExit(1)

@alembic_group.command("history")
@click.option("--revision", "-r", default=None, help="Show history from revision")
@with_appcontext
def alembic_history(revision):
    """Show migration history."""
    from link_shortener.infrastructure.cli.commands.alembic import AlembicCommands
    success, output = AlembicCommands.history(revision, _echo_target())
    click.echo(output, err=not success)
    if not success:
        raise SystemExit(1)

@alembic_group.command("upgrade")
@click.argument("revision", default="head")
@with_appcontext
def alembic_upgrade(revision):
    """Apply migrations to target revision."""
    from link_shortener.infrastructure.cli.commands.alembic import AlembicCommands
    success, output = AlembicCommands.upgrade(revision, _require_alembic_enabled())
    click.echo(output)
    if not success:
        raise SystemExit(1)

# ignore_unknown_options: relative revisions start with a dash ("-1", "-2"),
# and Click would otherwise reject them as unknown options before the command
# body ever runs, making the documented `alembic downgrade -1` impossible.
@alembic_group.command(
    "downgrade", context_settings={"ignore_unknown_options": True}
)
@click.argument("revision", default="-1")
@with_appcontext
def alembic_downgrade(revision):
    """Rollback migrations to target revision."""
    from link_shortener.infrastructure.cli.commands.alembic import AlembicCommands
    success, output = AlembicCommands.downgrade(revision, _require_alembic_enabled())
    click.echo(output)
    if not success:
        raise SystemExit(1)

@alembic_group.command("migrate")
@click.argument("message")
@with_appcontext
def alembic_migrate(message):
    """Create new migration with auto-generated changes."""
    from link_shortener.infrastructure.cli.commands.alembic import AlembicCommands
    success, output = AlembicCommands.migrate(message, _require_alembic_enabled())
    click.echo(output)
    if not success:
        raise SystemExit(1)

# ------------------------------------------------------------------
# Registration helper
# ------------------------------------------------------------------
def register_flask_commands(app):
    """
    Register all CLI commands with the Flask application.

    This function is called during application factory initialization
    to make the commands available via the `flask` CLI.

    Args:
        app: Flask application instance.
    """
    app.cli.add_command(db_group)
    app.cli.add_command(stats_group)
    app.cli.add_command(maintenance_group)
    app.cli.add_command(link_group)
    app.cli.add_command(cache_group)
    app.cli.add_command(alembic_group)
    app.cli.add_command(security_group)
    app.cli.add_command(create_admin)
    app.cli.add_command(create_user)
