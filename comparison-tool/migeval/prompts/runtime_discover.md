# Runtime Configuration Discovery

Migration: {{migration_description}}

## Project files:
{{project_files}}

## Task
Determine the runtime configuration for this project:
1. What is the dev server command? (e.g., npm start, npm run dev)
2. What port does it run on?
3. What routes/pages should be tested?

Output as YAML:
```yaml
dev_server_cmd: "..."
port: ...
ready_pattern: "..."
startup_timeout: 120
routes:
  - path: /
    name: home
  - path: /login
    name: login
```
