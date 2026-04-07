# PatternFly v5 to v6 Migration — Domain Knowledge

This document provides key domain knowledge for evaluating PatternFly 5 (PF5) to PatternFly 6 (PF6) migrations.

## Package Version Requirements

All `@patternfly/*` packages must be v6. Key packages:
- `@patternfly/react-core` ^6
- `@patternfly/patternfly` ^6
- `@patternfly/react-icons` ^6
- `@patternfly/react-table` ^6

## Component Renames

| PF5 Name | PF6 Name | Notes |
|---|---|---|
| `TableComposable` | `Table` | The old `Table` (legacy) was removed entirely |
| `TextContent` | `Content` | Simplified content wrapper |
| `TextList` | `Content` with `<ul>`/`<ol>` | Use semantic HTML inside `<Content>` |
| `TextListItem` | `Content` with `<li>` | Use semantic HTML inside `<Content>` |
| `Text` | `Content` with `<p>` | Use semantic HTML inside `<Content>` |
| `Chip` | `Label` | Chip component was merged into Label |
| `ChipGroup` | `LabelGroup` | ChipGroup merged into LabelGroup |
| `EmptyStateHeader` | Removed | Use `titleText` prop on `EmptyState` directly |
| `EmptyStateIcon` | Removed | Use `icon` prop on `EmptyState` directly |

## Prop Changes

- **Spacer values**: `spacerNone`, `spacerSm`, `spacerMd`, `spacerLg`, `spacerXl`, `spacer2xl`, `spacer3xl`, `spacer4xl` replaced by gap-based values: `gap`, `gapSm`, `gapMd`, `gapLg`, etc.
- **Alignment values**: `alignRight` / `alignLeft` replaced by `alignEnd` / `alignStart` (logical properties).
- **EmptyState**: `EmptyStateHeader` and `EmptyStateIcon` subcomponents removed. Use `titleText`, `headingLevel`, and `icon` props directly on `EmptyState`.

## CSS Variable Prefix Changes

- `--pf-v5-*` variables renamed to `--pf-v6-*`
- `pf-v5-` CSS class prefix renamed to `pf-v6-`
- All custom overrides using `--pf-v5-` must be updated

## CSS Token Changes

- Old global tokens like `global_Color_*`, `global_BackgroundColor_*`, `global_active_color_*`, `global_success_color_*`, `global_warning_color_*`, `global_danger_color_*` are replaced by the `t_*` token system in PF6.

## Import Path Changes

- `@patternfly/react-core/deprecated` — components here are on their way out. Importing from this path is allowed temporarily but indicates incomplete migration.
- Components that were previously in `@patternfly/react-core` may have moved. Check the PF6 docs for current locations.
- `@patternfly/react-table` — `TableComposable` no longer exists; use `Table` directly from this package.

## Common Migration Pitfalls

1. **Partial renames**: Component renamed in JSX usage but not in import statements, or vice versa.
2. **Incomplete CSS variable updates**: Some `--pf-v5-` variables updated but others missed, especially in SCSS files or inline styles.
3. **Legacy Table usage**: Using the old `Table` (data-driven) API which no longer exists. Must convert to composable `Table` pattern.
4. **EmptyState restructuring**: Forgetting to remove `EmptyStateHeader`/`EmptyStateIcon` wrapper components after moving their content to props on `EmptyState`.
5. **Mixed dependency versions**: Some `@patternfly/*` packages at v5 and others at v6, causing type conflicts and runtime errors.
6. **Deprecated import reliance**: Heavily using `@patternfly/react-core/deprecated` instead of migrating to the new component equivalents.
7. **Spacer/alignment string literals**: Old spacer and alignment string values used in props that now expect different values.
8. **Icon size changes**: Some icon sizing props changed between v5 and v6.
9. **CSS specificity shifts**: PF6 changed some internal CSS specificity, so custom overrides that worked in PF5 may no longer apply correctly.
