import logging
import os
import pathlib
import subprocess
import sys
import contextlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import typer
import yaml
import keyring
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from wrappers.hub_client import KEY_AGENT_ID
from wrappers.hub_client import KEY_JWT
from wrappers.hub_client import KEYRING_SERVICE
from wrappers.hub_client import HubClient
from wrappers.sandbox import APPROVED_FILE as SANDBOX_APPROVED_FILE
from wrappers.sandbox import SCRIPTS_DIR as SANDBOX_SCRIPTS_DIR

logger = logging.getLogger(__name__)

app = typer.Typer(help="KidEconomy Agent CLI — lifecycle management for your KidEconomy agent.")
console = Console()


def _do_splash(ctx: typer.Context, *, no_splash: bool = False) -> None:
    import select
    import time

    from rich.live import Live
    from rich.panel import Panel
    from rich.text import Text

    if no_splash or not sys.stdout.isatty():
        typer.echo(ctx.get_help())
        return

    boot = [
        ("[bold green]> The world hums with possibility...[/bold green]", 0.35),
        ("[bold yellow]> Light finds its way through the code...[/bold yellow]", 0.4),
        ("[bold green]> Your companion awakens...[/bold green]", 0.5),
        ("[bold green]> The road ahead is open.[/bold green]", 0.3),
    ]

    rendered = ""
    with Live(refresh_per_second=12, console=console) as live:
        for line, delay in boot:
            rendered += line + "\n"
            live.update(Text.from_markup(rendered))
            time.sleep(delay)

    console.print()
    try:
        import pyfiglet

        title = pyfiglet.figlet_format("KidEconomy", font="slant")
    except Exception:
        title = "KidEconomy Agent"

    logo = Text(f"\n{title.rstrip()}\n", style="bold yellow")
    console.print(Panel(logo, border_style="green", expand=False, padding=(0, 2)))
    console.print()

    console.print("[bold yellow]Are you ready to go! >_ [/bold yellow]", end="", highlight=False)
    answer = ""
    if sys.stdin.isatty():
        rlist, _w, _x = select.select([sys.stdin], [], [], 2.0)
        if rlist:
            answer = sys.stdin.readline().strip().lower()
            time.sleep(0.15)
        else:
            console.print()
            console.print("[dim](auto-proceeding...)[/dim]")
    else:
        console.print()
    if answer in ("n", "no", "nah", "nope", "exit"):
        console.print("[dim]The adventure waits. See you later, hero.[/dim]")
        return

    typer.echo(ctx.get_help())


def _apply_no_color(no_color: bool) -> None:
    global console
    if no_color or os.environ.get("NO_COLOR") or os.environ.get("KIDECON_PLAIN"):
        console = Console(color_system=None, highlight=False, force_terminal=False)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    no_color: bool = typer.Option(False, "--no-color", help="Disable color and rich formatting."),
    no_splash: bool = typer.Option(False, "--no-splash", help="Skip the opening animation."),
):
    """KidEconomy Agent CLI — lifecycle management for your KidEconomy agent."""
    _apply_no_color(no_color)
    if ctx.invoked_subcommand is None:
        _do_splash(ctx, no_splash=no_splash or no_color)
        raise typer.Exit

CONFIG_PATH = "kidecon.yaml"


def load_config() -> dict:
    msg = "kidecon.yaml not found. Place it at ~/.config/kidecon/kidecon.yaml or in the current directory."
    candidates: list[pathlib.Path] = [
        pathlib.Path(CONFIG_PATH),
        pathlib.Path.home() / ".config" / "kidecon" / "kidecon.yaml",
    ]
    for candidate in candidates:
        if candidate.exists():
            return yaml.safe_load(candidate.read_bytes())
    raise FileNotFoundError(msg)


def hub_client() -> HubClient:
    config = load_config()
    return HubClient(
        hub_url=config["hub_url"],
        kideconomy_api_url=config.get("kideconomy_api_url", ""),
    )


def require_auth() -> HubClient:
    """Guard for commands that need a registered agent.

    Returns an authenticated HubClient or exits with an error if
    no JWT is found in the keyring.
    """
    client = hub_client()
    if not client.jwt:
        console.print("[bold red]✗[/bold red] Not registered. Run [bold]kidecon setup[/bold] first.")
        raise typer.Exit(code=1)
    return client


# ------------------------------------------------------------------
# init
# ------------------------------------------------------------------
@app.command()
def init(
    hub: str = typer.Option(
        "https://hub.kidecon.me", "--hub", help="Hub URL (default: https://hub.kidecon.me)",
    ),
    kideconomy_api: str = typer.Option(
        "https://kidecon.me", "--kideconomy-api",
        help="KidEconomy app URL (default: https://kidecon.me)",
    ),
):
    """Initialize the agent config for a hub environment.

    Writes config to ~/.config/kidecon/kidecon.yaml and clears any
    existing registration so you can register fresh.

    Examples:
        kidecon init                                        # local dev
        kidecon init --hub https://hub.kidecon.me \\
                     --kideconomy-api https://kidecon.me   # production
    """
    import yaml as _yaml

    config_dir = pathlib.Path.home() / ".config" / "kidecon"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "kidecon.yaml"

    defaults = {
        "hub_url": hub,
        "kideconomy_api_url": kideconomy_api,
        "provider": "openrouter",
        "tool_gate": {
            "allow": [
                "file_read",
                "file_append_markdown",
                "hub_call",
                "user_script_execute",
                "message_user",
            ],
            "deny": ["file_write_binary", "shell_execute", "file_delete"],
            "require_approval": ["user_script_first_run", "hub_collaboration_request"],
        },
        "update_channel": "stable",
        "hermes_version": "v1.2.0",
    }

    config_path.write_text(_yaml.dump(defaults, default_flow_style=False))
    console.print(f"[bold green]✓[/bold green] Config written: {config_path}")
    console.print(f"  [bold cyan]Hub URL:[/bold cyan]          {hub}")
    console.print(f"  [bold cyan]KidEconomy URL:[/bold cyan]   {kideconomy_api}")

    local_config = pathlib.Path("kidecon.yaml")
    if local_config.exists():
        content = local_config.read_text()
        updated = _yaml.safe_load(content) or {}
        updated["hub_url"] = hub
        updated["kideconomy_api_url"] = kideconomy_api
        local_config.write_text(_yaml.dump(updated, default_flow_style=False))
        console.print(f"[bold green]✓[/bold green] Local config updated: {local_config.resolve()}")

    try:
        keyring.delete_password(KEYRING_SERVICE, KEY_JWT)
        keyring.delete_password(KEYRING_SERVICE, KEY_AGENT_ID)
        console.print("[bold green]✓[/bold green] Old registration cleared from keyring.")
    except Exception:
        logger.debug("No existing registration to clear — proceeding fresh.")

    console.print()
    console.print("Next: [bold]kidecon setup --name <name>[/bold]")


# ------------------------------------------------------------------
# setup
# ------------------------------------------------------------------
@app.command()
def setup(
    agent_display_name: str = typer.Option(
        ..., "--agent-display-name", prompt="Agent display name (e.g. johnnys-laptop)",
        help="Display label for this agent instance — NOT your username. "
             "Use something that identifies the machine or purpose "
             "(e.g. johnnys-laptop, ci-runner, dev-agent).",
    ),
    ke_username: str = typer.Option(
        None, "--ke-username",
        help="Your KidEconomy username (prompts if not provided). "
             "This is the account that owns this agent.",
    ),
):
    """Register this agent with the hub.

    Authenticates against KidEconomy using your username and password,
    then registers the agent with the hub. The hub verifies your KidEconomy
    token and links this agent to your account. Your password is never
    stored — it's used once to get a DRF token and then discarded.

    Examples:
        kidecon setup --agent-display-name my-laptop
        kidecon setup --agent-display-name my-laptop --ke-username johnny
    """
    import getpass

    config = load_config()
    ke_api_url = config.get("kideconomy_api_url", "")
    if not ke_api_url:
        console.print("[bold red]✗[/bold red] KidEconomy API URL not configured.")
        console.print("  Run [bold]kidecon init[/bold] first.")
        raise typer.Exit(code=1)

    client = HubClient(
        hub_url=config["hub_url"],
        kideconomy_api_url=ke_api_url,
    )

    if not ke_username:
        ke_username = typer.prompt("KidEconomy username")

    password = getpass.getpass("KidEconomy password: ")

    console.print(f"[dim]Authenticating against KidEconomy ({ke_api_url})...[/dim]")
    try:
        ke_token = client.fetch_ke_token(ke_username, password)
    except Exception as err:
        console.print(f"[bold red]✗[/bold red] KidEconomy authentication failed: {err}")
        raise typer.Exit(code=1) from err
    finally:
        del password

    console.print(f"[dim]Registering agent with hub ({config['hub_url']})...[/dim]")
    try:
        client.register(name=agent_display_name, ke_token=ke_token)
    except Exception as err:
        console.print(f"[bold red]✗[/bold red] Hub registration failed: {err}")
        raise typer.Exit(code=1) from err

    console.print()
    console.print("[bold green]✓[/bold green] Agent registered and linked to KidEconomy account.")
    console.print(f"  [bold cyan]Agent ID:[/bold cyan]        {client.agent_id}")
    console.print(f"  [bold cyan]KE user:[/bold cyan]        {ke_username}")
    console.print(f"  [bold cyan]Hub:[/bold cyan]            {config['hub_url']}")
    console.print(f"  [bold cyan]KidEconomy:[/bold cyan]     {ke_api_url}")
    console.print()
    console.print("JWT stored in keyring. Run [bold]kidecon status[/bold] to verify.")


# ------------------------------------------------------------------
# start
# ------------------------------------------------------------------
@app.command()
def start():
    """Launch the agent — verifies connectivity and JWT, marks online on hub."""
    import contextlib

    import httpx

    config = load_config()
    hub_url = config["hub_url"]

    try:
        r = httpx.get(f"{hub_url}/", timeout=5.0)
        r.raise_for_status()
    except Exception as err:
        console.print(f"[bold red]✗[/bold red] Hub unreachable at {hub_url}")
        raise typer.Exit(code=1) from err

    client = require_auth()

    try:
        tier = client.get_tier()
    except Exception as err:
        console.print("[bold red]✗[/bold red] JWT invalid or expired. Re-run '[bold]kidecon setup[/bold]'.")
        raise typer.Exit(code=1) from err

    with contextlib.suppress(Exception):
        client.update_status("online")

    console.print(f"[bold green]✓[/bold green] Agent ready — tier {tier}, connected to {hub_url}")


# ------------------------------------------------------------------
# stop
# ------------------------------------------------------------------
@app.command()
def stop():
    """Graceful shutdown — marks agent offline on hub and cleans up."""
    client = require_auth()
    try:
        client.update_status("offline")
        console.print("[bold green]✓[/bold green] Agent marked offline on hub.")
    except Exception:
        console.print("[bold yellow]⚠[/bold yellow] Could not reach hub to update status (already offline?).")


# ------------------------------------------------------------------
# status
# ------------------------------------------------------------------
@app.command()
def status():
    """Check if agent is running and connected to hub."""
    client = require_auth()
    try:
        tier = client.get_tier()
    except Exception as err:
        console.print(f"[bold red]✗[/bold red] JWT invalid or expired: {err}")
        raise typer.Exit(code=1) from err

    agent_id = keyring.get_password(KEYRING_SERVICE, KEY_AGENT_ID)
    ke_username = keyring.get_password(KEYRING_SERVICE, "kideconomy_username")
    config = load_config()

    console.print(f"[bold cyan]Agent ID:[/bold cyan]     {agent_id or '(not set)'}")
    console.print(f"[bold cyan]KE user:[/bold cyan]      {ke_username or '(none)'}")
    console.print("[bold cyan]Registered:[/bold cyan]   yes")
    console.print(f"[bold cyan]Tier:[/bold cyan]        {tier}")
    console.print(f"[bold cyan]Hub:[/bold cyan]         {config['hub_url']}")


# ------------------------------------------------------------------
# tier
# ------------------------------------------------------------------
@app.command()
def tier():
    """Show current capability tier."""
    client = require_auth()
    try:
        console.print(f"[bold cyan]Current tier:[/bold cyan] {client.get_tier()}")
    except Exception as err:
        console.print(f"[bold red]✗[/bold red] Could not read tier: {err}")
        raise typer.Exit(code=1) from err


# ------------------------------------------------------------------
# update
# ------------------------------------------------------------------
@app.command()
def update():
    """Update kidecon-agent to the latest version."""
    repo_dir = pathlib.Path(__file__).resolve().parent.parent
    git_dir = repo_dir / ".git"

    if not git_dir.exists():
        console.print("[bold yellow]⚠[/bold yellow] Not a git checkout. To update, re-run:")
        console.print(f"  [dim]cd {repo_dir} && bash install.sh[/dim]")
        return

    try:
        result = subprocess.run(
            ["git", "pull", "--ff-only"],
            capture_output=True,
            text=True,
            cwd=str(repo_dir),
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired as err:
        console.print("[bold red]✗[/bold red] git pull timed out after 30s.")
        raise typer.Exit(code=1) from err

    if result.returncode != 0:
        console.print("[bold red]✗[/bold red] git pull failed:")
        console.print(f"  [dim]{result.stderr.strip()}[/dim]")
        raise typer.Exit(code=1)

    console.print(f"[bold green]✓[/bold green] {result.stdout.strip() or 'Already up to date.'}")
    subprocess.run(
        ["pip", "install", str(repo_dir)],
        capture_output=True,
        timeout=60,
        check=False,
    )
    console.print("[bold green]✓[/bold green] Reinstalled from local checkout.")


# ------------------------------------------------------------------
# key
# ------------------------------------------------------------------
_key_app = typer.Typer(help="Manage API keys in keyring.")
app.add_typer(_key_app, name="key", help="Manage API keys in keyring.")


KEYS_INDEX_PATH = pathlib.Path.home() / ".config" / "kidecon" / "keys.json"


def _load_key_index() -> list[str]:
    """Load the list of user-added API key names from the index file."""
    if KEYS_INDEX_PATH.exists():
        import json

        return json.loads(KEYS_INDEX_PATH.read_text())
    return []


def _save_key_index(names: list[str]) -> None:
    KEYS_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    import json

    KEYS_INDEX_PATH.write_text(json.dumps(sorted(set(names)), indent=2))


INTERNAL_KEYS = ["hub_jwt", "agent_id", "kideconomy_username"]


def _mask(value: str | None) -> str:
    if value and len(value) > 8:
        return f"{value[:4]}...{value[-4:]}"
    if value:
        return "***"
    return "(not set)"


@_key_app.callback()
def key_main(
    no_color: bool = typer.Option(False, "--no-color", help="Disable color and rich formatting."),
):
    """Manage API keys in keyring."""
    _apply_no_color(no_color)


@_key_app.command("add")
def key_add(
    name: str = typer.Option(..., "--name", prompt="Key name (e.g. openrouter)", help="Name of the API key"),
    value: str = typer.Option(..., "--value", prompt="API key value", hide_input=True, help="The API key"),
):
    keyring.set_password(KEYRING_SERVICE, f"api_key_{name}", value)
    names = _load_key_index()
    if name not in names:
        names.append(name)
        _save_key_index(names)
    console.print(f"[bold green]✓[/bold green] Key '[bold]{name}[/bold]' stored.")


@_key_app.command("remove")
def key_remove(
    name: str = typer.Option(..., "--name", prompt="Key name to remove", help="Name of the API key to remove"),
):
    with contextlib.suppress(Exception):
        keyring.delete_password(KEYRING_SERVICE, f"api_key_{name}")
    names = _load_key_index()
    if name in names:
        names.remove(name)
        _save_key_index(names)
    console.print(f"[bold green]✓[/bold green] Key '[bold]{name}[/bold]' removed.")


@_key_app.command("list")
def key_list():
    api_keys = _load_key_index()
    table = Table(show_header=True, header_style="bold")
    table.add_column("Name")
    table.add_column("Value", overflow="fold")
    for k in INTERNAL_KEYS:
        v = keyring.get_password(KEYRING_SERVICE, k)
        table.add_row(k, _mask(v))
    for k in api_keys:
        v = keyring.get_password(KEYRING_SERVICE, f"api_key_{k}")
        table.add_row(k, _mask(v))
    console.print(table)


# ------------------------------------------------------------------
# skills
# ------------------------------------------------------------------
_skills_app = typer.Typer(help="Manage installed skills.")
app.add_typer(_skills_app, name="skills", help="Manage installed skills.")


@_skills_app.callback()
def skills_main(
    no_color: bool = typer.Option(False, "--no-color", help="Disable color and rich formatting."),
):
    """Manage installed skills."""
    _apply_no_color(no_color)


@_skills_app.command("list")
def skills_list():
    console.print("[dim]No skills installed yet.[/dim]")


@_skills_app.command("discover")
def skills_discover(
    query: str = typer.Argument(None, help="Search query"),
):
    """Query hub skill directory."""
    try:
        client = require_auth()
        results = client.discover_skills(query or "")
    except Exception as err:
        console.print(f"[bold red]✗[/bold red] Discovery failed: {err}")
        raise typer.Exit(code=1) from err

    if not results:
        console.print("[dim]No skills found.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Name")
    table.add_column("Version")
    table.add_column("Category")
    for s in results:
        table.add_row(s["name"], s["version"], s.get("category", "uncategorized"))
    console.print(table)


@_skills_app.command("submit")
def skills_submit(
    file: str = typer.Option(None, "--file", help="Path to skill JSON file"),
    inline: str = typer.Option(None, "--inline", help="Full skill JSON as a single argument"),
    name: str = typer.Option(None, "--name", help="Unique skill name"),
    version: str = typer.Option("1.0.0", "--version", help="Semantic version"),
    category: str = typer.Option(None, "--category", help="e.g. scheduling, analytics"),
    description: str = typer.Option(None, "--description", help="What the skill does"),
):
    """Submit a skill to the hub for review.

    Three modes: --file to load from JSON, --inline to pass JSON directly,
    or --name/--category/--description for interactive flags.
    """
    import json as _json

    definition = {}
    if file:
        data = _json.loads(pathlib.Path(file).read_text())
        name = data["name"]
        version = data.get("version", "1.0.0")
        category = data["category"]
        description = data["description"]
        definition = data.get("definition", {})
    elif inline:
        data = _json.loads(inline)
        name = data["name"]
        version = data.get("version", "1.0.0")
        category = data["category"]
        description = data["description"]
        definition = data.get("definition", {})
    else:
        if not name:
            name = typer.prompt("Skill name")
        if not category:
            category = typer.prompt("Category")
        if not description:
            description = typer.prompt("Description")

    try:
        client = require_auth()
        result = client.submit_skill(name, version, category, description, definition or None)
    except Exception as err:
        console.print(f"[bold red]✗[/bold red] Submission failed: {err}")
        raise typer.Exit(code=1) from err

    console.print(f"[bold green]✓[/bold green] Skill submitted: {result['skill_id']} [{result['status']}]")
    eval_data = result.get("evaluation", {})
    if eval_data:
        console.print(f"  [bold cyan]Domain:[/bold cyan]     {eval_data.get('resolved_domain_id', 'N/A')}")
        console.print(f"  [bold cyan]Action:[/bold cyan]     {eval_data.get('resolved_action_id', 'N/A')}")
        console.print(f"  [bold cyan]Confidence:[/bold cyan] {eval_data.get('confidence', 'N/A')}")


@_skills_app.command("mine")
def skills_mine(
    status: str = typer.Option(None, "--status", help="Filter by status (submitted, pending, live, rejected)"),
):
    """List my submitted skills."""
    try:
        client = require_auth()
        skills = client.my_skills(status)
    except Exception as err:
        console.print(f"[bold red]✗[/bold red] Could not list skills: {err}")
        raise typer.Exit(code=1) from err

    if not skills:
        console.print("[dim]No skills found.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Version")
    table.add_column("Status")
    table.add_column("Category")
    table.add_column("Domain")
    table.add_column("Confidence")
    for s in skills:
        ev = s.get("evaluation") or {}
        table.add_row(
            s["id"], s["name"], s["version"],
            s["approval_status"], s["category"],
            ev.get("resolved_domain_id", "-"),
            str(ev.get("confidence", "-")),
        )
    console.print(table)


@_skills_app.command("inspect")
def skills_inspect(
    skill_id: str = typer.Argument(..., help="UUID of the skill to inspect"),
):
    """Show full evaluation detail for a submitted skill."""
    try:
        client = require_auth()
        skills = client.my_skills()
    except Exception as err:
        console.print(f"[bold red]✗[/bold red] Could not fetch skills: {err}")
        raise typer.Exit(code=1) from err

    found = None
    for s in skills:
        if s["id"] == skill_id:
            found = s
            break

    if not found:
        console.print(f"[bold red]✗[/bold red] Skill {skill_id} not found in your submissions.")
        raise typer.Exit(code=1)

    console.print(f"[bold]Skill:[/bold] {found['name']} v{found['version']}")
    console.print(f"[bold]Status:[/bold] {found['approval_status']}")
    console.print(f"[bold]Submitted:[/bold] {found['submitted_at']}")
    ev = found.get("evaluation") or {}
    if ev:
        console.print("\n[bold]Evaluation:[/bold]")
        console.print(f"  [bold cyan]Normalized:[/bold cyan]  {ev.get('normalized_text', 'N/A')}")
        console.print(f"  [bold cyan]Domain:[/bold cyan]      {ev.get('resolved_domain_id', 'N/A')}")
        console.print(f"  [bold cyan]Action:[/bold cyan]      {ev.get('resolved_action_id', 'N/A')}")
        console.print(f"  [bold cyan]Confidence:[/bold cyan]   {ev.get('confidence', 'N/A')}")
        console.print(f"  [bold cyan]Matched on:[/bold cyan]   {ev.get('matched_on', 'N/A')}")
    else:
        console.print("[dim]No evaluation details available.[/dim]")


SKILL_CATEGORIES = {
    "scheduling": "Calendar, availability, reminders, bookings",
    "monitoring": "Error tracking, crash reporting, system health",
    "analytics": "Campaign data, metrics, KPIs, reports",
    "compliance": "Content safety, legal checks, policy enforcement",
    "documentation": "Knowledge base search, doc retrieval, references",
    "support": "Ticket creation, help desk, issue tracking",
    "communication": "Messaging, notifications, alerts, Discord",
}

SKILL_TEMPLATE = """{
  "name": "my-skill-name",
  "version": "1.0.0",
  "category": "scheduling",
  "description": "Describe what this skill does in third person. Example: Retrives calendar availability for a given agent and returns upcoming time slots.",
  "definition": {
    "inputs": {
      "type": "object",
      "properties": {
        "agent_id": {"type": "string", "description": "UUID of the target agent"},
        "window_hours": {"type": "integer", "description": "Hours ahead to scan"}
      },
      "required": ["agent_id"],
      "additionalProperties": false
    },
    "outputs": {
      "type": "object",
      "properties": {
        "slots": {"type": "array", "description": "Available time slots as ISO 8601", "items": {"type": "string"}},
        "total_count": {"type": "integer", "description": "Number of slots found"}
      }
    }
  }
}
"""

SKILL_GUIDE_PATH = pathlib.Path(__file__).resolve().parent.parent / "docs" / "SKILL_AUTHORING.md"


@_skills_app.command("categories")
def skills_categories():
    """List available skill category namespaces."""
    console.print("[bold]Available Categories[/bold]\n")
    for cat, desc in SKILL_CATEGORIES.items():
        console.print(f"  [bold cyan]{cat:20s}[/bold cyan] {desc}")


@_skills_app.command("template")
def skills_template(
    output: str = typer.Option("tmp/skill-template.json", "--output", "-o", help="Path to write the template"),
):
    """Generate a starter skill definition (JSON Schema format).

    Writes to tmp/skill-template.json by default (gitignored).
    Edit the file, then submit with 'kidecon skills submit --file'.
    """
    out_path = pathlib.Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(SKILL_TEMPLATE)
    console.print(f"[bold green]✓[/bold green] Template written to [bold]{out_path}[/bold]")
    console.print("[dim]Edit this file, then run: kidecon skills submit --file " + output + "[/dim]")


@_skills_app.command("guide")
def skills_guide(
    full: bool = typer.Option(False, "--full", help="Print the complete authoring guide"),
):
    """Print the skill authoring guide.

    Without --full, prints a summary and the path.
    With --full, prints the complete markdown document.
    """
    if SKILL_GUIDE_PATH.exists():
        content = SKILL_GUIDE_PATH.read_text()
        if full:
            print(content)
        else:
            for line in content.splitlines()[:30]:
                print(line)
            console.print(f"\n[dim][...] Full guide: {SKILL_GUIDE_PATH}[/dim]")
            console.print("[dim]Use --full to print the complete guide.[/dim]")
    else:
        console.print("[yellow]Skill authoring guide not found on disk.[/yellow]")
        console.print(f"[dim]Expected: {SKILL_GUIDE_PATH}[/dim]")


# ------------------------------------------------------------------
# doctor
# ------------------------------------------------------------------
@app.command()
def doctor():
    """Diagnose agent health — Python, keyring, config, hub, keys, sandbox."""
    import platform
    from datetime import UTC
    from datetime import datetime
    from pathlib import Path

    import httpx

    pass_mark = "[bold green]PASS[/bold green]"
    fail_mark = "[bold red]FAIL[/bold red]"
    warn_mark = "[bold yellow]WARN[/bold yellow]"

    console.print(Panel.fit("[bold cyan]KidEconomy Agent Doctor[/bold cyan]", border_style="cyan"))

    results: list[tuple[str, str, str, str]] = []

    def _add(group, label, status, detail, hint=""):
        results.append((group, label, status, detail, hint))

    # Keys required for the agent to operate.
    # Each entry: (keyring_name, description, required)
    required_keys: list[tuple[str, str, bool]] = [
        ("openrouter", "LLM inference via OpenRouter", True),
    ]

    py_ver = platform.python_version()
    py_ok = tuple(int(x) for x in py_ver.split(".")) >= (3, 11)
    _add("Environment", f"Python {py_ver}", "pass" if py_ok else "fail",
         "", "" if py_ok else "Install Python 3.11+ from https://python.org")

    try:
        import keyring as _kr
        kr_name = type(_kr.get_keyring()).__name__
        _add("Environment", "Keyring", "pass", kr_name)
    except Exception:
        _add("Environment", "Keyring", "fail", "not available",
             "Install a backend: pip install keyring[SecretStorage]")

    config_path: Path = Path.home() / ".config" / "kidecon" / "kidecon.yaml"
    if config_path.exists():
        _add("Environment", "Config", "pass", str(config_path))
        try:
            config = load_config()
            hub_url = config["hub_url"]
        except Exception as e:
            _add("Environment", "Config parse", "fail", str(e), "Check kidecon.yaml syntax")
            hub_url = None
    else:
        _add("Environment", "Config", "fail", "not found",
             "Run `kidecon init` to create ~/.config/kidecon/kidecon.yaml")
        hub_url = None

    if hub_url:
        try:
            r = httpx.get(f"{hub_url}/docs", timeout=5.0)
            hub_ok = 200 <= r.status_code < 500
            _add("Hub", "Reachable", "pass" if hub_ok else "fail",
                 f"{hub_url} (HTTP {r.status_code})",
                 "" if hub_ok else "Check hub_url in kidecon.yaml")
        except Exception as e:
            _add("Hub", "Reachable", "fail", f"{hub_url} — {e}",
                 "Check hub_url in kidecon.yaml; is kidecon-hub running?")

        jwt = keyring.get_password(KEYRING_SERVICE, KEY_JWT)
        if jwt:
            try:
                client = HubClient(
                    hub_url=hub_url,
                    kideconomy_api_url=config.get("kideconomy_api_url", ""),
                )
                tier_val = client.get_tier()
                _add("Hub", "JWT", "pass", f"valid (tier {tier_val})")
            except Exception as e:
                _add("Hub", "JWT", "fail", str(e),
                     "Re-register with `kidecon setup`")
        else:
            _add("Hub", "JWT", "fail", "not set",
                 "Register with `kidecon setup`")

        agent_id = keyring.get_password(KEYRING_SERVICE, KEY_AGENT_ID)
        if agent_id:
            _add("Hub", "Agent ID", "pass", agent_id)
        else:
            _add("Hub", "Agent ID", "fail", "not set",
                 "Run `kidecon setup` to generate")

        ke_user = keyring.get_password(KEYRING_SERVICE, "kideconomy_username")
        if ke_user:
            _add("Hub", "KE username", "pass", ke_user)
        else:
            _add("Hub", "KE username", "fail", "not set",
                 "Run `kidecon setup` to link your KidEconomy account")
    else:
        _add("Hub", "Reachable", "warn", "skipped (no config)", "Fix config first")
        _add("Hub", "JWT", "warn", "skipped")
        _add("Hub", "Agent ID", "warn", "skipped")

    for key_name, description, required in required_keys:
        v = keyring.get_password(KEYRING_SERVICE, f"api_key_{key_name}")
        if v:
            _add("Keys", key_name, "pass", description)
        elif required:
            _add("Keys", key_name, "fail", f"required — {description}",
                 f"Run: kidecon key add --name {key_name} --value <your-key>")
        else:
            _add("Keys", key_name, "warn", f"optional — {description}")

    api_keys = _load_key_index()
    for key_name in api_keys:
        if key_name in [k for k, _, _ in required_keys]:
            continue
        v = keyring.get_password(KEYRING_SERVICE, f"api_key_{key_name}")
        _add("Keys", key_name, "pass" if v else "warn",
             "user-added" if v else "indexed but missing")

    messages_log = Path.home() / "kidecon" / "messages.log"
    if messages_log.exists():
        mtime = datetime.fromtimestamp(messages_log.stat().st_mtime, tz=UTC)
        _add("Sandbox", "Messages log", "pass", f"last write {mtime.isoformat()}")
    else:
        _add("Sandbox", "Messages log", "warn", "not yet created")

    if SANDBOX_SCRIPTS_DIR.exists():
        script_count = len(list(SANDBOX_SCRIPTS_DIR.glob("*.py")))
        _add("Sandbox", "Scripts dir", "pass" if script_count else "warn",
             f"{SANDBOX_SCRIPTS_DIR} ({script_count} scripts)")
    else:
        _add("Sandbox", "Scripts dir", "warn", "does not exist")

    if SANDBOX_APPROVED_FILE.exists():
        approved_count = len(SANDBOX_APPROVED_FILE.read_text().splitlines())
        _add("Sandbox", "Approved scripts", "pass", str(approved_count))
    else:
        _add("Sandbox", "Approved scripts", "warn", "not yet created")

    workspace = Path.home() / "kidecon" / "workspace"
    ws_exists = workspace.exists()
    _add("Sandbox", "Workspace dir", "pass" if ws_exists else "fail",
         str(workspace),
         "" if ws_exists else "Run `mkdir -p ~/kidecon/workspace` to create")

    counts = {"pass": 0, "fail": 0, "warn": 0}
    order = ["Environment", "Hub", "Keys", "Sandbox"]
    for group in order:
        rows = [r for r in results if r[0] == group]
        if not rows:
            continue
        console.print()
        console.print(f"[bold underline]{group}[/bold underline]")
        table = Table(show_header=True, header_style="bold", expand=False)
        table.add_column("Check", style="bold")
        table.add_column("Status")
        table.add_column("Detail", overflow="fold")
        for _g, label, status, detail, hint in rows:
            counts[status] += 1
            if status == "pass":
                mark = pass_mark
            elif status == "fail":
                mark = fail_mark
            else:
                mark = warn_mark
            text = detail or "—"
            if hint:
                text += f"\n[yellow]→ {hint}[/yellow]"
            table.add_row(label, mark, text)
        console.print(table)

    total = sum(counts.values())
    console.print()
    console.print(
        f"[bold]{total} checks[/bold] [dim]·[/dim] "
        f"[green]{counts['pass']} passed[/green] [dim]·[/dim] "
        + (f"[red]{counts['fail']} failed[/red] [dim]·[/dim] " if counts["fail"]
           else f"[dim]{counts['fail']} failed[/dim] [dim]·[/dim] ")
        + (f"[yellow]{counts['warn']} warnings[/yellow]" if counts["warn"]
           else f"[dim]{counts['warn']} warnings[/dim]"),
    )
    if counts["fail"]:
        raise typer.Exit(code=1)


# ------------------------------------------------------------------
# admin
# ------------------------------------------------------------------
_admin_app = typer.Typer(help="Admin commands (requires tier 3 staff agent).")
app.add_typer(_admin_app, name="admin", help="Admin commands (requires tier 3 staff agent).")


@_admin_app.callback()
def admin_main(
    no_color: bool = typer.Option(False, "--no-color", help="Disable color and rich formatting."),
):
    """Admin commands (requires tier 3 staff agent)."""
    _apply_no_color(no_color)


@_admin_app.command("skills")
def admin_skills(
    action: str = typer.Argument(..., help="pending | approve | reject"),
    skill_id: str = typer.Option(None, "--id", help="Skill ID (required for approve/reject)"),
    reason: str = typer.Option(None, "--reason", help="Rejection reason (required for reject)"),
):
    """Manage skills: pending (list), approve, reject."""
    client = require_auth()

    if action == "pending":
        try:
            skills = client.admin_pending_skills()
        except Exception as err:
            console.print(f"[bold red]✗[/bold red] Could not fetch pending skills: {err}")
            raise typer.Exit(code=1) from err
        if not skills:
            console.print("[dim]No pending skills.[/dim]")
            return
        table = Table(show_header=True, header_style="bold")
        table.add_column("ID")
        table.add_column("Name")
        table.add_column("Version")
        table.add_column("Status")
        table.add_column("Category")
        for s in skills:
            table.add_row(s["id"], s["name"], s["version"], s["approval_status"], s["category"])
        console.print(table)

    elif action == "approve":
        if not skill_id:
            raise typer.BadParameter("--id is required for approve")
        try:
            result = client.admin_approve_skill(skill_id)
        except Exception as err:
            console.print(f"[bold red]✗[/bold red] Approve failed: {err}")
            raise typer.Exit(code=1) from err
        console.print(f"[bold green]✓[/bold green] Skill {skill_id} set to {result['status']}.")

    elif action == "reject":
        if not skill_id:
            raise typer.BadParameter("--id is required for reject")
        if not reason:
            raise typer.BadParameter("--reason is required for reject")
        try:
            result = client.admin_reject_skill(skill_id, reason)
        except Exception as err:
            console.print(f"[bold red]✗[/bold red] Reject failed: {err}")
            raise typer.Exit(code=1) from err
        console.print(f"[bold yellow]⚠[/bold yellow] Skill {skill_id} rejected: {result['reason']}")


@_admin_app.command("agents")
def admin_agents(
    action: str = typer.Argument(..., help="list | promote | staff | unstaff"),
    agent_id: str = typer.Option(None, "--id", help="Agent ID (required for promote/staff/unstaff)"),
    tier: int = typer.Option(None, "--tier", help="Tier level (required for promote)"),
):
    """Manage agents: list, promote (set tier), staff/unstaff (toggle staff flag)."""
    client = require_auth()

    if action == "list":
        try:
            agents = client.admin_list_agents()
        except Exception as err:
            console.print(f"[bold red]✗[/bold red] Could not list agents: {err}")
            raise typer.Exit(code=1) from err
        if not agents:
            console.print("[dim]No agents registered.[/dim]")
            return
        table = Table(show_header=True, header_style="bold")
        table.add_column("ID")
        table.add_column("Name")
        table.add_column("Tier")
        table.add_column("Staff")
        table.add_column("Status")
        for a in agents:
            staff = "[green]yes[/green]" if a.get("is_staff") else "[dim]no[/dim]"
            table.add_row(str(a["id"]), a["name"], str(a["tier"]), staff, a["status"])
        console.print(table)

    elif action == "promote":
        if not agent_id:
            raise typer.BadParameter("--id is required for promote")
        if tier is None:
            raise typer.BadParameter("--tier is required for promote")
        try:
            result = client.admin_set_tier(agent_id, tier)
        except Exception as err:
            console.print(f"[bold red]✗[/bold red] Promote failed: {err}")
            raise typer.Exit(code=1) from err
        console.print(f"[bold green]✓[/bold green] Agent {agent_id} set to tier {result['tier']}.")

    elif action in ("staff", "unstaff"):
        if not agent_id:
            raise typer.BadParameter("--id is required")
        try:
            result = client.admin_set_staff(agent_id, action == "staff")
        except Exception as err:
            console.print(f"[bold red]✗[/bold red] Staff toggle failed: {err}")
            raise typer.Exit(code=1) from err
        console.print(f"[bold green]✓[/bold green] Agent {agent_id} is_staff={result['is_staff']}.")


if __name__ == "__main__":
    app()
