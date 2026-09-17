import os
import subprocess
from typing import Optional
import paramiko
from mcp_useronboard.core.security import EphemeralCredentialVault

class HostConnection:
    """Unified connection abstraction supporting both Local (subprocess) and Remote (SSH) execution
    with transparent privilege escalation (sudo -S) and fallback."""

    def __init__(self, host: str = "localhost", user: Optional[str] = None, port: int = 22, key_filename: Optional[str] = None):
        self.host = host or "localhost"
        self.is_local = self.host.lower() in ("localhost", "127.0.0.1", "local")
        self.user = user or (os.environ.get("USER") or os.environ.get("USERNAME") or "root")
        self.port = port
        self.key_filename = key_filename
        self._ssh_client: Optional[paramiko.SSHClient] = None
        self._is_connected = False

    def connect(self) -> None:
        if self.is_local or self._is_connected:
            return
        self._ssh_client = paramiko.SSHClient()
        self._ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._ssh_client.connect(
            hostname=self.host,
            port=self.port,
            username=self.user,
            key_filename=self.key_filename,
            timeout=10
        )
        self._is_connected = True

    def close(self) -> None:
        if self._ssh_client and self._is_connected:
            self._ssh_client.close()
            self._is_connected = False

    def run_cmd(self, command: str) -> str:
        """Executes a command without privilege escalation."""
        if self.is_local:
            res = subprocess.run(["bash", "-c", command], capture_output=True, text=True)
            return res.stdout
        else:
            self.connect()
            assert self._ssh_client is not None
            _, stdout, stderr = self._ssh_client.exec_command(command)
            return stdout.read().decode("utf-8")

    def run_privileged(self, command: str, justification: str = "Privileged operation") -> str:
        """Executes a command with sudo, supplying password safely via stdin."""
        vault = EphemeralCredentialVault.get_vault()
        if not vault.confirm_privileged_action(self.host, command, justification):
            raise PermissionError(f"Execution of '{command}' on {self.host} was rejected by operator.")

        if self.is_local:
            # Check if current user is already root
            if os.geteuid() == 0:
                res = subprocess.run(["bash", "-c", command], capture_output=True, text=True)
                if res.returncode != 0:
                    raise RuntimeError(f"Privileged local command failed (code {res.returncode}): {res.stderr}")
                return res.stdout

            password = vault.get_sudo_password(self.host)
            proc = subprocess.Popen(
                ["sudo", "-S", "-p", "", "bash", "-c", command],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            stdout, stderr = proc.communicate(input=f"{password}\n")
            if proc.returncode != 0:
                raise RuntimeError(f"Local sudo command failed (code {proc.returncode}): {stderr.strip()}")
            return stdout
        else:
            self.connect()
            assert self._ssh_client is not None
            # If user is root, execute directly
            if self.user == "root":
                _, stdout, stderr = self._ssh_client.exec_command(command)
                status = stdout.channel.recv_exit_status()
                out = stdout.read().decode("utf-8")
                err = stderr.read().decode("utf-8")
                if status != 0 and err.strip():
                    raise RuntimeError(f"Root command failed (code {status}): {err.strip()}")
                return out

            password = vault.get_sudo_password(self.host)
            stdin, stdout, stderr = self._ssh_client.exec_command(f"sudo -S -p '' bash -c {subprocess.list2cmdline([command])}")
            stdin.write(f"{password}\n")
            stdin.flush()
            status = stdout.channel.recv_exit_status()
            out = stdout.read().decode("utf-8")
            err = stderr.read().decode("utf-8")
            if status != 0 and err.strip():
                raise RuntimeError(f"Remote sudo command failed (code {status}): {err.strip()}")
            return out

    def run_with_sudo_fallback(self, command: str, justification: str = "Fallback privileged operation") -> str:
        """Executes unprivileged first; if permission denied or error occurs, retries via sudo."""
        out = self.run_cmd(f"{command} 2>&1")
        if "Permission denied" in out or "Operation not permitted" in out:
            return self.run_privileged(command, justification=f"{justification} (permission denied on unprivileged attempt)")
        return out

    def read_file(self, path: str) -> Optional[str]:
        """Reads a file, falling back to privileged read if necessary."""
        cmd = f"test -f {path} && cat {path}"
        out = self.run_cmd(cmd)
        if not out and ("Permission denied" in out or not self.file_exists(path)):
            if self.file_exists(path):
                out = self.run_privileged(f"cat {path}", f"Read protected file {path}")
            else:
                return None
        return out if out else None

    def file_exists(self, path: str) -> bool:
        res = self.run_cmd(f"test -e {path} && echo 'EXISTS' || echo 'MISSING'").strip()
        return "EXISTS" in res

    def write_file(self, path: str, content: str, mode: str = "644", privileged: bool = False) -> None:
        """Writes content to a file. Supports privileged write."""
        escaped_content = content.replace("'", "'\\''")
        write_cmd = f"mkdir -p $(dirname {path}) && cat << 'MCP_EOF' > {path}\n{content}\nMCP_EOF\nchmod {mode} {path}"
        if privileged:
            self.run_privileged(write_cmd, f"Write file {path}")
        else:
            self.run_cmd(write_cmd)
