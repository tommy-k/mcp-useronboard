import getpass
import sys
from typing import Dict, Optional

class EphemeralCredentialVault:
    """Manages sensitive credentials (like sudo passwords) strictly in volatile memory.
    Never persisted to disk, never included in logs or LLM responses."""
    _instance: Optional["EphemeralCredentialVault"] = None

    def __init__(self, auto_approve: bool = False):
        self._sudo_passwords: Dict[str, str] = {}
        self.auto_approve = auto_approve

    @classmethod
    def get_vault(cls, auto_approve: bool = False) -> "EphemeralCredentialVault":
        if cls._instance is None:
            cls._instance = EphemeralCredentialVault(auto_approve=auto_approve)
        elif auto_approve:
            cls._instance.auto_approve = True
        return cls._instance

    def set_sudo_password(self, host: str, password: str) -> None:
        self._sudo_passwords[host] = password

    def get_sudo_password(self, host: str) -> str:
        if host not in self._sudo_passwords:
            # If interactive TTY is available, prompt user
            if sys.stdin and sys.stdin.isatty():
                prompt = f"[mcp-useronboard] Enter sudo password for {host}: "
                pwd = getpass.getpass(prompt)
                self._sudo_passwords[host] = pwd
            else:
                return ""
        return self._sudo_passwords.get(host, "")

    def confirm_privileged_action(self, host: str, command: str, justification: str) -> bool:
        if self.auto_approve:
            return True
        if not (sys.stdin and sys.stdin.isatty()):
            return True
        print(f"\n[SECURITY GATE] Elevated Action Requested on {host}:")
        print(f"  Command:       {command}")
        print(f"  Justification: {justification}")
        choice = input("Authorize execution? [y/N]: ").strip().lower()
        return choice in ("y", "yes")

    def clear(self) -> None:
        self._sudo_passwords.clear()
