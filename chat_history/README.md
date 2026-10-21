# Chat history

This folder contains the OpenCode session that built UnknownID.

| File | Contents |
|---|---|
| [`transcript.md`](transcript.md) | Readable transcript: user and assistant messages plus summarised tool calls. Internal reasoning and raw tool output are omitted. |
| [`session.json`](session.json) | Complete OpenCode V2 session export. Includes internal reasoning, raw tool inputs/outputs, local absolute paths and the full command history. |

> **Privacy warning:** `session.json` is a raw agent transcript, not a polished
> document. Review it before sharing the repository widely. It contains local
> filesystem paths and internal reasoning. It does **not** contain GitHub
> tokens, API keys or passwords (checked before publishing).

## Import the session into OpenCode

```bash
opencode session import chat_history/session.json
```

Then open the imported session from the session list:

```bash
opencode session list
```

## Export a session yourself

```bash
# List sessions and find the ID
opencode session list

# Full export (what session.json is)
opencode session export <session-id> > chat_history/session.json

# Redacted export (paths and sensitive file data removed)
opencode session export <session-id> --sanitize > chat_history/session-redacted.json
```

The session ID for this build is `ses_ea2fb63d2ffeG6qZ1S5ujWrrUh`.

## Share a live session

OpenCode V2 documents `session export` / `session import` as the supported
portable format. There is no documented public share-link command in the V2
docs index (`https://opencode.ai/v2/llms.txt`), so this repository uses the
exported JSON plus a readable Markdown transcript rather than a hosted link.
