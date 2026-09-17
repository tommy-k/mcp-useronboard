# 🚀 mcp-useronboard: Universal Enterprise Linux User Onboarding MCP Agent & CLI

[![Protocol: MCP](https://img.shields.io/badge/Protocol-Model%20Context%20Protocol-8A2BE2.svg)](https://modelcontextprotocol.io/)
[![Clients: Universal](https://img.shields.io/badge/Clients-Claude%20%7C%20Cursor%20%7C%20Antigravity%20%7C%20Windsurf%20%7C%20VS%20Code-blue.svg)](https://modelcontextprotocol.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

An intelligent, universal **Model Context Protocol (MCP)** agent and CLI designed for seamlessly onboarding users onto newly migrated or provisioned **Enterprise Linux** servers (RHEL, Rocky, AlmaLinux, Oracle Linux, Fedora).

`mcp-useronboard` is **100% client-agnostic**. It works natively with:
* **Anthropic Claude Desktop** & **Claude Code CLI**
* **Cursor AI IDE**
* **Google Antigravity / Gemini CLI**
* **Windsurf (Codeium Cascade)**
* **VS Code** (via Continue, Cline, or Roo Code)
* **Remote SSE / Streamable HTTP** network agents

`mcp-useronboard` consumes the **Onboarding Handover Contract** produced by [`mcp-servermigrate`](https://github.com/tommy-k/mcp-servermigrate), automatically aligning user roles to custom application groups, non-destructively preserving shell preferences, and validating developer credentials.

---

## 🌟 Key Capabilities

* 🤝 **Onboarding Handover Contract Consumer**
  * Directly reads `/etc/mcp-migration/manifest.json` and on-server operational skills (`SKILL.md`) left by `mcp-servermigrate`.
  * Dynamically maps role groups (e.g., `terraform_users`, `git_users`, `db_operators`) to controlled binaries in `/opt/tools/bin` without hardcoded assumptions.
* 👥 **Privileged Group & Role Assignment**
  * Inspects existing user groups on target and source hosts (`id -Gn <user>`).
  * Executes elevated group modifications (`sudo usermod -aG <group> <user>`) using safe, in-memory ephemeral credentials.
  * Solves Linux session cache invalidation by automatically providing actionable session refresh guidance (`newgrp <group>` or `exec su -l $USER`).
* 🐚 **Non-Destructive Shell & Dotfile Migration**
  * Safely migrates user aliases (`alias k=kubectl`), personal environment variables (`EDITOR`, `PAGER`), prompts (`PS1`, Starship), and completions.
  * Avoids clobbering system baselines and `/etc/profile.d/corp-standards.sh` tool paths.
  * **Safety Guardrails:** Always generates a timestamped backup (`~/.bashrc.pre-onboard.<timestamp>`), updates an idempotent managed block, and runs `bash -n` syntax verification before applying changes.
* 🔐 **GitHub CLI (`gh`) & Git Credential Handover**
  * Migrates `~/.config/gh/hosts.yml`, `~/.config/gh/config.yml`, and `~/.gitconfig` while enforcing strict POSIX permissions (`chmod 700 ~/.config/gh`, `chmod 600 hosts.yml`).
  * Runs real-time verification (`gh auth status` and `gh api user`).
  * **Graceful Failure Handling:** If corporate SAML SSO, IP restrictions, or token expiration blocks authentication, it flags a clear non-blocking advisory with exact login instructions (`gh auth login --hostname github.com --web`) to address on the side without halting the rest of onboarding.
* 🌐 **Universal Transport Modes**
  * **stdio:** Standard I/O subprocess for local agents (Claude Desktop, Cursor, Antigravity, Claude Code).
  * **SSE (Server-Sent Events) & Streamable HTTP:** For web UIs, remote Claude instances, or network jump-hosts (`mcp-useronboard serve --transport sse --port 8000`).
  * **Interactive CLI:** Rich terminal interface with dry-run support, tables, and spinners.

---

## 🏗️ Architecture & Workflow

```mermaid
flowchart TD
    Start(["User or AI Agent Launches Onboarding"]) --> ReadManifest["1. Read /etc/mcp-migration/manifest.json<br/>(Discover Application Groups & Tool Matrix)"]
    ReadManifest --> AuditSource["2. Audit User Groups & Preferences<br/>(Evaluate target host & optional source host)"]
    AuditSource --> Plan["3. Generate Comprehensive Onboarding Plan<br/>(Group delta, shell preferences, gh configs)"]
    Plan --> Elevate["4. Privileged Group Assignment<br/>(sudo usermod -aG &lt;groups&gt; &lt;user&gt;)"]
    Elevate --> ShellSync["5. Safe Shell Migration<br/>(Backup ~/.bashrc, merge managed block, bash -n check)"]
    ShellSync --> MigrateGH["6. Migrate GitHub & Git Configurations<br/>(Enforce chmod 600, test gh auth status)"]
    MigrateGH --> CheckAuth{"gh auth valid?"}
    CheckAuth -->|"Yes"| Verified["✅ Fully Authenticated"]
    CheckAuth -->|"Needs SAML / Expired"| Warning["⚠️ Flag Out-of-Band Warning<br/>(gh auth login --web)"]
    Verified --> Report["7. Compile Post-Flight Verification & Refresh Guidance"]
    Warning --> Report
    Report --> End(["Session Ready! (newgrp &lt;group&gt;)"])
```

---

## 📥 Installation

Clone the repository and set up a virtual environment (Python 3.11+ required):

```bash
# 1. Clone repository
git clone https://github.com/tommy-k/mcp-useronboard.git
cd mcp-useronboard

# 2. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install in editable mode
pip install --upgrade pip
pip install -e .
```

---

## 🔌 Universal MCP Client Configuration

`mcp-useronboard` includes a built-in helper command to display or generate the exact configuration for any client:

```bash
# Print configuration for your specific client
mcp-useronboard config --client claude
mcp-useronboard config --client cursor
mcp-useronboard config --client windsurf
mcp-useronboard config --client vscode
mcp-useronboard config --client all
```

### 1. Anthropic Claude Desktop
Add this to your `claude_desktop_config.json`:
* **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
* **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
* **Linux:** `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "user-onboard": {
      "command": "<path-to-repo>/.venv/bin/python",
      "args": ["-m", "mcp_useronboard.server"]
    }
  }
}
```

### 2. Anthropic Claude Code CLI
Add directly via the CLI:
```bash
claude mcp add user-onboard -- <path-to-repo>/.venv/bin/python -m mcp_useronboard.server
```

### 3. Cursor IDE
In your workspace `.cursor/mcp.json` or global `~/.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "user-onboard": {
      "command": "<path-to-repo>/.venv/bin/python",
      "args": ["-m", "mcp_useronboard.server"]
    }
  }
}
```

### 4. Windows Host Bridging into WSL (for Claude or Cursor)
If your AI IDE runs on Windows and the environment is inside WSL:
```json
{
  "mcpServers": {
    "user-onboard": {
      "command": "wsl.exe",
      "args": [
        "-d", "<your-wsl-distro-name>",
        "bash", "-c",
        "cd <path-to-repo> && source .venv/bin/activate && python -m mcp_useronboard.server"
      ]
    }
  }
}
```

### 5. Remote SSE / HTTP Network Transport
To host the agent as a remote HTTP/SSE service for network clients:
```bash
mcp-useronboard serve --transport sse --host 0.0.0.0 --port 8000
```

---

### 🛠️ Exposed MCP Tools

| Tool Name | Parameters | Description |
| :--- | :--- | :--- |
| `audit_onboarding_contract` | `target_host`, `username` | Inspects `/etc/mcp-migration/manifest.json` and audits role groups, tools, and current memberships. |
| `plan_onboarding` | `target_host`, `source_host`, `username`, `requested_tools`, `requested_groups` | Calculates group assignments, extracts shell preferences, and inspects GitHub CLI configurations. |
| `execute_onboarding` | `target_host`, `source_host`, `username`, `requested_tools`, `requested_groups`, `auto_approve_sudo` | Executes end-to-end onboarding: applies groups with sudo, merges dotfiles with backup & syntax check, migrates `gh`, and verifies access. |
| `verify_user_access` | `target_host`, `username` | Verifies group memberships, tool executability in `/opt/tools/bin`, bash syntax, and GitHub auth status. |

---

## 💻 CLI Usage Examples

You can also run `mcp-useronboard` directly from the command line:

### 1. Audit Target Server Contract
```bash
mcp-useronboard audit --target target-host.corp.local --user tom
```

### 2. Dry-Run Onboarding Plan
```bash
mcp-useronboard onboard --target target-host.corp.local --tools "terraform,gh" --dry-run
```

### 3. End-to-End Onboarding Execution
```bash
# Onboards user 'tom' to target host, syncing dotfiles from source server
mcp-useronboard onboard \
  --target target-host.corp.local \
  --source source-host.corp.local \
  --user tom \
  --tools "terraform,gh" \
  --auto-approve-sudo
```

---

## 🧪 Testing

Run the automated pytest suite:

```bash
source .venv/bin/activate
pytest tests/ -v
```

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
