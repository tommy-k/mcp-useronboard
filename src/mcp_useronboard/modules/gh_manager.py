import re
from typing import Optional
from mcp_useronboard.core.connection import HostConnection
from mcp_useronboard.core.models import GHAuthPlan

class GHManager:
    """Manages GitHub CLI credentials, Git configuration, and non-blocking authentication verification."""

    def __init__(self, target_conn: HostConnection, source_conn: Optional[HostConnection] = None):
        self.target_conn = target_conn
        self.source_conn = source_conn

    def _get_user_home(self, conn: HostConnection, username: str) -> str:
        home = conn.run_cmd(f"eval echo ~{username}").strip()
        if not home or home.startswith("~"):
            return f"/home/{username}"
        return home

    def plan_gh_migration(self, username: str) -> GHAuthPlan:
        """Inspects source environment to determine if gh or git configurations exist."""
        src_conn = self.source_conn or self.target_conn
        src_home = self._get_user_home(src_conn, username)

        has_hosts = src_conn.file_exists(f"{src_home}/.config/gh/hosts.yml")
        has_config = src_conn.file_exists(f"{src_home}/.config/gh/config.yml")
        has_gitconfig = src_conn.file_exists(f"{src_home}/.gitconfig")

        has_gh = has_hosts or has_config

        return GHAuthPlan(
            target_user=username,
            source_has_gh_config=has_gh,
            hosts_migrated=False,
            config_migrated=False,
            gitconfig_migrated=False,
            auth_status="pending_migration" if has_gh else "missing_config",
            is_non_blocking_warning=False,
            readdress_instructions=None
        )

    def execute_gh_migration(self, plan: GHAuthPlan) -> GHAuthPlan:
        """Migrates gh configs and gitconfig with strict file permissions, then runs non-blocking auth verification."""
        src_conn = self.source_conn or self.target_conn
        src_home = self._get_user_home(src_conn, plan.target_user)
        tgt_home = self._get_user_home(self.target_conn, plan.target_user)

        # 1. Ensure target directory structure exists
        self.target_conn.run_cmd(f"mkdir -p {tgt_home}/.config/gh && chmod 700 {tgt_home}/.config/gh")

        # 2. Migrate ~/.config/gh/hosts.yml if present
        src_hosts = f"{src_home}/.config/gh/hosts.yml"
        if src_conn.file_exists(src_hosts):
            content = src_conn.read_file(src_hosts)
            if content:
                tgt_hosts = f"{tgt_home}/.config/gh/hosts.yml"
                self.target_conn.write_file(tgt_hosts, content, mode="600")
                plan.hosts_migrated = True

        # 3. Migrate ~/.config/gh/config.yml if present
        src_cfg = f"{src_home}/.config/gh/config.yml"
        if src_conn.file_exists(src_cfg):
            content = src_conn.read_file(src_cfg)
            if content:
                tgt_cfg = f"{tgt_home}/.config/gh/config.yml"
                self.target_conn.write_file(tgt_cfg, content, mode="644")
                plan.config_migrated = True

        # 4. Migrate ~/.gitconfig if present
        src_gitcfg = f"{src_home}/.gitconfig"
        if src_conn.file_exists(src_gitcfg):
            content = src_conn.read_file(src_gitcfg)
            if content:
                tgt_gitcfg = f"{tgt_home}/.gitconfig"
                self.target_conn.write_file(tgt_gitcfg, content, mode="644")
                plan.gitconfig_migrated = True

        # Ensure correct ownership
        self.target_conn.run_cmd(
            f"chown -R {plan.target_user}:{plan.target_user} {tgt_home}/.config/gh {tgt_home}/.gitconfig 2>/dev/null || true"
        )

        # 5. Verify GitHub CLI on target host
        return self.verify_gh_status(plan)

    def verify_gh_status(self, plan: GHAuthPlan) -> GHAuthPlan:
        """Verifies gh execution and authentication status on target host."""
        # Check if gh binary is accessible
        gh_bin = self.target_conn.run_cmd("command -v gh || test -x /opt/tools/bin/gh && echo '/opt/tools/bin/gh'").strip()
        if not gh_bin:
            plan.auth_status = "not_installed"
            plan.is_non_blocking_warning = True
            plan.readdress_instructions = (
                "The 'gh' executable was not found in PATH. Ensure group 'git_users' is assigned "
                "or refresh your shell session."
            )
            return plan

        # Check authentication status
        status_out = self.target_conn.run_cmd(f"{gh_bin} auth status 2>&1")

        if "Logged in to" in status_out:
            plan.auth_status = "authenticated"
            user_match = re.search(r"account ([A-Za-z0-9_-]+)", status_out)
            if user_match:
                plan.authenticated_user = user_match.group(1)
            else:
                api_user = self.target_conn.run_cmd(f"{gh_bin} api user --jq .login 2>/dev/null").strip()
                if api_user:
                    plan.authenticated_user = api_user
            plan.is_non_blocking_warning = False
            plan.readdress_instructions = None
        else:
            plan.auth_status = "needs_reauth"
            plan.is_non_blocking_warning = True
            plan.readdress_instructions = (
                "GitHub CLI token was copied, but requires re-authentication on this host "
                "(common when SAML SSO or IP restrictions are enforced). "
                "Please run 'gh auth login --hostname github.com --web' on the side. "
                "Remaining onboarding completed successfully."
            )

        return plan
