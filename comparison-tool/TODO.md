# TODO

- [ ] **Incremental writes**: Write `evaluation.json` and `report.md` after each layer/attempt completes, not just at the end. If the run crashes mid-way, partial results are still available.

- [ ] **Extend existing run**: Add `--extend-run previous/evaluation.json` flag to `migeval evaluate`. Loads previous run, reuses `before` and existing attempt results, only runs layers on new `--attempt`(s), then recomputes all comparisons. Warn if target config hash differs between runs.

- [ ] **DOM snapshots via Playwright MCP**: Use `browser_snapshot` (accessibility tree) on each route for both before and attempt. Diff the snapshots to find structural regressions — missing elements, changed hierarchy, lost interactive controls. Store snapshots in Jest `.snap`-style format for human-readable diffs.

- [ ] **Deeper Playwright MCP usage**: Go beyond screenshots + console errors. Use `browser_click`, `browser_fill` to test interactive flows (login, form submission, dropdowns). Use `browser_evaluate` to inspect component state and run assertions in-page. The runtime agent prompt should be told about all available MCP tools and instructed to exercise basic interactions per route.
