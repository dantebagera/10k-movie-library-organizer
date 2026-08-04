# Desktop Sidebar Cosmetic Refinement: Trakt-Inspired Zero-Regression Plan

- **Status:** Planning contract only. Implementation has not started under this plan.
- **Last reviewed:** 2026-08-04
- **Repository:** `C:\Users\dante\Desktop\cinema paradiso`
- **Observed branch:** `master`, one local commit ahead of `origin/master`
- **Target:** Cinema Paradiso desktop primary sidebar only
- **Primary owners:** `Sidebar` and `navItems` in `src/App.jsx`; sidebar presentation in `src/styles.css`
- **Regression owner:** `tests/e2e/app-smoke.spec.js`
- **Visual reference:** signed-in Trakt desktop sidebar at `https://app.trakt.tv/discover/trending?mode=media`

This plan is the implementation contract. Saving it does not authorize production-code edits, dependency changes, process restarts, Git staging, commits, pushes, or work outside the gates below. Dante must explicitly approve implementation after reviewing this plan.

## 1. Goal

Refine Cinema Paradiso's desktop sidebar so it:

1. occupies materially less horizontal space;
2. visually blends into the page instead of reading as a bordered panel;
3. uses Trakt's quick, controlled motion language;
4. provides a styled floating label when a collapsed navigation icon is hovered or keyboard-focused;
5. preserves CP's gold identity, navigation ownership, accessibility, persistence, and workspace behavior;
6. changes no route, feature ownership, mobile behavior, or non-sidebar surface.

The product principle is:

> Borrow Trakt's density, motion, and collapsed-hover clarity while preserving Cinema Paradiso's authoritative navigation model and visual identity.

## 2. Confirmed planning baseline

These facts were measured during planning and must be rechecked before implementation.

### 2.1 Trakt desktop reference

The signed-in Trakt sidebar was inspected at a 1440 by 900 desktop viewport.

| Property | Measured Trakt behavior |
| --- | --- |
| Collapsed navigation width | `48px` |
| Expanded navigation width | `180px` |
| Expanded content reserve | `196px` left padding |
| Collapsed content reserve | `64px` left padding |
| Layout motion | content padding transitions for `150ms ease-in-out` |
| Link/icon motion | color and icon-state opacity transition for `150ms ease-in-out` |
| Primary icon size | approximately `24px` |
| Expanded primary row content | icon plus 16px regular label; no row panel |
| Expanded secondary links | indented text links, approximately 19.3px line box with 6px vertical gap |
| Active state | accent-colored text/icon without a row background or outline |

The collapsed hover action is a custom floating label rather than a browser-native `title` tooltip. The measured `Discover` label used:

- a dark neutral surface;
- no border;
- `4px` corner radius;
- `5px 6px` padding;
- `12px` text at weight `500`;
- a soft `0 4px 20px` shadow;
- a left edge approximately `4px` beyond the collapsed rail;
- a high stacking level so it appears over page content.

The tooltip itself is inserted for the hover interaction. Trakt's surrounding icon, color, opacity, and layout motion consistently uses `150ms ease-in-out`.

### 2.2 Cinema Paradiso desktop baseline

The current CP sidebar is owned by the existing `Sidebar` function in `src/App.jsx`. It receives `activeSection`, `collapsed`, `onSelect`, and `onToggleCollapsed`; it renders the authoritative `navItems` list.

Current geometry and behavior:

| Property | Current CP behavior |
| --- | --- |
| Expanded width token | `280px` |
| Collapsed width token | `84px` |
| Collapsed live width at 1440 by 900 | `84px` |
| Collapsed brand block | approximately `112.8px` high |
| Navigation row | approximately `55.2px` high |
| Icon treatment | `34px` dark rounded tile around each icon |
| Active treatment | full-row gradient plus a 2px gold left indicator |
| Sidebar surface | separate dark gradient with a right border |
| Internal seams | brand bottom border, footer top border, bordered toggle |
| Collapse persistence | `localStorage` key `cp.sidebarCollapsed` |
| Shell motion | `200ms` using `--ease-out: cubic-bezier(0.22, 1, 0.36, 1)` |
| Item/toggle motion | mixed `160ms` and `180ms` durations using `--ease-out` |

The current sidebar is not functionally broken. The cosmetic problem is that its width, boxed icons, gradient active rows, multiple divider lines, and separate panel background compete with the movie surfaces and consume more workspace width than necessary.

### 2.3 Existing regression coverage

`tests/e2e/app-smoke.spec.js` already proves:

- expanded and collapsed widths;
- `aria-expanded` state;
- collapsed labels through the current native `title` attribute;
- centered collapsed logo geometry;
- workspace and content expansion after collapse;
- unchanged 24px workspace padding;
- `localStorage` persistence across reload;
- expansion back to the original width;
- state preservation when navigating between sidebar workspaces.

This coverage must be updated, not bypassed or replaced with a parallel test path.

### 2.4 Dirty-worktree protection

Planning-time Git inventory showed:

- branch `master` is one commit ahead of `origin/master`;
- the repository contains substantial unrelated modified and untracked work;
- `src/App.jsx` is modified;
- `src/styles.css` is modified;
- `tests/e2e/app-smoke.spec.js` is modified;
- several files already exist untracked under `docs/plans` and `docs/verification`.

All existing changes belong to the current worktree and must be preserved. Before implementation, capture a path-scoped status and diff for every planned file. Do not reset, discard, rewrite, stage, or commit unrelated changes.

## 3. Non-negotiable product contract

### 3.1 Desktop-only scope

- The change applies only at the existing desktop sidebar breakpoint above `980px`.
- Do not redesign, test, screenshot, or optimize a mobile or responsive navigation variant.
- Existing mobile behavior must remain unchanged unless a shared selector would otherwise break it; in that case, narrow the selector instead of redesigning mobile.

### 3.2 Target geometry

The initial implementation target is:

| Element | Target |
| --- | --- |
| Expanded sidebar | `220px` |
| Collapsed sidebar | `64px` |
| Expanded brand block | no more than `80px` high |
| Collapsed brand block | no more than `96px` high while keeping logo and toggle usable |
| Navigation row | `46px` high |
| Navigation icon | `22px` |
| Expanded label | `15px`, weight `600` |
| Footer | approximately `48px` high |

At 1920px viewport width, collapse should return approximately `156px` of additional width to the workspace while retaining the existing 24px workspace padding.

If rendered geometry proves that the collapsed logo and toggle cannot remain clear and comfortably clickable within the 96px brand limit, stop and present measured alternatives instead of hiding or combining controls without approval.

### 3.3 Borderless page blend

The sidebar must read as part of the app canvas, not a card or separate panel.

Remove the following persistent decoration from the desktop sidebar:

- sidebar right border;
- sidebar-specific dark gradient that visually separates it from the shell;
- brand bottom border;
- footer top border;
- toggle border;
- icon-tile backgrounds;
- active-row gradient;
- active-row left indicator;
- any other always-visible navigation outline introduced by this work.

The sidebar should use a transparent background so the authoritative `.app-shell` canvas continues beneath it. Hover and active states must not recreate full boxed rows.

### 3.4 Active and hover behavior

- Inactive items use the existing muted text treatment.
- The active item uses CP gold for its icon and label.
- Expanded inactive items may transition to a brighter/gold treatment on hover, but must not gain a panel, border, translation, or outline.
- Remove the current `translateX(2px)` hover movement; Trakt's sidebar remains geometrically stable.
- Active state remains visually distinct without relying only on a background fill.

### 3.5 Collapsed floating label

Replace the browser-native collapsed `title` tooltip with one authoritative CP tooltip owned by `Sidebar`.

Required behavior:

1. It appears only while the sidebar is collapsed.
2. Mouse hover and keyboard focus both reveal it.
3. It contains the exact navigation label.
4. It appears to the right of the rail with a `4px` visual gap.
5. It is vertically centered on the triggering navigation item.
6. It uses a dark blended surface, no border, `4px` radius, `5px 6px` padding, 12px/500 text, and a soft shadow.
7. It uses a small opacity and horizontal-position reveal governed by the shared sidebar motion token.
8. It does not intercept pointer events.
9. It cannot be clipped by `.nav-stack` scrolling or sidebar overflow.
10. It clears on mouse leave, blur, navigation, collapse-state expansion, and component unmount.
11. Only one tooltip instance can exist at a time.
12. Expanded navigation does not render or reveal this tooltip.

Keep the collapsed button's `aria-label`; remove its native `title` attribute so duplicate native and custom labels cannot appear together.

Implementation should prefer one fixed-position tooltip rendered by `Sidebar`, outside the scrollable `.nav-stack`, over one tooltip per item or a new tooltip dependency. If clipping cannot be solved without a portal or broader ownership change, stop and report the evidence before expanding scope.

### 3.6 Motion contract

Create one sidebar-specific motion contract:

```css
--sidebar-motion-duration: 150ms;
--sidebar-motion-easing: ease-in-out;
```

Apply it consistently to:

- shell column expansion/collapse;
- brand text visibility;
- navigation label visibility;
- icon and text color;
- toggle feedback;
- tooltip reveal/hide;
- footer text visibility.

Do not use `transition: all`. Name the properties that actually animate.

Honor `prefers-reduced-motion: reduce` by removing sidebar transitions while preserving the final visible states and all interaction behavior.

### 3.7 Keyboard focus contract

The request to remove sidebar outlines applies to persistent decorative borders and seams. It does not remove keyboard accessibility.

- Retain a restrained CP-gold `:focus-visible` ring.
- The ring appears only for keyboard-style focus, not as a permanent row outline.
- It must remain visible against the borderless canvas in expanded and collapsed modes.
- The collapsed tooltip must also appear for focused navigation buttons.

### 3.8 Preserved behavior

The implementation must preserve:

- current navigation order and labels;
- the authoritative `navItems` array;
- `activeSection` and `onSelect` behavior;
- `cp.sidebarCollapsed` persistence;
- `aria-label`, `aria-expanded`, and button semantics;
- the CP mark and Cinema Paradiso wordmark in expanded mode;
- local-first status and application version;
- workspace padding and content-width expansion;
- state preservation across sidebar navigation;
- the existing desktop breakpoint;
- all non-sidebar page styling.

## 4. Authoritative ownership

### `src/App.jsx`

`Sidebar` remains the only owner of:

- primary navigation rendering;
- collapse/expand control rendering;
- active-item selection;
- collapsed tooltip interaction state and anchor measurement.

Do not introduce a route-specific sidebar, duplicate navigation array, second collapse state, or general tooltip framework.

### `src/styles.css`

The existing sidebar rules remain the only owner of:

- width tokens;
- brand geometry;
- navigation geometry;
- icon, label, active, hover, and focus presentation;
- footer presentation;
- collapsed presentation;
- desktop motion and reduced-motion behavior;
- floating tooltip presentation.

Do not add route-local overrides to individual workspaces.

### `tests/e2e/app-smoke.spec.js`

The existing desktop sidebar test remains the principal regression path. Extend it in place rather than creating a second competing sidebar suite unless the resulting test becomes unreasonably large.

## 5. Gated implementation plan

### Gate 0 - Reconfirm and protect the current state

Before editing production code:

1. Record `git status -sb` using a command-local safe-directory override only.
2. Record path-scoped diffs for:
   - `src/App.jsx`;
   - `src/styles.css`;
   - `tests/e2e/app-smoke.spec.js`.
3. Reconfirm the current `Sidebar` owner and CSS selectors.
4. Reconfirm the live expanded/collapsed widths and current served asset.
5. Run or inspect the existing focused desktop sidebar regression to establish the baseline.
6. Stop if current edits overlap the exact sidebar/test hunks in a way that cannot be safely preserved.

### Gate 1 - Add the single tooltip interaction owner

In the existing `Sidebar` function:

1. Add one local tooltip state containing only the current label and measured vertical anchor.
2. Add small show/hide handlers shared by hover and focus.
3. Render one fixed-position tooltip outside `.nav-stack`.
4. Retain `aria-label` for collapsed buttons.
5. Remove the collapsed native `title` attribute from navigation items.
6. Clear tooltip state for every exit condition in section 3.5.
7. Do not change navigation routing or introduce a dependency.

### Gate 2 - Refine the existing sidebar CSS owner

Update the existing sidebar rules rather than layering a second theme:

1. Set the 220px and 64px width tokens.
2. Compact brand, row, icon, label, toggle, and footer geometry.
3. Make the sidebar transparent and remove the listed seams.
4. Remove icon tiles, active gradient, active indicator, and hover translation.
5. Apply gold active state and restrained expanded hover feedback.
6. Add the collapsed tooltip surface and reveal motion.
7. Standardize all sidebar motion on 150ms `ease-in-out`.
8. Add the reduced-motion override.
9. Preserve the existing desktop breakpoint and leave mobile selectors unchanged.
10. Remove obsolete sidebar declarations once their replacement is verified.

### Gate 3 - Expand automated regression coverage

Update the existing desktop sidebar test to prove:

1. expanded width is `220px`;
2. collapsed width is `64px`;
3. the workspace receives approximately 156px after collapse;
4. workspace padding remains `24px` on both sides;
5. collapse persistence survives reload;
6. the collapsed CP mark remains centered within 0.5px;
7. no collapsed navigation button has a native `title` attribute;
8. hovering a collapsed item reveals exactly one custom tooltip with the correct label;
9. moving away removes the tooltip;
10. keyboard focus reveals the same tooltip;
11. blur removes it;
12. expanding the sidebar removes it and prevents it from appearing on expanded item hover;
13. tooltip geometry begins at least 4px beyond the sidebar edge and remains inside the viewport;
14. sidebar, brand, and footer borders compute to zero;
15. icon tiles and active rows have transparent backgrounds;
16. the active item is identifiable by CP gold text/icon color;
17. sidebar transition duration and timing compute to `0.15s` and `ease-in-out` in normal motion mode;
18. reduced-motion mode removes transitions without hiding labels or controls;
19. existing state-preservation navigation coverage still passes.

Do not weaken unrelated assertions merely to make the new geometry pass.

### Gate 4 - Build and rendered desktop acceptance

After the approved code and tests are complete:

1. Run the focused sidebar Playwright case through the isolated CP runner.
2. Run the complete `app-smoke.spec.js` suite if focused verification passes.
3. Run the normal production Vite build.
4. Verify the normally served asset, not only the isolated test build.
5. Inspect the rendered desktop sidebar at 1920 by 1000 in expanded and collapsed states.
6. Verify tooltip hover and keyboard focus visually.
7. Verify Home, Library, Discover, IPTV, Downloads, Help, and Settings navigation still work.
8. Verify no console errors, clipping, horizontal overflow, or workspace jump.
9. Reset temporary browser viewport overrides and collapse state after verification.

No application process may be restarted without explicit approval. If the running Flask process serves a stale bundle and a restart is required for live verification, stop and ask.

## 6. Verification commands

### Focused desktop sidebar Playwright

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools\run_playwright_e2e.ps1 app-smoke.spec.js -g "desktop sidebar"
```

The runner creates a unique isolated `CP_TEST_ROOT`, builds an isolated frontend, and owns its temporary process lifecycle.

### Complete app smoke suite

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools\run_playwright_e2e.ps1 app-smoke.spec.js
```

### Normal production build

```powershell
npm.cmd run build
```

## 7. Expected file scope

Expected production and regression files:

- `src/App.jsx`
- `src/styles.css`
- `tests/e2e/app-smoke.spec.js`

Planning artifact:

- `docs/plans/desktop-sidebar-trakt-inspired-cosmetic-zero-regression-plan.md`

Any additional production file requires a written reason and renewed approval if it materially expands ownership.

## 8. Acceptance matrix

| Scenario | Required result |
| --- | --- |
| Desktop, expanded | 220px borderless sidebar; labels visible; no custom tooltip |
| Desktop, collapsed | 64px borderless rail; icons centered; labels hidden |
| Active item | Gold icon and label; no row panel, outline, gradient, or side bar |
| Expanded hover | Stable geometry; subtle color response only |
| Collapsed hover | One compact floating label appears to the right |
| Collapsed keyboard focus | Same floating label plus a restrained focus-visible ring |
| Mouse leave or blur | Floating label disappears |
| Expand while tooltip is open | Tooltip clears immediately |
| Reload while collapsed | Collapsed state persists |
| Reduced motion | Same final states without transition animation |
| Low desktop height | Navigation remains reachable without tooltip clipping |
| Workspace layout | 24px padding retained; additional width returned to content |
| Mobile or <=980px | Existing behavior unchanged |

## 9. Risks and mitigations

### Risk: tooltip is clipped by the scrollable navigation

Mitigation: render one fixed-position tooltip as a sibling outside `.nav-stack`; do not place a tooltip inside every scrolling item.

### Risk: dirty sidebar files are overwritten

Mitigation: capture path-scoped diffs at Gate 0, edit only the authoritative hunks, and review the final diff against the pre-edit snapshot.

### Risk: compact geometry makes controls hard to use

Mitigation: retain 46px navigation rows and verify real bounding boxes. Do not shrink controls merely to match Trakt's exact 48px rail.

### Risk: removing borders makes state ambiguous

Mitigation: use clear gold active color and retain a visible keyboard focus ring without recreating persistent panels.

### Risk: animation feels inconsistent

Mitigation: use one 150ms `ease-in-out` token and explicit transition properties across every sidebar-owned motion path.

### Risk: reduced-motion users receive hidden or stale labels

Mitigation: reduced motion removes only transitions, not visibility-state changes or interaction handlers.

### Risk: low-height desktop clips the last navigation items

Mitigation: preserve vertical scrolling in `.nav-stack` and test a low-height desktop viewport while keeping the tooltip outside that overflow owner.

### Risk: isolated tests pass while the user sees the old bundle

Mitigation: run the normal build, confirm the asset served by port 5000, and perform rendered desktop acceptance against that asset before completion.

### Risk: Trakt inspiration becomes copied architecture

Mitigation: copy no Trakt code or assets and add no nested route model. Adopt only measured presentation principles through CP's existing owners.

## 10. Explicit non-goals

This plan does not authorize:

- mobile or bottom-dock navigation work;
- nested Home, Discover, or Lists route trees;
- navigation reordering, renaming, or new destinations;
- a user avatar or account menu;
- changes to page cards, headers, workspaces, or content margins outside the sidebar contract;
- a new tooltip library or general tooltip system;
- copying Trakt source code, icons, assets, or purple brand color;
- backend, database, metadata, playback, IPTV, or acquisition changes;
- process restarts, commits, pushes, releases, or deployment.

## 11. Stop conditions

Stop, summarize the evidence, and ask Dante before proceeding if:

1. current uncommitted changes overlap the same sidebar hunks and cannot be safely preserved;
2. the tooltip requires a new dependency, application-wide portal owner, or route-level changes;
3. compact geometry cannot keep the CP mark and collapse control clear and usable;
4. any mobile or non-sidebar selector must be materially redesigned;
5. workspace padding, state preservation, or existing navigation breaks;
6. the tooltip clips under realistic desktop scrolling and cannot be fixed inside `Sidebar` ownership;
7. the normally served bundle is stale and requires an unapproved process restart;
8. unrelated tests fail and the cause is not clearly pre-existing;
9. the required file scope expands materially.

## 12. Completion definition

This task is complete only when:

- the implementation matches every approved geometry, blend, motion, hover, tooltip, focus, and preservation contract;
- the existing authoritative owners remain clear;
- obsolete sidebar styling is removed rather than left as a competing path;
- focused and complete sidebar-relevant automated coverage passes;
- the normal production build passes;
- the normally served desktop bundle is confirmed;
- expanded, collapsed, hover, focus, persistence, low-height, and workspace geometry are visually verified;
- no console errors or unintended horizontal overflow appear;
- the final path-scoped diff contains no unrelated changes;
- no commit, push, restart, or release occurs without separate approval.

## 13. Approval gate

The plan is now saved for review. Implementation must not begin until Dante explicitly approves this plan with a clear instruction such as `go`, `implement it`, `proceed`, or `fix it`.
