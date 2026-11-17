from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

class ToolRecipeSummary(BaseModel):
    name: str
    version: str = "latest"
    group: str = "tool_users"
    target_path: str = "/opt/tools/bin"
    download_url: Optional[str] = None

class OnboardingManifest(BaseModel):
    """The Onboarding Handover Contract left by mcp-servermigrate in /etc/mcp-migration/manifest.json."""
    generation: int = 1
    parent_host: Optional[str] = "unknown"
    migration_timestamp: Optional[str] = None
    application_groups: Dict[str, List[str]] = Field(default_factory=dict)
    local_group: str = "tool_users"
    ad_group: str = "Domain Users"
    acl_path: str = "/opt/tools"
    tools: Dict[str, Any] = Field(default_factory=dict)
    learned_rules: List[str] = Field(default_factory=list)

class GroupAssignmentPlan(BaseModel):
    target_user: str
    current_groups: List[str] = Field(default_factory=list)
    source_groups: List[str] = Field(default_factory=list)
    available_manifest_groups: Dict[str, List[str]] = Field(default_factory=dict)
    groups_to_assign: List[str] = Field(default_factory=list)
    assigned_groups: List[str] = Field(default_factory=list)
    session_refresh_guidance: str = ""

class HomeScriptItem(BaseModel):
    relative_path: str
    source_path: str
    target_path: str
    mode: str = "0750"

class ShellConfigPlan(BaseModel):
    target_user: str
    target_shell_file: str = "~/.bashrc"
    backup_path: Optional[str] = None
    migrated_aliases: List[str] = Field(default_factory=list)
    migrated_env_vars: Dict[str, str] = Field(default_factory=dict)
    migrated_custom_blocks: List[str] = Field(default_factory=list)
    personal_scripts: List[HomeScriptItem] = Field(default_factory=list)
    migrated_home_scripts: List[str] = Field(default_factory=list)
    syntax_verified: bool = False

class GHAuthPlan(BaseModel):
    target_user: str
    source_has_gh_config: bool = False
    hosts_migrated: bool = False
    config_migrated: bool = False
    gitconfig_migrated: bool = False
    auth_status: str = "unknown"  # "authenticated", "needs_reauth", "missing_config", "skipped"
    authenticated_user: Optional[str] = None
    is_non_blocking_warning: bool = False
    readdress_instructions: Optional[str] = None

class UserOnboardingPlan(BaseModel):
    target_host: str
    source_host: Optional[str] = None
    target_user: str
    group_plan: GroupAssignmentPlan
    shell_plan: ShellConfigPlan
    gh_plan: GHAuthPlan
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class OnboardingResult(BaseModel):
    success: bool
    target_host: str
    target_user: str
    groups_assigned: List[str] = Field(default_factory=list)
    shell_migrated: bool = False
    shell_backup_created: Optional[str] = None
    gh_auth_status: str = "unknown"
    gh_authenticated_user: Optional[str] = None
    gh_auth_warning: Optional[str] = None
    session_refresh_cmd: str = ""
    verification_output: Dict[str, Any] = Field(default_factory=dict)
    next_steps: List[str] = Field(default_factory=list)
