import os
import sys
import json
from typing import Optional
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax

from mcp_useronboard.core.connection import HostConnection
from mcp_useronboard.core.security import EphemeralCredentialVault
from mcp_useronboard.core.models import UserOnboardingPlan
from mcp_useronboard.modules.manifest_reader import ManifestReader
from mcp_useronboard.modules.group_manager import GroupManager
from mcp_useronboard.modules.shell_manager import ShellManager
from mcp_useronboard.modules.gh_manager import GHManager
from mcp_useronboard.modules.verifier import PostOnboardingVerifier

app = typer.Typer(
    name="mcp-useronboard",
    help="Enterprise Linux User Onboarding Agent & Universal MCP Server (Claude, Cursor, Antigravity, Windsurf, VS Code).",
    add_completion=False
)
console = Console()

def get_default_user() -> str:
    return os.environ.get("USER") or os.environ.get("USERNAME") or "root"

@app.command()
def audit(
    target: str = typer.Option("localhost", "--target", "-t", help="Target server hostname or IP"),
    user: str = typer.Option(None, "--user", "-u", help="Target user account")
):
    """Audits the on-server migration manifest contract and reports available application groups."""
    username = user or get_default_user()
    console.print(Panel(f"[bold cyan]Auditing Onboarding Contract on [green]{target}[/] for user [yellow]{username}[/][/bold cyan]"))

    conn = HostConnection(host=target, user=username)
    try:
        manifest = ManifestReader(conn).read_manifest()
        curr_groups = GroupManager(conn).get_user_groups(conn, username)

        table = Table(title="Manifest Application Groups & Tool Bindings", show_header=True)
        table.add_column("Application Role Group", style="cyan")
        table.add_column("Controlled Applications / Binaries", style="green")
        table.add_column("User Currently Member?", style="yellow")

        for grp, apps in manifest.application_groups.items():
            is_member = "✅ Yes" if grp in curr_groups else "❌ No"
            table.add_row(grp, ", ".join(apps) if apps else "None registered", is_member)

        console.print(table)
        console.print(f"[bold]Origin Parent Host:[/bold] {manifest.parent_host}")
        console.print(f"[bold]Managed Tool Path:[/bold] {manifest.acl_path}/bin")
        console.print(f"[bold]Current User Groups:[/bold] {', '.join(curr_groups)}")
    finally:
        conn.close()

@app.command()
def onboard(
    target: str = typer.Option("localhost", "--target", "-t", help="Target server hostname or IP"),
    source: Optional[str] = typer.Option(None, "--source", "-s", help="Optional source origin server hostname or IP"),
    user: str = typer.Option(None, "--user", "-u", help="User account to onboard"),
    tools: Optional[str] = typer.Option(None, "--tools", help="Comma-separated tools required (e.g. 'terraform,gh')"),
    groups: Optional[str] = typer.Option(None, "--groups", help="Comma-separated groups required"),
    auto_approve_sudo: bool = typer.Option(False, "--auto-approve-sudo", help="Bypass confirmation prompt for sudo execution"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Generate and display plan without applying changes")
):
    """Executes end-to-end user onboarding to the target server."""
    username = user or get_default_user()
    requested_tools = [t.strip() for t in tools.split(",")] if tools else None
    requested_groups = [g.strip() for g in groups.split(",")] if groups else None

    EphemeralCredentialVault.get_vault(auto_approve=auto_approve_sudo)

    console.print(Panel(
        f"[bold blue]🚀 Enterprise User Onboarding Agent[/bold blue]\n"
        f"Target: [green]{target}[/] | Source: [cyan]{source or 'Local workstation'}[/] | User: [yellow]{username}[/]"
    ))

    tgt_conn = HostConnection(host=target, user=username)
    src_conn = HostConnection(host=source, user=username) if source else None

    try:
        manifest = ManifestReader(tgt_conn).read_manifest()
        grp_mgr = GroupManager(tgt_conn, src_conn)
        shell_mgr = ShellManager(tgt_conn, src_conn)
        gh_mgr = GHManager(tgt_conn, src_conn)

        with console.status("[bold yellow]Generating Onboarding Plan...[/bold yellow]"):
            grp_plan = grp_mgr.plan_group_assignments(username, manifest, requested_tools, requested_groups)
            shell_plan = shell_mgr.plan_shell_migration(username)
            gh_plan = gh_mgr.plan_gh_migration(username)

            full_plan = UserOnboardingPlan(
                target_host=target,
                source_host=source,
                target_user=username,
                group_plan=grp_plan,
                shell_plan=shell_plan,
                gh_plan=gh_plan
            )

        # Display Plan
        console.print(f"[bold cyan]Plan Summary:[/bold cyan]")
        console.print(f"  • [bold]Groups to Assign:[/bold] {', '.join(grp_plan.groups_to_assign) or '[dim]None (already assigned)[/dim]'}")
        console.print(f"  • [bold]Shell Preferences:[/bold] {len(shell_plan.migrated_aliases)} aliases, {len(shell_plan.migrated_env_vars)} env vars")
        console.print(f"  • [bold]GitHub CLI Config:[/bold] {'Found on source' if gh_plan.source_has_gh_config else 'None found'}")

        if dry_run:
            console.print("[yellow]Dry-run requested. Exiting without modifying host.[/yellow]")
            return

        # Execute
        with console.status("[bold green]Applying Group Assignments (privileged)...[/bold green]"):
            grp_mgr.execute_group_assignments(grp_plan)

        with console.status("[bold green]Merging Shell Preferences (~/.bashrc)...[/bold green]"):
            shell_mgr.execute_shell_migration(shell_plan)

        with console.status("[bold green]Migrating GitHub & Git Configs (~/.config/gh)...[/bold green]"):
            gh_plan = gh_mgr.execute_gh_migration(gh_plan)
            full_plan.gh_plan = gh_plan

        # Verify
        with console.status("[bold green]Running Post-Onboarding Verification...[/bold green]"):
            verifier = PostOnboardingVerifier(tgt_conn)
            result = verifier.verify(full_plan, manifest)

        console.print("\n[bold green]✅ Onboarding Execution Complete![/bold green]")
        for step in result.next_steps:
            console.print(f"  {step}")

    finally:
        tgt_conn.close()
        if src_conn:
            src_conn.close()

@app.command()
def serve(
    transport: str = typer.Option("stdio", "--transport", "-t", help="Transport mode: 'stdio', 'sse', or 'streamable-http'"),
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host interface for SSE/HTTP mode"),
    port: int = typer.Option(8000, "--port", "-p", help="Port for SSE/HTTP mode")
):
    """Runs the universal MCP server over stdio (Claude Desktop, Cursor, Antigravity) or SSE/HTTP network stream."""
    from mcp_useronboard.server import mcp

    if transport == "stdio":
        mcp.run(transport="stdio")
    elif transport in ("sse", "streamable-http"):
        console.print(f"[bold green]Starting MCP {transport.upper()} server on http://{host}:{port}...[/bold green]")
        mcp.run(transport=transport, host=host, port=port)
    else:
        console.print(f"[bold red]Unknown transport '{transport}'. Choose 'stdio', 'sse', or 'streamable-http'.[/bold red]")
        raise typer.Exit(code=1)

@app.command()
def config(
    client: str = typer.Option("all", "--client", "-c", help="Target client: 'claude', 'cursor', 'antigravity', 'windsurf', 'vscode', or 'all'"),
    python_path: Optional[str] = typer.Option(None, "--python-path", help="Explicit path to python binary inside virtual environment")
):
    """Generates ready-to-use MCP configuration snippets for Claude Desktop, Cursor, Antigravity, Windsurf, and VS Code."""
    py_bin = python_path or sys.executable

    configs = {
        "claude": {
            "name": "Claude Desktop",
            "file_locations": {
                "macOS": "~/Library/Application Support/Claude/claude_desktop_config.json",
                "Windows": "%APPDATA%\\Claude\\claude_desktop_config.json",
                "Linux": "~/.config/Claude/claude_desktop_config.json"
            },
            "json": {
                "mcpServers": {
                    "user-onboard": {
                        "command": py_bin,
                        "args": ["-m", "mcp_useronboard.server"]
                    }
                }
            },
            "claude_code_cli": f"claude mcp add user-onboard -- {py_bin} -m mcp_useronboard.server"
        },
        "cursor": {
            "name": "Cursor",
            "file_locations": {
                "Workspace": ".cursor/mcp.json",
                "Global": "~/.cursor/mcp.json"
            },
            "json": {
                "mcpServers": {
                    "user-onboard": {
                        "command": py_bin,
                        "args": ["-m", "mcp_useronboard.server"]
                    }
                }
            }
        },
        "antigravity": {
            "name": "Google Antigravity / Gemini CLI",
            "file_locations": {
                "Config": "~/.gemini/antigravity-cli/mcp_config.json"
            },
            "json": {
                "mcpServers": {
                    "user-onboard": {
                        "command": py_bin,
                        "args": ["-m", "mcp_useronboard.server"]
                    }
                }
            }
        },
        "windsurf": {
            "name": "Windsurf (Codeium Cascade)",
            "file_locations": {
                "Config": "~/.codeium/windsurf/mcp_config.json"
            },
            "json": {
                "mcpServers": {
                    "user-onboard": {
                        "command": py_bin,
                        "args": ["-m", "mcp_useronboard.server"]
                    }
                }
            }
        },
        "vscode": {
            "name": "VS Code (Continue / Cline / Roo Code)",
            "file_locations": {
                "Cline": "~/.vscode/extensions/saoudrizwan.claude-dev/settings/cline_mcp_settings.json",
                "Continue": "~/.continue/config.json"
            },
            "json": {
                "mcpServers": {
                    "user-onboard": {
                        "command": py_bin,
                        "args": ["-m", "mcp_useronboard.server"]
                    }
                }
            }
        }
    }

    selected = [client.lower()] if client.lower() != "all" else list(configs.keys())

    for key in selected:
        if key not in configs:
            console.print(f"[red]Unknown client '{key}'. Available: claude, cursor, antigravity, windsurf, vscode, all[/red]")
            continue

        item = configs[key]
        console.print(Panel(f"[bold cyan]{item['name']} MCP Configuration[/bold cyan]"))
        console.print("[bold]Config File Path(s):[/bold]")
        for platform, path in item["file_locations"].items():
            console.print(f"  • {platform}: [green]{path}[/green]")

        json_str = json.dumps(item["json"], indent=2)
        console.print("\n[bold]Configuration JSON:[/bold]")
        console.print(Syntax(json_str, "json", theme="monokai", line_numbers=False))

        if "claude_code_cli" in item:
            console.print("\n[bold]Or install with Claude Code CLI:[/bold]")
            console.print(f"  [yellow]{item['claude_code_cli']}[/yellow]")
        console.print()

if __name__ == "__main__":
    app()
