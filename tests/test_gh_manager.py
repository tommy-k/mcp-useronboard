from unittest.mock import MagicMock
from mcp_useronboard.core.connection import HostConnection
from mcp_useronboard.modules.gh_manager import GHManager

def test_gh_migration_successful_auth():
    target_conn = MagicMock(spec=HostConnection)
    source_conn = MagicMock(spec=HostConnection)

    source_conn.run_cmd.return_value = "/home/tom"
    target_conn.run_cmd.side_effect = lambda cmd: (
        "/home/tom" if "eval echo" in cmd
        else "/opt/tools/bin/gh" if "command -v gh" in cmd
        else "github.com\n  ✓ Logged in to github.com account octocat (keyring)\n" if "auth status" in cmd
        else ""
    )
    source_conn.file_exists.side_effect = lambda p: "hosts.yml" in p
    source_conn.read_file.return_value = "github.com:\n  oauth_token: gho_secrettoken123\n"

    mgr = GHManager(target_conn=target_conn, source_conn=source_conn)
    plan = mgr.plan_gh_migration("tom")
    assert plan.source_has_gh_config is True

    result_plan = mgr.execute_gh_migration(plan)
    assert result_plan.hosts_migrated is True
    assert result_plan.auth_status == "authenticated"
    assert result_plan.authenticated_user == "octocat"
    assert result_plan.is_non_blocking_warning is False

def test_gh_migration_graceful_reauth_warning():
    target_conn = MagicMock(spec=HostConnection)
    source_conn = MagicMock(spec=HostConnection)

    source_conn.run_cmd.return_value = "/home/tom"
    target_conn.run_cmd.side_effect = lambda cmd: (
        "/home/tom" if "eval echo" in cmd
        else "/opt/tools/bin/gh" if "command -v gh" in cmd
        else "github.com: authentication failed: token expired or SAML SSO required\n" if "auth status" in cmd
        else ""
    )
    source_conn.file_exists.return_value = False

    mgr = GHManager(target_conn=target_conn, source_conn=source_conn)
    plan = mgr.plan_gh_migration("tom")
    result_plan = mgr.execute_gh_migration(plan)

    assert result_plan.auth_status == "needs_reauth"
    assert result_plan.is_non_blocking_warning is True
    assert "gh auth login" in result_plan.readdress_instructions
