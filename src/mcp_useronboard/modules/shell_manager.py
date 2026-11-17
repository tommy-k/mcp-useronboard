import re
from datetime import datetime, timezone
from typing import Optional, List, Dict
from mcp_useronboard.core.connection import HostConnection
from mcp_useronboard.core.models import ShellConfigPlan, HomeScriptItem

BLOCK_START = "# >>> mcp-useronboard managed block >>>"
BLOCK_END = "# <<< mcp-useronboard managed block <<<"

HOME_SCRIPT_DIRS = ("bin", ".local/bin", "scripts")


class ShellManager:
    """Manages safe, non-destructive migration of user shell preferences (~/.bashrc, aliases, prompt) and personal ~ scripts."""

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

    def discover_personal_scripts(self, username: str) -> List[HomeScriptItem]:
        """
        Discovers personal scripts/binaries in the migrating user's home directories
        (~/bin, ~/.local/bin, ~/scripts) on source_conn.
        Only runs when migrating from a source host; brand-new users have nothing copied.
        """
        if not self.source_conn:
            return []

        src_home = self._get_user_home(self.source_conn, username).rstrip("/")
        tgt_home = self._get_user_home(self.target_conn, username).rstrip("/")
        search_dirs = " ".join(f"'{src_home}/{d}'" for d in HOME_SCRIPT_DIRS)

        raw_lines = self.source_conn.run_cmd(
            f"find {search_dirs} -maxdepth 2 -type f -exec stat -c '%a|%n' {{}} + 2>/dev/null"
        ).splitlines()

        scripts: List[HomeScriptItem] = []
        for line in raw_lines:
            line = line.strip()
            if "|" not in line:
                continue
            mode_str, src_path = line.split("|", 1)
            src_path = src_path.strip()
            if not src_path.startswith(src_home + "/"):
                continue
            rel_path = src_path[len(src_home) + 1:]
            scripts.append(HomeScriptItem(
                relative_path=rel_path,
                source_path=src_path,
                target_path=f"{tgt_home}/{rel_path}",
                mode=mode_str.strip() or "0750",
            ))
        return scripts

    def parse_shell_preferences(self, raw_shell: str) -> Dict[str, List[str]]:
        """Parses aliases, environment variables, and custom functions/prompts from shell script."""
        aliases: List[str] = []
        exports: List[str] = []
        custom_lines: List[str] = []

        for line in raw_shell.splitlines():
            line_str = line.strip()
            if not line_str or line_str.startswith("#"):
                continue

            if line_str.startswith("alias "):
                aliases.append(line_str)
            elif line_str.startswith("export "):
                if "PATH=" in line_str and "/opt/tools" in line_str:
                    continue  # /opt/tools binaries are published via /usr/local/bin symlinks
                exports.append(line_str)
            elif any(line_str.startswith(k) for k in ["PS1=", "eval \"$(starship", "eval \"$(oh-my-posh", "source <(gh completion"]):
                custom_lines.append(line_str)

        return {
            "aliases": aliases,
            "exports": exports,
            "custom": custom_lines
        }

    def plan_shell_migration(self, username: str) -> ShellConfigPlan:
        """Plans non-destructive shell and personal ~ script migration for user."""
        raw_source = self.read_source_shell_content(username)
        parsed = self.parse_shell_preferences(raw_source)
        personal_scripts = self.discover_personal_scripts(username)

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
            personal_scripts=personal_scripts,
            syntax_verified=False
        )

    def execute_shell_migration(self, plan: ShellConfigPlan) -> bool:
        """
        Backs up existing target ~/.bashrc, migrates personal ~ scripts byte-for-byte,
        merges preferences inside an idempotent block, and verifies bash syntax before finalizing.
        """
        home = self._get_user_home(self.target_conn, plan.target_user)
        target_path = f"{home}/.bashrc"

        # 0. Copy personal ~ scripts byte-for-byte if migrating from a source server
        migrated_scripts: List[str] = []
        if self.source_conn and plan.personal_scripts:
            for item in plan.personal_scripts:
                raw_bytes = self.source_conn.read_bytes(item.source_path)
                if raw_bytes is not None:
                    self.target_conn.write_bytes(item.target_path, raw_bytes, mode=item.mode)
                    parent_dir = item.target_path.rsplit("/", 1)[0]
                    self.target_conn.run_cmd(
                        f"chown '{plan.target_user}': '{parent_dir}' '{item.target_path}' 2>/dev/null || true"
                    )
                    migrated_scripts.append(item.target_path)
        plan.migrated_home_scripts = migrated_scripts

        # 1. Create timestamped backup if target file exists
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_path = f"{home}/.bashrc.pre-onboard.{timestamp}"

        existing_content = ""
        if self.target_conn.file_exists(target_path):
            existing_content = self.target_conn.read_file(target_path) or ""
            self.target_conn.write_file(backup_path, existing_content, mode="644")
            plan.backup_path = backup_path

        # 2. Build the new managed block
        block_lines = [
            BLOCK_START,
            f"# Auto-migrated by mcp-useronboard on {datetime.now(timezone.utc).isoformat()}",
            "# Preserves personal aliases, preferences, and user ~/bin PATH without overriding system baselines."
        ]

        if plan.personal_scripts:
            block_lines.append("\n# Personal Home Script Paths")
            block_lines.append('export PATH="$HOME/bin:$HOME/.local/bin:$HOME/scripts:$PATH"')

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

        check_cmd = f"bash -n '{temp_path}' 2>&1"
        check_res = self.target_conn.run_cmd(check_cmd).strip()

        if check_res:
            self.target_conn.run_cmd(f"rm -f '{temp_path}'")
            raise SyntaxError(f"Shell migration aborted: syntax validation failed for ~/.bashrc: {check_res}")

        # Move verified file into place and assign user's primary login group (trailing colon)
        self.target_conn.run_cmd(
            f"mv '{temp_path}' '{target_path}' && chmod 644 '{target_path}' && chown '{plan.target_user}': '{target_path}' 2>/dev/null || true"
        )
        plan.syntax_verified = True
        return True
