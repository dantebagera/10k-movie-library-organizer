# Gate 5 verification — passed

## Outcome

`src/api/catalogEvents.js` owns one app-level EventSource. The Library responds to a newer committed generation with one bounded authoritative SQL page refetch. Its background path does not set foreground loading, unmount the grid, create a card from event data, or navigate/reload the page.

Stable keys preserve unaffected card nodes. Query/generation guards discard stale responses. Existing filters, sorting, page, search, scroll, focus, selection, and expanded-card state remain owned by the mounted workspace.

## Desktop proof

The full desktop suite passed 49/49 at 1600x1000. The new test holds the background response open and asserts that the exact grid DOM node remains mounted, no spinner appears, the selected/expanded card stays selected/expanded, search retains focus, and the final card appears only after the response is released.

Evidence:

- `after/library-background-refresh-during.png`
- `after/library-background-refresh-complete.png`
- `after/playwright-artifacts/app-smoke-committed-catalo-cf96b--unmounting-or-losing-state/video.webm`

The screenshots and video were captured from a fresh isolated production build. No mobile/responsive work was performed.
