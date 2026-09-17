import os
from typing import Optional, List
from mcp.server.fastmcp import FastMCP
from mcp_useronboard.core.connection import HostConnection
from mcp_useronboard.core.security import EphemeralCredentialVault
from mcp_useronboard.core.models import UserOnboardingPlan
from mcp_useronboard.modules.manifest_reader import ManifestReader
from mcp_useronboard.modules.group_manager import GroupManager
from mcp_useronboard.modules.shell_manager import ShellManager
from mcp_useronboard.modules.gh_manager import GHManager
from mcp_useronboard.modules.verifier import PostOnboardingVerifier

mcp = FastMCP("Enterprise-User-Onboard-Agent")

def _resolve_username(user: Optional[str]) -> str:
    return user or os.environ.get("USER") or os.environ.get("USERNAME") or "root"

@mcp.tool()
def audit_onboarding_contract(target_host: str = "localhost", username: str = "") -> str:
    """Inspects target host for /etc/mcp-migration/manifest.json and audits available application role groups and tools."""
    user = _resolve_username(username)
    tgt_conn = HostConnection(host=target_host, user=user)
    manifest = ManifestReader(tgt_conn).read_manifest()
    curr_groups = GroupManager(tgt_conn).get_user_groups(tgt_conn, user)
    tgt_conn.close()

    result = {
        "target_host": target_host,
        "user": user,
        "current_user_groups": curr_groups,
        "manifest_generation": manifest.generation,
        "parent_origin_host": manifest.parent_host,
        "available_application_groups": manifest.application_groups,
        "primary_tool_directory": manifest.acl_path,
        "learned_rules": manifest.learned_rules
    }
    import json
    return json.dumps(result, indent=2)

@mcp.tool()
def plan_onboarding(
    target_host: str = "localhost",
    source_host: Optional[str] = None,
    username: str = "",
    requested_tools: Optional[List[str]] = None,
    requested_groups: Optional[List[str]] = None
) -> str:
    """Generates a complete onboarding plan: calculates needed role groups, extracts shell preferences, and stages GitHub credentials."""
    user = _resolve_username(username)
    tgt_conn = HostConnection(host=target_host, user=user)
    src_conn = HostConnection(host=source_host, user=user) if source_host else None

    manifest = ManifestReader(tgt_conn).read_manifest()
    grp_mgr = GroupManager(tgt_conn, src_conn)
    shell_mgr = ShellManager(tgt_conn, src_conn)
    gh_mgr = GHManager(tgt_conn, src_conn)

    grp_plan = grp_mgr.plan_group_assignments(user, manifest, requested_tools, requested_groups)
    shell_plan = shell_mgr.plan_shell_migration(user)
    gh_plan = gh_mgr.plan_gh_migration(user)

    plan = UserOnboardingPlan(
        target_host=target_host,
        source_host=source_host,
        target_user=user,
        group_plan=grp_plan,
        shell_plan=shell_plan,
        gh_plan=gh_plan
    )

    tgt_conn.close()
    if src_conn:
        src_conn.close()

    return plan.model_dump_json(indent=2)

@mcp.tool()
def execute_onboarding(
    target_host: str = "localhost",
    source_host: Optional[str] = None,
    username: str = "",
    requested_tools: Optional[List[str]] = None,
    requested_groups: Optional[List[str]] = None,
    auto_approve_sudo: bool = False
) -> str:
    """Executes end-to-end user onboarding: assigns role groups via sudo, merges shell preferences cleanly, migrates gh credentials, and runs post-onboarding verification."""
    EphemeralCredentialVault.get_vault(auto_approve=auto_approve_sudo)
    user = _resolve_username(username)
    tgt_conn = HostConnection(host=target_host, user=user)
    src_conn = HostConnection(host=source_host, user=user) if source_host else None

    manifest = ManifestReader(tgt_conn).read_manifest()
    grp_mgr = GroupManager(tgt_conn, src_conn)
    shell_mgr = ShellManager(tgt_conn, src_conn)
    gh_mgr = GHManager(tgt_conn, src_conn)

    grp_plan = grp_mgr.plan_group_assignments(user, manifest, requested_tools, requested_groups)
    grp_mgr.execute_group_assignments(grp_plan)

    shell_plan = shell_mgr.plan_shell_migration(user)
    shell_mgr.execute_shell_migration(shell_plan)

    gh_plan = gh_mgr.plan_gh_migration(user)
    gh_plan = gh_mgr.execute_gh_migration(gh_plan)

    full_plan = UserOnboardingPlan(
        target_host=target_host,
        source_host=source_host,
        target_user=user,
        group_plan=grp_plan,
        shell_plan=shell_plan,
        gh_plan=gh_plan
    )

    verifier = PostOnboardingVerifier(tgt_conn)
    result = verifier.verify(full_plan, manifest)

    tgt_conn.close()
    if src_conn:
        src_conn.close()

    return result.model_dump_json(indent=2)

@mcp.tool()
def verify_user_access(target_host: str = "localhost", username: str = "") -> str:
    """Verifies that the user has group rights, access to /opt/tools binaries, valid shell syntax, and checks gh status."""
    user = _resolve_username(username)
    tgt_conn = HostConnection(host=target_host, user=user)
    manifest = ManifestReader(tgt_conn).read_manifest()

    grp_mgr = GroupManager(tgt_conn)
    shell_mgr = ShellManager(tgt_conn)
    gh_mgr = GHManager(tgt_conn)

    grp_plan = grp_mgr.plan_group_assignments(user, manifest)
    shell_plan = shell_mgr.plan_shell_migration(user)
    gh_plan = gh_mgr.plan_gh_migration(user)
    gh_plan = gh_mgr.verify_gh_status(gh_plan)

    full_plan = UserOnboardingPlan(
        target_host=target_host,
        target_user=user,
        group_plan=grp_plan,
        shell_plan=shell_plan,
        gh_plan=gh_plan
    )

    verifier = PostOnboardingVerifier(tgt_conn)
    result = verifier.verify(full_plan, manifest)
    tgt_conn.close()

    return result.model_dump_json(indent=2)
