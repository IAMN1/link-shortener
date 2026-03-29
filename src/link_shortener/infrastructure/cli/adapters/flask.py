import click
from flask import current_app
from flask.cli import with_appcontext

from ..commands.database import init_db as init_db_logic
from ..commands.database import drop_db as drop_db_logic
from ..commands.database import seed_db as seed_db_logic
from ..commands.database import check_db_connection as check_db_logic
from ..commands.database import migrate_db as migrate_db_logic
from ..commands.stats import refresh_stats as refresh_stats_logic
from ..commands.stats import get_stats as get_stats_logic
from ..commands.maintenance import clean_expired_links as clean_expired_logic
from ..commands.link import delete_link as delete_link_logic
from ..commands.link import get_link_info as link_info_logic
from ..commands.link import list_links as list_links_logic
from ..commands.cache import check_redis_connection as check_redis_logic
from ..commands.cache import get_cache_info as cache_info_logic
from ..commands.cache import clear_cache as clear_cache_logic
from ..commands.security import generate_secrets as generate_secrets_logic
from ..commands.admin import create_admin as create_admin_logic


# ------------------------------------------------------------------
# Группа DB-команд
# ------------------------------------------------------------------
@click.group(name="db")
def db_group():
    """Database management commands"""
    pass

@db_group.command("init")
@with_appcontext
def init_db():
    "Create database tables"
    container = current_app.container
    db_manager = container.get_db_manager()
    init_db_logic(db_manager)

@db_group.command("drop")
@click.option("--yes", is_flag=True, help="Confirm dropping all tables")
@with_appcontext
def drop_db(yes):
    """Drop all database tables (DANGEROUS)!!!"""
    if not yes:
        click.confirm("Are you sure you want to drop all tables?", abort=True)
    container = current_app.container
    db_manager = container.get_db_manager()
    drop_db_logic(db_manager, confirm=True)

@db_group.command("seed")
@click.option("--count", default=10, help="Number of test links to create")
@with_appcontext
def seed_db(count):
    """Fill database with test data"""
    container = current_app.container
    created = seed_db_logic(
        container.get_repository(),
        container.get_shortening_policy(),
        count=count
    )
    click.echo(f"Created {created} test links")

@db_group.command("check")
@with_appcontext
def check_db():
    """Check database connection"""
    container = current_app.container
    if check_db_logic(container.get_db_manager()):
        click.echo("Database connection is healthy.")
    else:
        click.echo("Database connection failed.", err=True)

@db_group.command("migrate")
@with_appcontext
def migrate_db():
    """Apply database migrations (placeholder – to be replaced with Alembic)."""
    container = current_app.container
    migrate_db_logic(container.get_db_manager())

# ------------------------------------------------------------------
# Группа Stats-команд
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
    for i, (code, clicks, url) in enumerate(stats['popular_links'], 1):
        short_url = f"{code}"
        click.echo(f"\t\t\t{i}. {short_url} - {clicks} clicks")
    click.echo("=" * 80)

@stats_group.command("refresh")
@with_appcontext
def stats_refresh():
    """Force refresh of cached statistics"""
    container = current_app.container
    stats = refresh_stats_logic(container.get_get_service_stats_use_case())
    click.echo("\n\t\t\tSTATISTIC REFRESHED IN CACHE:")
    click.echo("=" * 80)
    click.echo(f"\t\t\tTotal URL's: {stats['total_urls']}")
    click.echo(f"\t\t\tTotal clicks: {stats['total_clicks']}")
    click.echo(f"\t\t\tAvg clicks per URL: {stats['avg_clicks_per_url']}")
    click.echo("=" * 80)

# ------------------------------------------------------------------
# Группа Maintenance-команд
# ------------------------------------------------------------------
@click.group(name="maintenance")
def maintenance_group():
    """Maintenance and health check commands."""
    pass

@maintenance_group.command("clean-expired")
@click.option("--days", default=30, help="Delete links older than N days")
@with_appcontext
def clean_expired(days):
    """Delete links that have not been accessed for N days."""
    container = current_app.container
    deleted = clean_expired_logic(container.get_repository(), days=days)
    click.echo(f"Deleted {deleted} expired links.")

@maintenance_group.command("check-redis")
@with_appcontext
def check_redis():
    """Check Redis connection (if Redis cache is used)."""
    container = current_app.container
    if check_redis_logic(container.get_cache()):
        click.echo("Redis connection is healthy.")
    else:
        click.echo("Redis not used or connection failed.")

@maintenance_group.command("check-db")
@with_appcontext
def check_db_maintenance():
    """Check database connection."""
    container = current_app.container
    if check_db_logic(container.get_db_manager()):
        click.echo("Database connection is healthy.")
    else:
        click.echo("Database connection failed.", err=True)

# ------------------------------------------------------------------
# Группа Cache-команд
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
# Группа Link-команд
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
    
    click.echo("=" * 80)
    if delete_link_logic(container.get_repository(), short_code):
        click.echo(f"\t\t\tLink '{short_code}' deleted.")
    else:
        click.echo(f"Link '{short_code}' not found or invalid.")
    click.echo("=" * 80)

@link_group.command("info")
@click.argument("short_code")
@with_appcontext
def link_info(short_code):
    """Show information about a short link."""
    container = current_app.container
    info = link_info_logic(container.get_repository(), short_code)
    
    if info:
        click.echo(f"\n\t\t\tLink: {info['short_code']}")
        click.echo("=" * 80)
        click.echo(f"\t\t\tOriginal URL: {info['original_url']}")
        click.echo(f"\t\t\tClicks: {info['clicks']}")
        click.echo(f"\t\t\tCreated: {info['created_at']}")
        click.echo(f"\t\t\tLast accessed: {info['last_accessed'] or 'never'}")
    else:
        click.echo("=" * 80)
        click.echo(f"\t\t\tLink '{short_code}' not found.")
    click.echo("=" * 80)


@link_group.command("list")
@click.option("--limit", default=10, help="Number of recent links to show")
@with_appcontext
def link_list(limit):
    """List the most recent short links."""
    container = current_app.container
    links = list_links_logic(container.get_repository(), limit=limit)

    if not links:
        click.echo("=" * 80)
        click.echo("\t\t\tNo links found.")
    else:
        click.echo(f"\n\t\t\tRecent {len(links)} links:")
        click.echo("=" * 80)
        for link in links:
            click.echo(f"\t\t\t{link['short_code']} - {link['clicks']} clicks - {link['created_at'][:10]}")
    click.echo("=" * 80)
# ------------------------------------------------------------------
# Отдельные команды верхнего уровня
# ------------------------------------------------------------------
@click.command("generate-secrets")
def generate_secrets():
    """Generate new SECRET_KEY and SHORT_CODE_PEPPER."""
    secrets = generate_secrets_logic()
    click.echo("=" * 80)
    click.echo(f"SECRET_KEY={secrets['SECRET_KEY']}")
    click.echo(f"SHORT_CODE_PEPPER={secrets['SHORT_CODE_PEPPER']}")
    click.echo("=" * 80)


@click.command("create-admin")
@click.option("--email", prompt=True, help="Admin email")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True, help="Admin password")
def create_admin(email, password):
    """Create an admin user (placeholder – requires user model)."""
    if create_admin_logic(email, password):
        click.echo(f"Admin user {email} created.")
    else:
        click.echo("Failed to create admin.")


# ------------------------------------------------------------------
# Регистрация всех комманд
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
    app.cli.add_command(generate_secrets)
    app.cli.add_command(create_admin)