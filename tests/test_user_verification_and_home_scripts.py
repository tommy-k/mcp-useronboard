from unittest.mock import MagicMock
from mcp_useronboard.core.connection import HostConnection
from mcp_useronboard.core.models import (
    OnboardingManifest, UserOnboardingPlan, GroupAssignmentPlan,
    ShellConfigPlan, GHAuthPlan
)
from mcp_useronboard.modules.group_manager import GroupManager
from mcp_useronboard.modules.shell_manager import ShellManager
from mcp_useronboard.modules.verifier import PostOnboardingVerifier


def test_verifier_runs_as_actual_user_and_checks_path():
    tgt_conn = MagicMock(spec=HostConnection)
    tgt_conn.user = "root"
    tgt_conn.run_cmd.side_effect = lambda cmd: (
        "alice tool_users" if "id -Gn" in cmd else
        "/home/alice" if "eval echo" in cmd else ""
    )
    tgt_conn.run_privileged.side_effect = lambda cmd, just="": (
        "EXECUTABLE:/usr/local/bin/gh" if "'gh'" in cmd else "NOT_EXECUTABLE"
    )

    manifest = OnboardingManifest(
        application_groups={"tool_users": ["gh", "terraform"]},
        local_group="tool_users",
    )
    plan = UserOnboardingPlan(
        target_host="tgt.corp",
        target_user="alice",
        group_plan=GroupAssignmentPlan(target_user="alice", groups_to_assign=["tool_users"]),
        shell_plan=ShellConfigPlan(target_user="alice", syntax_verified=True),
        gh_plan=GHAuthPlan(target_user="alice", auth_status="authenticated", authenticated_user="alice"),
    )

    result = PostOnboardingVerifier(tgt_conn).verify(plan, manifest)

    # Verified via su -l 'alice' (NOT as root)
    priv_cmds = [c.args[0] for c in tgt_conn.run_privileged.mock_calls]
    assert any("su -s /bin/bash -l 'alice'" in c and "command -v 'gh'" in c for c in priv_cmds)

    # gh succeeded, terraform failed -> overall success must be False!
    assert result.verification_output["tools_accessible"]["gh"] is True
    assert result.verification_output["tool_paths"]["gh"] == "/usr/local/bin/gh"
    assert result.verification_output["tools_accessible"]["terraform"] is False
    assert result.success is False


def test_personal_home_scripts_migrated_for_migrating_user():
    src_conn = MagicMock(spec=HostConnection)
    tgt_conn = MagicMock(spec=HostConnection)

    src_conn.run_cmd.side_effect = lambda cmd: (
        "/home/alice" if "eval echo" in cmd else
        "750|/home/alice/bin/mytool.sh\n750|/home/alice/.local/bin/helper\n" if "find " in cmd else ""
    )
    src_conn.file_exists.return_value = False
    src_conn.read_bytes.return_value = b"#!/bin/bash\necho personal\n"

    tgt_conn.run_cmd.side_effect = lambda cmd: "/home/alice" if "eval echo" in cmd else ""
    tgt_conn.file_exists.return_value = False

    mgr = ShellManager(target_conn=tgt_conn, source_conn=src_conn)
    plan = mgr.plan_shell_migration("alice")

    assert len(plan.personal_scripts) == 2
    assert plan.personal_scripts[0].target_path == "/home/alice/bin/mytool.sh"

    ok = mgr.execute_shell_migration(plan)
    assert ok is True
    assert len(plan.migrated_home_scripts) == 2
    assert tgt_conn.write_bytes.call_count == 2
    # Ensure $HOME/bin is added to PATH in .bashrc
    written_bashrc = tgt_conn.write_file.call_args.args[1]
    assert "$HOME/bin:$HOME/.local/bin:$HOME/scripts:$PATH" in written_bashrc


def test_new_user_without_source_server_gets_tool_users_and_no_source_scripts():
    tgt_conn = MagicMock(spec=HostConnection)
    tgt_conn.run_cmd.return_value = "newuser"
    tgt_conn.file_exists.return_value = False

    manifest = OnboardingManifest(
        application_groups={"tool_users": ["gh", "terraform", "kubectl"]},
        local_group="tool_users",
    )

    grp_plan = GroupManager(target_conn=tgt_conn).plan_group_assignments("newuser", manifest)
    assert "tool_users" in grp_plan.groups_to_assign

    shell_plan = ShellManager(target_conn=tgt_conn, source_conn=None).plan_shell_migration("newuser")
    assert shell_plan.personal_scripts == []
    assert shell_plan.migrated_aliases == []
