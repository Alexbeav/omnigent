# Primary platform image attachments

This note records the attachment flow at base `e88754218`. It also records the
fix for pictures whose browser `File.type` is empty or
`application/octet-stream`.

## Finding and root cause

The web composers already use one attachment state hook. They accept files from
the **Files and images** menu, a paste into the text area, or a file drop on the
chat surface. The landing composer and the in-session composer both upload each
accepted file to `/v1/sessions/{id}/resources/files`. They then send the returned
file ID in an `input_image` or `input_file` content block.

The client classified pictures only from `File.type`. Some browser and OS file
providers return an empty or generic MIME type for a `.png` or `.jpg` file. The
client rejected those files before upload. If a picture bypassed validation, the
send path labeled it as `input_file`, so the model did not receive it through
the image path. The server already resolves a missing or generic type from the
filename, so the client and server disagreed.

The fix makes the shared client classifier use `.png`, `.jpg`, `.jpeg`,
`.webp`, and `.gif` when the MIME type is missing or generic. The send path now
uses that same classifier to choose `input_image`. A specific conflicting MIME,
such as `video/mp4` on `clip.png`, still fails client validation and then server
validation if a caller bypasses the client.
An explicit non-compressible image MIME also keeps the 5 MB size limit.
A misleading raster filename does not raise that limit.

## Entry points

The following paths share `useComposerAttachments` and
`validateAttachments`:

- The in-session **Add > Files and images** control.
- The new-session **Add > Files and images** control.
- Clipboard file items pasted into either composer.
- Operating-system files dropped on the in-session transcript or landing
  surface.

The browser uploads files only when the user sends the message. The message
keeps a `File` object until that point. Failed uploads restore or retain the
draft through the existing send flow.

## Harness delivery matrix

| Path | Image delivery | Evidence | Limit |
| --- | --- | --- | --- |
| Native Codex | Supported | The executor materializes the data URI outside the workspace and sends a `localImage` item. The focused test checks the decoded bytes and makes sure that base64 is absent from text. | No live Codex CLI turn was run in this task. |
| Native Claude | Supported | The executor materializes the data URI and injects an `[Attached: <absolute path>]` marker. The focused test checks the file bytes and marker order. | No live Claude CLI turn was run in this task. |
| ACP, including OMP | Capability-dependent | When `initialize.result.agentCapabilities.promptCapabilities.image` is true, the executor sends an ACP `image` block with `mimeType` and base64 `data`. When it is absent or false, the executor sends only an attached-image text marker. | OMP itself was not installed or started, so its current capability advertisement is unproven. An OMP build that does not advertise ACP image support cannot inspect the image through this path. |
| Server and model adapter | Supported for the isolated mock path | The upload route accepted supported image MIME types. `test_image_upload_reaches_llm` proved that uploaded image bytes reached the mock multimodal model. | This does not prove every remote provider and model accepts every image format. |

Archives, Office documents, and databases are separate filesystem attachments.
Only filesystem-capable native Claude and Codex sessions accept them. This patch
does not change that rule.

## Automated evidence

Run the web checks from the repository root:

```sh
pnpm --dir web exec vitest run src/lib/attachments.test.ts src/store/chatStore.test.ts
pnpm --dir web exec vitest run src/hooks/useComposerAttachments.test.tsx \
  src/hooks/useFileDropTarget.test.tsx src/shell/NewChatDialog.test.tsx \
  -t 'ComposerAddMenu|paste|drop|MIME|attachment'
```

The first command passed 599 tests. It includes the new checks for a MIME-less
PNG and its `input_image` message block. The second command passed 46 focused
tests and skipped 551 unrelated tests. It covers the add-menu callback, paste,
drop, and shared attachment state.

Run the backend and harness checks with the prepared development environment:

```sh
PYTHONPATH=$PWD /home/alexbeav/Projects/omnigent-primary/.venv/bin/python -m pytest \
  tests/server/routes/test_sessions_upload_limits.py::test_upload_supported_types \
  tests/e2e/test_image_upload_e2e.py::test_image_upload_reaches_llm -q

PYTHONPATH=$PWD /home/alexbeav/Projects/omnigent-primary/.venv/bin/python -m pytest \
  tests/inner/test_codex_native_executor.py::test_image_block_is_sent_as_local_image_not_inline_base64 \
  tests/inner/test_claude_native_executor.py::test_run_turn_materializes_image_to_bridge_dir \
  tests/inner/test_qwen_executor.py::test_image_blocks_from_content_builds_acp_image_block \
  tests/inner/test_qwen_executor.py::test_ensure_initialized_captures_image_capability \
  tests/inner/test_goose_executor.py::test_run_turn_forwards_image_block_when_supported -q
```

The backend command passed seven parameterized checks with one Starlette
deprecation warning. The harness command passed five checks.

## Human verification

Do not use the live server at `http://172.16.1.8:8090` for this check. Start an
isolated instance as described in `feature-map/skills/verify-omnigent/SKILL.md`.

1. Open the landing page and select a native Codex agent.
2. Select **Add > Files and images**, choose a PNG, and make sure that its image
   chip appears.
3. Remove it, paste a screenshot, and make sure that a new image chip appears.
4. Remove it, drop a PNG on the landing surface, and make sure that the chip
   appears.
5. Send the image with the text `Describe the dominant color in this image.`
6. Make sure that the user bubble shows the image and the answer describes it.
7. Repeat steps 1 through 6 for native Claude and for an existing in-session
   composer.
8. For OMP, inspect its ACP initialize frame first. Continue only if it reports
   `agentCapabilities.promptCapabilities.image: true`. If it reports false or
   omits the field, record the path as unsupported instead of claiming image
   delivery.

For the regression, use a browser fixture or file provider that gives the PNG
an empty MIME type. Make sure that the chip appears and the outgoing event uses
`type: "input_image"`.

## Integrated browser evidence

After integration, the parent ran 16 isolated browser checks:

```sh
python -m pytest tests/e2e_ui/chat/test_composer_attachments.py \
  tests/e2e_ui/chat/test_image_attachment_mime.py \
  tests/e2e_ui/start_session/test_image_only_first_message_send.py --ui-skip-build
```

The shared verification environment ran a private server, runner, and mock model.
Picker, paste, and drop each accepted a PNG with an empty or generic browser MIME type.
Each regression case uploaded the image and emitted an `input_image` block with its file ID.
The suite also covered image-only sends, rejected files, and failed-upload draft recovery.
The browser evidence is under `.omnigent/verify/resume/image-evidence/`.

Secondary pane composers reuse the same attachment hook for validation and paste.
They also support drop inside their own composer and recover failed sends.
Component tests cover those paths and preserve edited drafts after a late acknowledgement.
Native Codex and Claude adapter tests and the mock-model image upload test passed three checks after integration.

## Remaining gaps

No native Codex, native Claude, or OMP process received a live image in this work.
The adapter tests establish request construction, not behavior of every installed CLI and model.
The browser regression does not prove the exact cause of Alex's original missing attachment control.
The existing control is reached through **Add > Files and images**.
A screenshot of any remaining interface failure will narrow that separate symptom.
