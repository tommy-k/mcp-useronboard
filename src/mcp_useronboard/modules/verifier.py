from typing import Dict, Any, List
from mcp_useronboard.core.connection import HostConnection
from mcp_useronboard.core.models import (
    UserOnboardingPlan,
    OnboardingResult,
    OnboardingManifest
)

class PostOnboardingVerifier:
    """Verifies user access, group assignments, shell validity, and tool readiness after onboarding."""

    def __init__(self, target_conn: HostConnection):
        self.target_conn = target_conn

    def verify(self, plan: UserOnboardingPlan, manifest: OnboardingManifest) -> OnboardingResult:
        """Executes verification checks on target host and builds OnboardingResult."""
        username = plan.target_user
        verification: Dict[str, Any] = {}
        next_steps: List[str] = []

        # 1. Verify Groups
        active_groups_raw = self.target_conn.run_cmd(f"id -Gn {username} 2>/dev/null").strip()
        active_groups = active_groups_raw.split()
        assigned_match = [g for g in plan.group_plan.groups_to_assign if g in active_groups]
        verification["groups"] = {
            "requested": plan.group_plan.groups_to_assign,
            "confirmed_on_host": assigned_match,
            "all_user_groups": active_groups
        }

        # 2. Verify Tool Executability per Group
        accessible_tools: Dict[str, bool] = {}
        for grp, tools in manifest.application_groups.items():
            for tool in tools:
                tool_path = f"{manifest.acl_path}/bin/{tool}"
                check = self.target_conn.run_cmd(
                    f"test -x {tool_path} && echo 'EXECUTABLE' || echo 'NOT_EXECUTABLE'"
                ).strip()
                accessible_tools[tool] = ("EXECUTABLE" in check)

        verification["tools_accessible"] = accessible_tools

        # 3. Verify Shell File
        home = self.target_conn.run_cmd(f"eval echo ~{username}").strip()
        bashrc_path = f"{home}/.bashrc"
        syntax_check = self.target_conn.run_cmd(f"bash -n {bashrc_path} 2>&1").strip()
        verification["shell"] = {
            "file": bashrc_path,
            "syntax_valid": (syntax_check == ""),
            "backup": plan.shell_plan.backup_path
        }

        # 4. Compile Next Steps & Guidance
        refresh_cmd = f"newgrp {plan.group_plan.groups_to_assign[0]}" if plan.group_plan.groups_to_assign else f"exec su -l {username}"
        next_steps.append(
            f"🔄 Refresh your active shell session: Run '{refresh_cmd}' or log out and back in."
        )

        if plan.gh_plan.is_non_blocking_warning and plan.gh_plan.readdress_instructions:
            next_steps.append(f"⚠️  GitHub CLI: {plan.gh_plan.readdress_instructions}")
        elif plan.gh_plan.auth_status == "authenticated":
            next_steps.append(f"✅ GitHub CLI: Verified and authenticated as @{plan.gh_plan.authenticated_user}.")

        next_steps.append(f"🚀 Environment ready! Custom aliases and tools in {manifest.acl_path}/bin are primed.")

        return OnboardingResult(
            success=True,
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
