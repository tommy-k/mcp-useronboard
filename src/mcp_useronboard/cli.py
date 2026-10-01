import os
import sys
import json
import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from typing import Optional

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
    help="Enterprise Linux User Onboarding MCP Agent & CLI. Seamlessly aligns user roles to custom application groups and preserves shell preferences."
)
console = Console()

@app.command()
def onboard(
    target: str = typer.Option("localhost", "--target", "-t", help="Target host where user is onboarding"),
    source: Optional[str] = typer.Option(None, "--source", "-s", help="Optional source host/workstation to pull shell preferences from"),
    user: Optional[str] = typer.Option(None, "--user", "-u", help="Username to onboard (defaults to current user)"),
    tools: Optional[str] = typer.Option(None, "--tools", help="Comma-separated tools requested by user (e.g. terraform,gh,kubectl)"),
    groups: Optional[str] = typer.Option(None, "--groups", help="Comma-separated application groups to explicitly grant"),
    sudo_pass_file: Optional[str] = typer.Option(None, "--sudo-pass-file", help="Path to 0600 sudo password file for non-interactive privilege escalation"),
    auto_approve_sudo: bool = typer.Option(False, "--auto-approve-sudo", help="Bypass interactive sudo approval prompts for routine commands"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Compile and display the onboarding plan without modifying the target host")
):
    """Executes full user onboarding: group assignment, shell migration, and GitHub CLI setup."""
    username = user or os.environ.get("USER") or os.environ.get("USERNAME") or "root"
    requested_tools = [t.strip() for t in tools.split(",")] if tools else None
    requested_groups = [g.strip() for g in groups.split(",")] if groups else None

    vault = EphemeralCredentialVault.get_vault(auto_approve=auto_approve_sudo)
    if sudo_pass_file:
        vault.load_sudo_pass_file(sudo_pass_file)

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
    py_bin = python_path or "/path/to/mcp-useronboard/.venv/bin/python"

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
                        "args": ["-m", "mcp_useronboard.server"],
                        "alwaysAllow": [
                            "audit_onboarding_contract",
                            "plan_onboarding",
                            "execute_onboarding",
                            "verify_user_access",
                            "auto_onboard"
                        ]
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
