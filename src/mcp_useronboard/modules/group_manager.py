from typing import List, Dict, Optional, Set
from mcp_useronboard.core.connection import HostConnection
from mcp_useronboard.core.models import OnboardingManifest, GroupAssignmentPlan

class GroupManager:
    """Manages role-based group assignment for users onboarding to target hosts."""

    def __init__(self, target_conn: HostConnection, source_conn: Optional[HostConnection] = None):
        self.target_conn = target_conn
        self.source_conn = source_conn

    def get_user_groups(self, conn: HostConnection, username: str) -> List[str]:
        """Retrieves list of secondary and primary groups for a user."""
        res = conn.run_cmd(f"id -Gn {username} 2>/dev/null").strip()
        if not res:
            return []
        return [g.strip() for g in res.split() if g.strip()]

    def plan_group_assignments(
        self,
        username: str,
        manifest: OnboardingManifest,
        requested_tools: Optional[List[str]] = None,
        requested_groups: Optional[List[str]] = None
    ) -> GroupAssignmentPlan:
        """Calculates which groups need to be assigned to the user on the target host."""
        current_groups = self.get_user_groups(self.target_conn, username)
        source_groups = self.get_user_groups(self.source_conn, username) if self.source_conn else []

        needed_groups: Set[str] = set()

        # 1. Always include the default local tool group if it exists in manifest
        if manifest.local_group:
            needed_groups.add(manifest.local_group)

        # 2. Map requested tools to application groups
        if requested_tools:
            for tool in requested_tools:
                tool_lower = tool.lower().strip()
                matched = False
                for grp, apps in manifest.application_groups.items():
                    if any(tool_lower == app.lower().strip() for app in apps):
                        needed_groups.add(grp)
                        matched = True
                if not matched:
                    # Check if a group with <tool>_users exists
                    potential_grp = f"{tool_lower}_users"
                    if potential_grp in manifest.application_groups:
                        needed_groups.add(potential_grp)

        # 3. Add any explicitly requested groups
        if requested_groups:
            for grp in requested_groups:
                needed_groups.add(grp.strip())

        # 4. If neither tools nor groups specified, match source groups that exist in manifest
        if not requested_tools and not requested_groups and source_groups:
            for s_grp in source_groups:
                if s_grp in manifest.application_groups or s_grp == manifest.local_group:
                    needed_groups.add(s_grp)

        # If still no groups selected, assign all available application groups from manifest
        if not needed_groups and manifest.application_groups:
            for grp in manifest.application_groups.keys():
                needed_groups.add(grp)

        # Calculate groups that are not already assigned
        groups_to_assign = [g for g in sorted(needed_groups) if g not in current_groups]

        session_refresh_cmd = f"newgrp {groups_to_assign[0]}" if groups_to_assign else f"exec su -l {username}"
        guidance = (
            f"Run '{session_refresh_cmd}' or log out and back in to refresh active session tokens "
            f"so group permissions take effect."
        )

        return GroupAssignmentPlan(
            target_user=username,
            current_groups=current_groups,
            source_groups=source_groups,
            available_manifest_groups=manifest.application_groups,
            groups_to_assign=groups_to_assign,
            assigned_groups=[],
            session_refresh_guidance=guidance
        )

    def execute_group_assignments(self, plan: GroupAssignmentPlan) -> List[str]:
        """
        Applies group assignments on the target server using batched privileged execution.
        Eliminates approval fatigue and reduces SSH round-trips.
        """
        if not plan.groups_to_assign:
            return []

        assigned = []
        for group in plan.groups_to_assign:
            # Compound execution: ensure group exists and assign user in one operation
            self.target_conn.run_privileged(
                f"getent group '{group}' >/dev/null 2>&1 || groupadd -r '{group}' && usermod -aG '{group}' '{plan.target_user}'",
                f"Ensure role group '{group}' exists and assign user '{plan.target_user}'"
            )
            assigned.append(group)

        plan.assigned_groups = assigned
        return assigned
