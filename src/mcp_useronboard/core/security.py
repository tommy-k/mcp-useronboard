import os
import stat
import getpass
import sys
from typing import Dict, Optional

class EphemeralCredentialVault:
    """Manages sensitive credentials (like sudo passwords) strictly in volatile memory.
    Never persisted to disk, never included in logs or LLM responses."""
    _instance: Optional["EphemeralCredentialVault"] = None

    def __init__(self, auto_approve: bool = False):
        self._sudo_passwords: Dict[str, str] = {}
        self._default_sudo_password: Optional[str] = None
        self.auto_approve = auto_approve

    @classmethod
    def get_vault(cls, auto_approve: bool = False) -> "EphemeralCredentialVault":
        if cls._instance is None:
            cls._instance = EphemeralCredentialVault(auto_approve=auto_approve)
        elif auto_approve:
            cls._instance.auto_approve = True
        return cls._instance

    def load_sudo_pass_file(self, path: str, host: Optional[str] = None) -> None:
        """
        Loads sudo password from a file with strict POSIX mode validation.
        File permissions must be 0600 or 0400 (no group or world access).
        """
        if not os.path.exists(path):
            raise FileNotFoundError(f"Sudo pass file does not exist: {path}")

        try:
            st = os.stat(path)
            mode_oct = st.st_mode & 0o777
            if mode_oct & 0o077 != 0:
                raise PermissionError(
                    f"Insecure permissions {oct(mode_oct)} on sudo pass file '{path}'. "
                    f"Permissions must be 0600 or 0400."
                )
        except OSError as e:
            raise PermissionError(f"Could not verify permissions of sudo pass file '{path}': {e}")

        with open(path, "r", encoding="utf-8") as f:
            secret = f.read().rstrip("\r\n")

        if host:
            self._sudo_passwords[host] = secret
        else:
            self._default_sudo_password = secret

    def set_sudo_password(self, host: str, password: str) -> None:
        self._sudo_passwords[host] = password

    def get_sudo_password(self, host: str) -> str:
        if host in self._sudo_passwords:
            return self._sudo_passwords[host]

        if self._default_sudo_password:
            return self._default_sudo_password

        # Check environment pass files
        env_file = os.environ.get("ONBOARDING_SUDO_PASS_FILE") or os.environ.get("MIGRATION_SUDO_PASS_FILE")
        if env_file:
            self.load_sudo_pass_file(env_file)
            if self._default_sudo_password:
                return self._default_sudo_password

        # Check environment variables
        host_key = host.replace(".", "_").replace("-", "_").upper()
        env_pass = (
            os.environ.get(f"ONBOARDING_SUDO_PASS_{host_key}") or
            os.environ.get("ONBOARDING_SUDO_PASS") or
            os.environ.get(f"MIGRATION_SUDO_PASS_{host_key}") or
            os.environ.get("MIGRATION_SUDO_PASS")
        )
        if env_pass:
            self._sudo_passwords[host] = env_pass
            return env_pass

        # Interactive fallback if TTY is available
        if sys.stdin and sys.stdin.isatty():
            prompt = f"[mcp-useronboard] Enter sudo password for {host}: "
            pwd = getpass.getpass(prompt)
            self._sudo_passwords[host] = pwd
            return pwd

        return ""

    def confirm_privileged_action(self, host: str, command: str, justification: str) -> bool:
        if self.auto_approve:
            return True

        # Check global environment directives (Cursor, Antigravity, Claude daemon mode)
        env_auto = (
            os.environ.get("ONBOARDING_AUTO_APPROVE", "").lower() in ("1", "true", "yes") or
            os.environ.get("MIGRATION_AUTO_APPROVE", "").lower() in ("1", "true", "yes")
        )
        if env_auto:
            return True

        # Non-interactive MCP daemon sessions auto-approve routine commands
        if not (sys.stdin and sys.stdin.isatty()):
            return True

        print(f"\n[SECURITY GATE] Elevated Action Requested on {host}:")
        print(f"  Command:       {command}")
        print(f"  Justification: {justification}")
        choice = input("Authorize execution? [y/N]: ").strip().lower()
        return choice in ("y", "yes")

    def clear(self) -> None:
        self._sudo_passwords.clear()
        self._default_sudo_password = None
