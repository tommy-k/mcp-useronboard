import re
from datetime import datetime, timezone
from typing import Optional, List, Dict
from mcp_useronboard.core.connection import HostConnection
from mcp_useronboard.core.models import ShellConfigPlan

BLOCK_START = "# >>> mcp-useronboard managed block >>>"
BLOCK_END = "# <<< mcp-useronboard managed block <<<"

class ShellManager:
    """Manages safe, non-destructive migration of user shell preferences (~/.bashrc, aliases, prompt)."""

    def __init__(self, target_conn: HostConnection, source_conn: Optional[HostConnection] = None):
        self.target_conn = target_conn
        self.source_conn = source_conn

    def _get_user_home(self, conn: HostConnection, username: str) -> str:
        """Determines home directory for user on host."""
        home = conn.run_cmd(f"eval echo ~{username}").strip()
        if not home or home.startswith("~"):
            return f"/home/{username}"
        return home

    def read_source_shell_content(self, username: str) -> str:
        """Reads shell configuration from source host (or target if no separate source)."""
        conn = self.source_conn or self.target_conn
        home = self._get_user_home(conn, username)

        for filename in [".bashrc", ".bash_profile", ".profile", ".zshrc"]:
            path = f"{home}/{filename}"
            if conn.file_exists(path):
                content = conn.read_file(path)
                if content and content.strip():
                    return content
        return ""

    def parse_shell_preferences(self, raw_shell: str) -> Dict[str, List[str]]:
        """Parses aliases, environment variables, and custom functions/prompts from shell script."""
        aliases: List[str] = []
        exports: List[str] = []
        custom_lines: List[str] = []

        for line in raw_shell.splitlines():
            line_str = line.strip()
            # Ignore comments and empty lines
            if not line_str or line_str.startswith("#"):
                continue

            # Check for aliases
            if line_str.startswith("alias "):
                aliases.append(line_str)
            # Check for exports (excluding generic PATH overrides that clobber enterprise baselines)
            elif line_str.startswith("export "):
                if "PATH=" in line_str and "/opt/tools" in line_str:
                    continue  # already managed by /etc/profile.d/corp-standards.sh
                exports.append(line_str)
            # Check for prompt customizations or completions
            elif any(line_str.startswith(k) for k in ["PS1=", "eval \"$(starship", "eval \"$(oh-my-posh", "source <(gh completion"]):
                custom_lines.append(line_str)

        return {
            "aliases": aliases,
            "exports": exports,
            "custom": custom_lines
        }

    def plan_shell_migration(self, username: str) -> ShellConfigPlan:
        """Plans non-destructive shell migration for user."""
        raw_source = self.read_source_shell_content(username)
        parsed = self.parse_shell_preferences(raw_source)

        env_dict = {}
        for exp in parsed["exports"]:
            match = re.match(r"export\s+([A-Za-z0-9_]+)=(.*)", exp)
            if match:
                env_dict[match.group(1)] = match.group(2)

        return ShellConfigPlan(
            target_user=username,
            target_shell_file="~/.bashrc",
            migrated_aliases=parsed["aliases"],
            migrated_env_vars=env_dict,
            migrated_custom_blocks=parsed["custom"],
            syntax_verified=False
        )

    def execute_shell_migration(self, plan: ShellConfigPlan) -> bool:
        """Backs up existing target ~/.bashrc, merges preferences inside an idempotent block,
        and verifies bash syntax before finalizing."""
        home = self._get_user_home(self.target_conn, plan.target_user)
        target_path = f"{home}/.bashrc"

        # 1. Create timestamped backup if target file exists
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_path = f"{home}/.bashrc.pre-onboard.{timestamp}"

        existing_content = ""
        if self.target_conn.file_exists(target_path):
            existing_content = self.target_conn.read_file(target_path) or ""
            # Save backup
            self.target_conn.write_file(backup_path, existing_content, mode="644")
            plan.backup_path = backup_path

        # 2. Build the new managed block
        block_lines = [
            BLOCK_START,
            f"# Auto-migrated by mcp-useronboard on {datetime.now(timezone.utc).isoformat()}",
            "# Preserves personal aliases and preferences without overriding /etc/profile.d/ standards."
        ]

        if plan.migrated_aliases:
            block_lines.append("\n# Personal Aliases")
            block_lines.extend(plan.migrated_aliases)

        if plan.migrated_env_vars:
            block_lines.append("\n# Personal Environment Variables")
            for k, v in plan.migrated_env_vars.items():
                block_lines.append(f"export {k}={v}")

        if plan.migrated_custom_blocks:
            block_lines.append("\n# Personal Shell Prompt & Completions")
            block_lines.extend(plan.migrated_custom_blocks)

        block_lines.append(BLOCK_END)
        managed_block = "\n".join(block_lines) + "\n"

        # 3. Merge cleanly (replace existing block if present, else append)
        if BLOCK_START in existing_content and BLOCK_END in existing_content:
            pattern = re.compile(rf"{re.escape(BLOCK_START)}.*?{re.escape(BLOCK_END)}\n?", re.DOTALL)
            new_content = pattern.sub(managed_block, existing_content)
        else:
            new_content = existing_content.rstrip() + "\n\n" + managed_block

        # 4. Write new content to a temporary file first and verify syntax
        temp_path = f"{home}/.bashrc.onboard_tmp"
        self.target_conn.write_file(temp_path, new_content, mode="644")

        # Run syntax check: bash -n <file>
        check_cmd = f"bash -n '{temp_path}' 2>&1"
        check_res = self.target_conn.run_cmd(check_cmd).strip()

        if check_res:
            self.target_conn.run_cmd(f"rm -f '{temp_path}'")
            raise SyntaxError(f"Shell migration aborted: syntax validation failed for ~/.bashrc: {check_res}")

        # Move verified file into place and assign user's primary login group (trailing colon)
        self.target_conn.run_cmd(f"mv '{temp_path}' '{target_path}' && chmod 644 '{target_path}' && chown '{plan.target_user}': '{target_path}' 2>/dev/null || true")
        plan.syntax_verified = True
        return True
