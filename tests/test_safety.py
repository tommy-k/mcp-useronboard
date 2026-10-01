import os
import stat
import tempfile
import pytest
from unittest.mock import MagicMock, patch
from mcp_useronboard.core.security import EphemeralCredentialVault
from mcp_useronboard.core.connection import HostConnection
from mcp_useronboard.core.models import OnboardingManifest
from mcp_useronboard.modules.group_manager import GroupManager
from mcp_useronboard.modules.shell_manager import ShellManager
from mcp_useronboard.modules.gh_manager import GHManager
from mcp_useronboard.server import auto_onboard

def test_sudo_pass_file_mode_verification():
    vault = EphemeralCredentialVault.get_vault()

    with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
        f.write("super_secret_sudo_pass\n")
        temp_path = f.name

    try:
        # Insecure 0644 mode must be rejected
        os.chmod(temp_path, 0o644)
        with pytest.raises(PermissionError, match="Insecure permissions"):
            vault.load_sudo_pass_file(temp_path)

        # Secure 0600 mode must succeed
        os.chmod(temp_path, 0o600)
        vault.load_sudo_pass_file(temp_path, host="target-host")
        assert vault.get_sudo_password("target-host") == "super_secret_sudo_pass"
    finally:
        os.unlink(temp_path)

def test_auto_approve_environment_variable():
    vault = EphemeralCredentialVault(auto_approve=False)

    with patch.dict(os.environ, {"ONBOARDING_AUTO_APPROVE": "1"}):
        assert vault.confirm_privileged_action("target-host", "usermod -aG tool_users user", "Role assignment") is True

def test_shell_manager_uses_trailing_colon_chown():
    target_conn = MagicMock(spec=HostConnection)
    target_conn.run_cmd.return_value = ""
    target_conn.file_exists.return_value = False

    mgr = ShellManager(target_conn=target_conn)
    plan = mgr.plan_shell_migration(username="c5496a")
    mgr.execute_shell_migration(plan)

    # Verify chown uses trailing colon (chown 'c5496a': ...)
    assert any("chown 'c5496a':" in str(call) for call in target_conn.run_cmd.mock_calls)

def test_gh_manager_uses_trailing_colon_chown():
    target_conn = MagicMock(spec=HostConnection)
    target_conn.run_cmd.return_value = "gh version 2.50.0"
    target_conn.file_exists.return_value = False

    mgr = GHManager(target_conn=target_conn)
    plan = mgr.plan_gh_migration(username="c5496a")
    mgr.execute_gh_migration(plan)

    # Verify chown uses trailing colon (chown -R 'c5496a': ...)
    assert any("chown -R 'c5496a':" in str(call) for call in target_conn.run_cmd.mock_calls)
