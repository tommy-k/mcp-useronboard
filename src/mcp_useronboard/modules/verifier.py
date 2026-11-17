from typing import Dict, Any, List
from mcp_useronboard.core.connection import HostConnection
from mcp_useronboard.core.models import (
    UserOnboardingPlan,
    OnboardingResult,
    OnboardingManifest
)


class PostOnboardingVerifier:
    """Verifies user access, group assignments, shell validity, and tool readiness as the actual user."""

    def __init__(self, target_conn: HostConnection):
        self.target_conn = target_conn

    def _run_as_user_login_shell(self, username: str, inner_cmd: str) -> str:
        """Runs a verification command inside the target user's login shell, not as root."""
        if self.target_conn.user == username:
            return self.target_conn.run_cmd(f"bash -lc '{inner_cmd}'")
        return self.target_conn.run_privileged(
            f"su -s /bin/bash -l '{username}' -c \"{inner_cmd}\"",
            f"Verify command as user '{username}' in login shell"
        )

    def verify(self, plan: UserOnboardingPlan, manifest: OnboardingManifest) -> OnboardingResult:
        """Executes verification checks as the target user on target host and builds OnboardingResult."""
        username = plan.target_user
        verification: Dict[str, Any] = {}
        next_steps: List[str] = []

        # 1. Verify Groups
        active_groups_raw = self.target_conn.run_cmd(f"id -Gn '{username}'").strip()
        active_groups = active_groups_raw.split()
        assigned_match = [g for g in plan.group_plan.groups_to_assign if g in active_groups]
        groups_ok = len(assigned_match) == len(plan.group_plan.groups_to_assign)
        verification["groups"] = {
            "requested": plan.group_plan.groups_to_assign,
            "confirmed_on_host": assigned_match,
            "all_user_groups": active_groups,
            "ok": groups_ok,
        }

        # 2. Verify Tool Executability by Name on User's Login $PATH (as the actual user, NOT as root)
        all_tools: List[str] = []
        for tools in manifest.application_groups.values():
            for t in tools:
                if t not in all_tools:
                    all_tools.append(t)

        accessible_tools: Dict[str, bool] = {}
        tool_paths: Dict[str, str] = {}
        for tool in all_tools:
            check_out = self._run_as_user_login_shell(
                username,
                f"resolved=$(command -v '{tool}') && test -x \"$resolved\" && echo \"EXECUTABLE:$resolved\" || echo 'NOT_EXECUTABLE'"
            ).strip()
            is_ok = "EXECUTABLE:" in check_out and "NOT_EXECUTABLE" not in check_out
            accessible_tools[tool] = is_ok
            if is_ok:
                for line in check_out.splitlines():
                    if line.startswith("EXECUTABLE:"):
                        tool_paths[tool] = line.split("EXECUTABLE:", 1)[1].strip()
                        break

        all_tools_ok = all(accessible_tools.values()) if accessible_tools else True
        verification["tools_accessible"] = accessible_tools
        verification["tool_paths"] = tool_paths

        # 3. Verify Shell File & Personal Home Scripts
        home = self.target_conn.run_cmd(f"eval echo ~{username}").strip()
        bashrc_path = f"{home}/.bashrc"
        syntax_check = self.target_conn.run_cmd(f"bash -n '{bashrc_path}' 2>&1").strip()
        shell_valid = (syntax_check == "")

        home_script_checks: Dict[str, bool] = {}
        for script_path in plan.shell_plan.migrated_home_scripts:
            s_out = self._run_as_user_login_shell(
                username,
                f"test -x '{script_path}' && echo 'OK' || echo 'FAIL'"
            ).strip()
            home_script_checks[script_path] = ("OK" in s_out and "FAIL" not in s_out)

        verification["shell"] = {
            "file": bashrc_path,
            "syntax_valid": shell_valid,
            "backup": plan.shell_plan.backup_path,
            "personal_scripts_ok": home_script_checks,
        }

        overall_success = bool(
            groups_ok
            and shell_valid
            and all_tools_ok
            and all(home_script_checks.values())
        )

        # 4. Compile Next Steps & Guidance
        refresh_cmd = f"newgrp {plan.group_plan.groups_to_assign[0]}" if plan.group_plan.groups_to_assign else f"exec su -l {username}"
        next_steps.append(
            f"🔄 Refresh your active shell session: Run '{refresh_cmd}' or log out and back in."
        )

        if not all_tools_ok:
            missing = [t for t, ok in accessible_tools.items() if not ok]
            next_steps.append(
                f"❌ Missing or unexecutable tools on {username}'s $PATH: {', '.join(missing)}"
            )

        if plan.gh_plan.is_non_blocking_warning and plan.gh_plan.readdress_instructions:
            next_steps.append(f"⚠️  GitHub CLI: {plan.gh_plan.readdress_instructions}")
        elif plan.gh_plan.auth_status == "authenticated":
            next_steps.append(f"✅ GitHub CLI: Verified and authenticated as @{plan.gh_plan.authenticated_user}.")

        if overall_success:
            next_steps.append(f"🚀 Environment ready! Tools are published on $PATH and verified as '{username}'.")

        return OnboardingResult(
            success=overall_success,
            target_host=plan.target_host,
            target_user=username,
            groups_assigned=plan.group_plan.groups_to_assign,
            shell_migrated=plan.shell_plan.syntax_verified,
            shell_backup_created=plan.shell_plan.backup_path,
            gh_auth_status=plan.gh_plan.auth_status,
            gh_authenticated_user=plan.gh_plan.authenticated_user,
            gh_auth_warning=plan.gh_plan.readdress_instructions if plan.gh_plan.is_non_blocking_warning else None,
            session_refresh_cmd=refresh_cmd,
            verification_output=verification,
            next_steps=next_steps
        )
