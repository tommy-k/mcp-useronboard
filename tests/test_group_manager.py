from unittest.mock import MagicMock
from mcp_useronboard.core.connection import HostConnection
from mcp_useronboard.core.models import OnboardingManifest
from mcp_useronboard.modules.group_manager import GroupManager

def test_plan_group_assignments_from_tools():
    target_conn = MagicMock(spec=HostConnection)
    target_conn.run_cmd.return_value = "tom domain_users"

    manifest = OnboardingManifest(
        application_groups={
            "terraform_users": ["terraform"],
            "git_users": ["gh"],
            "db_operators": ["psql-client"]
        },
        local_group="tool_users"
    )

    mgr = GroupManager(target_conn=target_conn)
    plan = mgr.plan_group_assignments(
        username="tom",
        manifest=manifest,
        requested_tools=["terraform", "gh"]
    )

    assert "terraform_users" in plan.groups_to_assign
    assert "git_users" in plan.groups_to_assign
    assert "tool_users" in plan.groups_to_assign
    assert "db_operators" not in plan.groups_to_assign
    assert "newgrp" in plan.session_refresh_guidance

def test_execute_group_assignments():
    target_conn = MagicMock(spec=HostConnection)
    target_conn.run_cmd.return_value = "tom"

    manifest = OnboardingManifest(
        application_groups={"terraform_users": ["terraform"]},
        local_group="tool_users"
    )

    mgr = GroupManager(target_conn=target_conn)
    plan = mgr.plan_group_assignments(username="tom", manifest=manifest, requested_tools=["terraform"])
    assigned = mgr.execute_group_assignments(plan)

    assert "terraform_users" in assigned
    assert target_conn.run_privileged.call_count >= 2
