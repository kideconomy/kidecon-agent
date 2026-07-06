import logging
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import yaml

import click
import keyring

from wrappers.hub_client import HubClient, KEYRING_SERVICE, KEY_JWT, KEY_AGENT_ID
from wrappers.sandbox import UserScriptSandbox

logger = logging.getLogger(__name__)

CONFIG_PATH = "kidecon.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


@click.group()
def cli():
    """KidEconomy Agent CLI — lifecycle management for your KidEconomy agent."""


@cli.command()
@click.option("--name", prompt="Agent name", help="Name for this agent")
def setup(name):
    """First-time install: keyring, registration with hub."""
    config = load_config()
    client = HubClient(hub_url=config["hub_url"])
    jwt = client.register(name=name, platform="cli")
    click.echo(f"Agent registered. JWT stored in keyring.")
    click.echo(f"Agent ID: {client.agent_id}")


@cli.command()
def start():
    """Launch Hermes with KidEconomy config."""
    click.echo("Starting Hermes... (stub — Hermes integration TBD)")
    # Actual: subprocess.Popen(["hermes", "--config", "kidecon.yaml"])


@cli.command()
def stop():
    """Graceful shutdown of the agent."""
    click.echo("Stopping agent... (stub)")


@cli.command()
def status():
    """Check if agent is running and connected to hub."""
    try:
        config = load_config()
        client = HubClient(hub_url=config["hub_url"])
        tier = client.get_tier()
        jwt = keyring.get_password(KEYRING_SERVICE, KEY_JWT)
        agent_id = keyring.get_password(KEYRING_SERVICE, KEY_AGENT_ID)
        click.echo(f"Agent ID: {agent_id}")
        click.echo(f"Registered: {'yes' if jwt else 'no'}")
        click.echo(f"Tier: {tier}")
    except Exception as e:
        click.echo(f"Not connected: {e}")


@cli.command()
def update():
    """Pull latest Hermes + KidEconomy config."""
    click.echo("Checking for updates... (stub)")
    # Actual: re-run install.sh with latest version tag


@cli.group()
def key():
    """Manage API keys in keyring."""


@key.command("add")
@click.option("--name", prompt="Key name (e.g. openrouter)", help="Name of the API key")
@click.option("--value", prompt="API key value", hide_input=True, help="The API key")
def key_add(name, value):
    keyring.set_password(KEYRING_SERVICE, f"api_key_{name}", value)
    click.echo(f"Key '{name}' stored.")


@key.command("list")
def key_list():
    # keyring doesn't enumerate easily; show known keys
    known = ["openrouter", "hub_jwt", "agent_id"]
    for k in known:
        v = keyring.get_password(KEYRING_SERVICE, k if k.startswith("api_key_") else k)
        masked = f"{v[:4]}...{v[-4:]}" if v and len(v) > 8 else ("***" if v else "(not set)")
        click.echo(f"  {k}: {masked}")


@cli.command()
def tier():
    """Show current capability tier."""
    config = load_config()
    client = HubClient(hub_url=config["hub_url"])
    click.echo(f"Current tier: {client.get_tier()}")


@cli.group()
def skills():
    """Manage installed skills."""


@skills.command("list")
def skills_list():
    """Show installed skills."""
    click.echo("Installed skills: (none yet)")


@skills.command("browse")
@click.argument("query", required=False)
def skills_browse(query):
    """Query hub skill directory."""
    config = load_config()
    client = HubClient(hub_url=config["hub_url"])
    results = client.discover_skills(query or "")
    if not results:
        click.echo("No skills found.")
    for skill in results:
        click.echo(f"  {skill['name']} v{skill['version']} [{skill.get('category', 'uncategorized')}]")


if __name__ == "__main__":
    cli()
