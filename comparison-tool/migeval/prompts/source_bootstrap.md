# Source Pattern Generation

You are helping set up migration evaluation for: {{migration_description}}

## Before-migration code sample:
{{code_sample}}

## Task
Generate a list of regex text patterns that indicate old-framework usage.
Output as YAML matching this schema:
- id: descriptive-kebab-case-id
  pattern: "regex pattern"
  severity: warning|info
  title: "Short description"
  extensions: [.tsx, .ts, ...]
