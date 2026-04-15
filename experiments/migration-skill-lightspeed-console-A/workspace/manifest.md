# UI Manifest

Project: ./lightspeed-console

## Notes

This is an OpenShift Console **dynamic plugin**, not a standalone SPA. It has no internal router — it injects a floating popover chat window onto any OpenShift Console page. The plugin is loaded at runtime by the OpenShift web console and renders as an overlay. All "routes" below are effectively states of the single Popover component and its children.

Authentication required: YES (OpenShift Console login + OLS backend auth)
Credentials found: NO (requires a running OpenShift cluster with `oc login`)

---

## Routes

### Popover closed (button only) → popover-closed.png
- **Navigate to**: any console page with the plugin loaded
- **Wait for**: the Lightspeed popover button to appear in the bottom-right corner
- **Key elements**: floating popover button with Lightspeed icon, tooltip on hover ("Red Hat OpenShift Lightspeed")
- **Notes**: this is the default idle state; requires `console.hideLightspeedButton` user setting to be falsy

### Popover open — welcome page (collapsed) → popover-welcome.png
- **Navigate to**: any console page
- **Trigger**: click the Lightspeed popover button (data-test `ols-plugin__popover-button`)
- **Wait for**: popover panel to appear with welcome content
- **Key elements**: Lightspeed logo, "Red Hat OpenShift Lightspeed" title, welcome subheading, privacy alert, prompt input area with attach button and send button, footer text, expand/minimize buttons
- **Notes**: shown when chat history is empty; popover is in collapsed (default) size

### Popover open — welcome page (expanded) → popover-welcome--expanded.png
- **Navigate to**: any console page, open popover
- **Trigger**: click the expand button (data-test `ols-plugin__popover-expand-button`)
- **Wait for**: popover to expand to full size
- **Key elements**: same as welcome page but in expanded layout; collapse button replaces expand button
- **Notes**: CSS class `ols-plugin__popover--expanded`

### Popover open — welcome page (first-time user) → popover-welcome--first-time.png
- **Navigate to**: any console page (as a first-time user)
- **Wait for**: popover auto-opens after 500ms delay
- **Key elements**: all welcome page elements plus WelcomeNotice alert ("Welcome to OpenShift Lightspeed!")
- **Notes**: requires `useFirstTimeUser` to return true; auto-opens chat for first-time users

### Popover open — chat conversation → popover-chat.png
- **Navigate to**: any console page, open popover
- **Setup**: submit a prompt (type text in the prompt input, press Enter or click send)
- **Wait for**: AI response to finish streaming (spinner disappears, text fully rendered)
- **Key elements**: header with title + clear/copy/expand/minimize buttons, user chat entry ("You:"), AI chat entry ("OpenShift Lightspeed:") with Markdown-rendered response, feedback thumbs up/down + copy buttons, privacy alert, prompt input area
- **Notes**: requires a running OLS backend to get a real response

### Popover open — streaming response → popover-streaming.png
- **Navigate to**: any console page, open popover
- **Trigger**: submit a prompt
- **Wait for**: streaming to begin (spinner visible, partial text appearing)
- **Key elements**: "Waiting for LLM provider..." helper text with spinner (before tokens arrive), partially rendered AI response text, stop button (StopIcon) replacing send button (PaperPlaneIcon) in prompt area
- **Notes**: transient state; capture immediately after submitting prompt

---

## Interactive Components

### Modal: New Chat Confirmation → modal-new-chat.png
- **Trigger**: on popover with existing chat history, click the trash/clear chat button (data-test `ols-plugin__clear-chat-button`)
- **Wait for**: modal to appear with confirmation content
- **Key elements**: yellow warning triangle icon, "Confirm chat deletion" title, confirmation message ("Are you sure you want to erase..."), "Erase and start new chat" danger button, "Cancel" link button, close (X) button

### Modal: Attachment Preview (viewer) → modal-attachment-viewer.png
- **Trigger**: click on any attachment label in the chat prompt area or chat history
- **Wait for**: modal to appear with code block content
- **Key elements**: blue info circle icon, "Preview attachment" title, resource icon + name header, CodeBlock with YAML/log content, copy button, "Edit" primary button (if editable), "Dismiss" link button, close (X) button

### Modal: Attachment Preview (editor) → modal-attachment-editor.png
- **Trigger**: in the attachment preview modal, click the "Edit" button
- **Wait for**: CodeEditor (Monaco) to load and render
- **Key elements**: Monaco code editor with syntax highlighting (YAML or plaintext), language label, minimap, resource header, "Save" primary button, "Cancel" link button
- **Notes**: editor supports dark theme via `useIsDarkTheme`

### Modal: Attach Events Configuration → modal-attach-events.png
- **Trigger**: on a workload resource page (e.g., Deployment), open popover, click attach menu (+), select "Events"
- **Wait for**: modal to appear, events to load via WebSocket
- **Key elements**: "Configure events attachment" title, description text, slider for "Most recent N events", CodeBlock with YAML preview, copy button, "Attach" primary button, "Cancel" link button
- **Notes**: requires being on a workload resource page with events available; shows spinner while loading, "No events" if none found

### Modal: Attach Log Configuration → modal-attach-log.png
- **Trigger**: on a workload resource page, open popover, click attach menu (+), select "Logs"
- **Wait for**: modal to appear, pods to load, log preview to render
- **Key elements**: "Configure log attachment" title, description text, Pod selection (radio buttons or dropdown if ≥6 pods), Container selection (radio buttons or dropdown if ≥6 containers), slider for "Most recent N lines", CodeBlock with log preview, "Attach" primary button, "Cancel" link button
- **Notes**: requires being on a workload resource page with running pods

### Modal: Tool Output → modal-tool-output.png
- **Trigger**: in a chat response that used tools, click on a tool label in the response
- **Wait for**: modal to appear with tool output content
- **Key elements**: info/danger icon, "Tool output" title, description of tool name and arguments, DescriptionList with Status (colored label), MCP server name, UI resource URI, "Content" section with CodeBlock, "Structured content" section with formatted JSON CodeBlock, copy buttons, error alert (if status is error)
- **Notes**: requires an AI response that invoked MCP tools

### Modal: Import Confirmation → modal-import-confirm.png
- **Trigger**: in a chat response containing a code block, click the import/plus button on the code block (when NOT on the import YAML page)
- **Wait for**: modal to appear
- **Key elements**: "Do you want to leave this page?" title with warning icon, "Changes you made may not be saved." message, "Leave" primary button, "Stay" link button
- **Notes**: only shown when navigating away from current page to import YAML page; only available on OpenShift ≥4.18

### Dropdown: Attach Context Menu → dropdown-attach-menu.png
- **Trigger**: in the popover prompt area, click the attach/plus circle button (AttachMenu)
- **Wait for**: dropdown select menu to open
- **Key elements**: "Currently viewing" heading with resource label (kind icon + name), "Attach" heading, menu options: "Full YAML file", "Filtered YAML" (with info tooltip), "Events" (disabled if no events), "Logs", "Upload from computer"; context varies by current page resource type
- **Notes**: menu options differ based on resource kind — Alert pages show "Alert", ManagedCluster pages show "Attach cluster info", non-resource pages show only "Upload from computer"

### Feedback: Thumbs Up/Down Expanded → feedback-expanded.png
- **Trigger**: on an AI response entry, click the thumbs-up or thumbs-down icon
- **Wait for**: feedback form to expand below the response
- **Key elements**: filled thumbs-up or thumbs-down icon (selected state), "Why did you choose this rating?" title with close (X) button, "Optional" outline label, text area for additional feedback, privacy disclaimer helper text, "Submit" primary button
- **Notes**: requires `isUserFeedbackEnabled` to be true (controlled by OLS backend `/v1/feedback/status`)

### MCP App Card (normal) → mcp-app-card.png
- **Trigger**: AI response uses an MCP tool that has a `uiResourceUri`
- **Wait for**: card to load MCP app HTML content in sandboxed iframe
- **Key elements**: Card with header title "Interactive view from {toolName}", refresh button (SyncAltIcon), expand/collapse button, minimize button (MinusIcon), iframe with MCP app content
- **Notes**: requires MCP server integration; iframe communicates via postMessage JSON-RPC

### MCP App Card (minimized) → mcp-app-card--minimized.png
- **Trigger**: on an MCP app card, click the minimize button
- **Wait for**: card to collapse to header-only view
- **Key elements**: compact card with title "Interactive view from {toolName}", restore button (WindowRestoreIcon)

---

## Theme/Layout Variants

### Popover open — welcome page (dark theme) → popover-welcome--dark.png
- **Navigate to**: any console page, open popover
- **Setup**: set OpenShift Console theme to dark via user settings (`console.theme` = `dark`) or system preference `prefers-color-scheme: dark`
- **Wait for**: popover to render with dark theme styles
- **Key elements**: same as popover-welcome.png but with dark theme PatternFly tokens applied; Monaco editor in attachment modals will also use dark theme
- **Notes**: theme detected via `useIsDarkTheme` hook which reads `useUserSettings('console.theme')`; no manual toggle button in the plugin itself — theme is inherited from OpenShift Console settings

### Popover open — chat conversation (expanded) → popover-chat--expanded.png
- **Navigate to**: any console page, open popover with chat history
- **Trigger**: click expand button (data-test `ols-plugin__popover-expand-button`)
- **Wait for**: popover to expand
- **Key elements**: same as popover-chat.png but in expanded layout with collapse button; header shows clear/copy/collapse/minimize buttons
- **Notes**: CSS class `ols-plugin__popover--expanded`; expanded is the layout variant for the plugin

---

## Auth/Error States

### Auth error — Not Authenticated → popover-auth-not-authenticated.png
- **Navigate to**: open popover when auth check fails (AuthStatus.NotAuthenticated)
- **Wait for**: alert to render
- **Key elements**: danger alert "Not authenticated" with message about contacting system administrator, prompt area is hidden
- **Notes**: requires simulating auth failure

### Auth error — Not Authorized → popover-auth-not-authorized.png
- **Navigate to**: open popover when auth check returns not authorized (AuthStatus.NotAuthorized)
- **Wait for**: alert to render
- **Key elements**: danger alert "Not authorized" with insufficient permissions message, prompt area is hidden
- **Notes**: requires simulating authorization failure

### Readiness alert → popover-readiness-alert.png
- **Navigate to**: open popover when OLS backend `/readiness` endpoint returns not ready
- **Wait for**: warning alert to appear
- **Key elements**: warning alert "Waiting for OpenShift Lightspeed service" with inline spinner, message about checking OLSConfig
- **Notes**: transient state; polls every 10 seconds until ready
