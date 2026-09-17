import json
import re
from typing import Optional, Dict, List
from mcp_useronboard.core.connection import HostConnection
from mcp_useronboard.core.models import OnboardingManifest

MANIFEST_PATH = "/etc/mcp-migration/manifest.json"
SKILL_PATH = "/etc/mcp-migration/SKILL.md"

class ManifestReader:
    """Reads and parses the Onboarding Handover Contract left by mcp-servermigrate."""

    def __init__(self, conn: HostConnection):
        self.conn = conn

    def read_manifest(self) -> OnboardingManifest:
        """Attempts to read manifest.json first, falls back to SKILL.md, or discovers local tool groups."""
        # 1. Try reading manifest.json
        if self.conn.file_exists(MANIFEST_PATH):
            content = self.conn.read_file(MANIFEST_PATH)
            if content:
                try:
                    data = json.loads(content)
                    return OnboardingManifest.model_validate(data)
                except Exception:
                    pass

        # 2. Try parsing SKILL.md
        if self.conn.file_exists(SKILL_PATH):
            skill_content = self.conn.read_file(SKILL_PATH)
            if skill_content:
                parsed = self._parse_skill_markdown(skill_content)
                if parsed:
                    return parsed

        # 3. Fallback: Discover existing groups and /opt/tools if manifest not planted
        return self._discover_system_fallback()

    def _parse_skill_markdown(self, markdown: str) -> Optional[OnboardingManifest]:
        """Extracts application groups and metadata from SKILL.md."""
        try:
            app_groups: Dict[str, List[str]] = {}
            # Match: - **Group `terraform_users`**: Controls access to -> `terraform`
            pattern = re.compile(r"- \*\*Group `([^`]+)`\*\*: Controls access to -> (.+)")
            for line in markdown.splitlines():
                match = pattern.search(line)
                if match:
                    group_name = match.group(1).strip()
                    apps_raw = match.group(2).strip()
                    # extract `app1`, `app2`
                    apps = re.findall(r"`([^`]+)`", apps_raw)
                    app_groups[group_name] = apps

            # Extract metadata
            gen_match = re.search(r"- \*\*Generation\*\*: (\d+)", markdown)
            generation = int(gen_match.group(1)) if gen_match else 1

            parent_match = re.search(r"- \*\*Parent Origin Host\*\*: `([^`]+)`", markdown)
            parent_host = parent_match.group(1) if parent_match else "unknown"

            path_match = re.search(r"- \*\*Primary Tool Directory\*\*: `([^`]+)`", markdown)
            acl_path = path_match.group(1).replace("/bin", "") if path_match else "/opt/tools"

            return OnboardingManifest(
                generation=generation,
                parent_host=parent_host,
                application_groups=app_groups,
                acl_path=acl_path
            )
        except Exception:
            return None

    def _discover_system_fallback(self) -> OnboardingManifest:
        """Discovers custom local application groups if no migration manifest exists on the host."""
        app_groups: Dict[str, List[str]] = {}
        out = self.conn.run_cmd("getent group | awk -F: '$3 >= 1000 || $1 ~ /_users|_ops|_dev/ { print $1 }'")
        for grp in out.strip().splitlines():
            grp = grp.strip()
            if grp and grp not in ("nobody", "nfsnobody"):
                app_groups[grp] = []

        # Check /opt/tools/bin binaries if present
        binaries_out = self.conn.run_cmd("test -d /opt/tools/bin && ls -1 /opt/tools/bin || true")
        tools = [b.strip() for b in binaries_out.strip().splitlines() if b.strip()]
        if "tool_users" in app_groups and tools:
            app_groups["tool_users"] = tools

        return OnboardingManifest(
            generation=1,
            parent_host="unmanaged_baseline",
            application_groups=app_groups,
            acl_path="/opt/tools" if self.conn.file_exists("/opt/tools") else "/usr/local"
        )
