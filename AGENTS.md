# Project guidance adapter

Before substantive work, read `.github/copilot-instructions.md` in full, resolving
the path from the repository root even when working below it. Read its referenced
repository-local skills when their task applies.

This is a reference, not an automatic include. Keep the existing instructions
canonical; do not duplicate them or replace the agent's own memory store.

## Execution-context clarification

The existing instructions describe a WSL2-hosted client. Verify the actual host,
account and shell: native Windows Hermes uses PowerShell, not a Linux shell.
For Linux administration, enter the verified local Ubuntu WSL2 context and use
its existing trusted SSH configuration as the shared guidance requires.
This checkout is not a live Proxmox guest; do not run guest deployment/bootstrap
commands locally. Client-specific tool names do not grant capabilities or bypass
approval boundaries. Historical task notes are not current authorization; use
TickTick rather than the retired pending-changes ledger for active tracking.
