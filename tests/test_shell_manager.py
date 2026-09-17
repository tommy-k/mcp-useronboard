from unittest.mock import MagicMock
from mcp_useronboard.core.connection import HostConnection
from mcp_useronboard.modules.shell_manager import ShellManager, BLOCK_START, BLOCK_END

def test_parse_shell_preferences():
    sample_shell = r"""
# System definitions
if [ -f /etc/bashrc ]; then
    . /etc/bashrc
fi

# User aliases
alias k='kubectl'
alias ll='ls -la'
export EDITOR=vim
export PROJECT_DIR=/workspace/myproject
export PATH=/opt/tools/bin:$PATH
PS1='[\u@\h \W]\$ '
"""
    mock_conn = MagicMock(spec=HostConnection)
    mgr = ShellManager(target_conn=mock_conn)
    parsed = mgr.parse_shell_preferences(sample_shell)

    assert "alias k='kubectl'" in parsed["aliases"]
    assert "alias ll='ls -la'" in parsed["aliases"]
    assert "export EDITOR=vim" in parsed["exports"]
    assert "export PROJECT_DIR=/workspace/myproject" in parsed["exports"]
    # PATH containing /opt/tools should be filtered out to preserve /etc/profile.d/ standards
    assert not any("PATH=" in exp for exp in parsed["exports"])
    assert any("PS1=" in c for c in parsed["custom"])

def test_execute_shell_migration_preserves_and_backs_up():
    target_conn = MagicMock(spec=HostConnection)
    target_conn.run_cmd.side_effect = lambda cmd: "/home/tom" if "eval echo" in cmd else ""
    target_conn.file_exists.return_value = True
    target_conn.read_file.return_value = "# Original target ~/.bashrc\nalias target_alias='echo target'\n"

    mgr = ShellManager(target_conn=target_conn)
    plan = mgr.plan_shell_migration("tom")
    plan.migrated_aliases = ["alias myalias='echo 123'"]

    success = mgr.execute_shell_migration(plan)

    assert success is True
    assert plan.syntax_verified is True
    assert plan.backup_path is not None
    # Verify write_file called for backup and new content
    assert target_conn.write_file.call_count >= 2
