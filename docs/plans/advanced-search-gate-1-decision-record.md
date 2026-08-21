# Advanced Search Gate 1 Decision Record

Approved by Dante on 2026-08-16 for the isolated implementation worktree.

- Different criterion types use AND. Repeatable values use an explicit group-level AND or OR and default to OR.
- Identical controlled identity and role values normalize to one value. The same person in different roles remains distinct; AND requires both roles and OR accepts either role.
- Discover title searches remain bounded by TMDB `/search/movie` result pages and use the label `TMDB title matches; filters applied to this page`.
- The first release exposes Actor, Director, and Writer. Producer and Any Credit are deferred because the Library catalogue does not store complete generic crew credits.
- Library Minimum Votes is deferred because stored vote counts are incomplete. Active numeric filters exclude movies whose required fact is unknown; unknown is never treated as zero.
- Discover availability, viewing status, and Cinema Paradiso list criteria are local refinements of the loaded TMDB page. Their summary is `X matches on this TMDB page`; no provider-global filtered total is claimed.
- Repair-frozen limits are 24 total values, 10 per repeatable group, 100 title characters, 100 results per logical page, 20 autocomplete suggestions, and a 300 ms query debounce.
- The current simple criteria import once on first Advanced entry after reset. Library and Discover own independent Advanced drafts. Leaving Advanced restores the selected simple mode without applying hidden Advanced criteria. Reset returns Library to Latest additions and Discover to Trending Week.
- Implementation and isolated test serving are authorized in the delegated worktree. The running port-5000 Desktop process remains untouched until separately approved.
