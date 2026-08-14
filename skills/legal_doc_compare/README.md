# legal-doc-compare

Compares an outside legal document against our legal corpus. The user pastes a
document (or names a file in `~/kidecon/workspace/inbox/`), and the agent:

1. refreshes the local read-only mirror of the protocol docs repo
   (`wrappers/docs_mirror.py` → `~/kidecon/workspace/legal-docs/`),
2. asks Lexor (`search.semantic`, direct MCP call via `wrappers/lexor_client.py`)
   which corpus documents are relevant,
3. reads the candidates locally and produces a gap-analysis report
   (covered / missing / extra / conflicts) with corpus citations, or an exact
   `text_diff` when the outside document is a variant of one corpus file.

The primary invocation path is the cognition loop: this skill is distributed
through the hub as prompt-injected instructions, executed via the `local_tool`
(`docs_sync`, `file_read`, `text_diff`, `file_append_markdown`) and
`lexor_call` step actions. `handler.py` exists for format parity only.

## Staff-only enforcement (three layers)

1. **Provisioning** — only staff agents get `api_key_github-docs` in the
   keyring (a read-only fine-grained PAT scoped to
   `kideconomy/kideconomy-protocol-docs`).
2. **Local tier gate** — `DocsMirror.sync()` refuses below hub tier 3 with a
   transparent three-part message; Lexor guidance calls carry their own gate.
3. **Read-only by construction** — the mirror only ever runs
   clone/fetch/merge `--ff-only`; no pushes, branches, or commits.

## Operator setup

1. Provision the credential (staff only):

   ```
   kidecon key add --name github-docs --value <read-only PAT>
   ```

2. Enable the mirror in `kidecon.yaml`:

   ```yaml
   docs:
     enabled: true
     repo_url: "https://github.com/kideconomy/kideconomy-protocol-docs.git"
     branch: "main"
   ```

3. Verify: `kidecon doctor` — `github-docs` appears under Keys (optional,
   present when provisioned).

## Publishing to the hub

Submit the hub manifest (see `hub-manifest/legal-doc-compare.json` in the
kidecon-hub repo `skills/` staging area, or build it from `instructions.md`):

```
kidecon skills submit --file legal-doc-compare.json
```

Staff approves it on the hub; it then goes live and is discoverable by all
agents. Non-staff agents can discover the skill but are blocked at execution
with a transparency message.

## Failure behavior

Every failure degrades gracefully with a three-part message (what happened /
why / what to do next): staff-only block, missing credential, clone/fetch
failure (continues with the last local copy and discloses staleness), Lexor
down (local-only comparison, disclosed), unsupported format (asks for text
export). A mirror failure never crashes a user turn.
