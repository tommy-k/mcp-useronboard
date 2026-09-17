import json
from unittest.mock import MagicMock
from mcp_useronboard.core.connection import HostConnection
from mcp_useronboard.modules.manifest_reader import ManifestReader

def test_manifest_reader_parses_json():
    mock_conn = MagicMock(spec=HostConnection)
    mock_conn.file_exists.side_effect = lambda path: path == "/etc/mcp-migration/manifest.json"
    sample_manifest = {
        "generation": 2,
        "parent_host": "server-genesis.corp.local",
        "application_groups": {
            "terraform_users": ["terraform"],
            "git_users": ["gh"],
            "db_operators": ["psql-client"]
        },
        "local_group": "tool_users",
        "acl_path": "/opt/tools",
        "learned_rules": ["Rule 1"]
    }
    mock_conn.read_file.return_value = json.dumps(sample_manifest)

    reader = ManifestReader(mock_conn)
    manifest = reader.read_manifest()

    assert manifest.generation == 2
    assert manifest.parent_host == "server-genesis.corp.local"
    assert "terraform_users" in manifest.application_groups
    assert manifest.application_groups["terraform_users"] == ["terraform"]
    assert manifest.application_groups["git_users"] == ["gh"]

def test_manifest_reader_parses_skill_markdown():
    mock_conn = MagicMock(spec=HostConnection)
    mock_conn.file_exists.side_effect = lambda path: path == "/etc/mcp-migration/SKILL.md"
    skill_content = """# 🧠 Server Migration Lineage & Operational Skill

## Metadata
- **Generation**: 3
- **Parent Origin Host**: `server-stage.corp.local`
- **Primary Tool Directory**: `/opt/tools/bin`

## 👥 Application Groups (Onboarding Contract)
- **Group `terraform_users`**: Controls access to -> `terraform`
- **Group `git_users`**: Controls access to -> `gh`
"""
    mock_conn.read_file.return_value = skill_content

    reader = ManifestReader(mock_conn)
    manifest = reader.read_manifest()

    assert manifest.generation == 3
    assert manifest.parent_host == "server-stage.corp.local"
    assert "terraform_users" in manifest.application_groups
    assert "terraform" in manifest.application_groups["terraform_users"]
