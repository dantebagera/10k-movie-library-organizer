# Cinema Paradiso Ideas

This folder records possible future work before it becomes an approved implementation plan.
An idea is not part of the current product contract and should not be implemented merely
because it is documented here.

## Statuses

- `Idea`: captured but not evaluated.
- `Researching`: evidence or product decisions are still being gathered.
- `Approved`: accepted in principle and ready for a separate implementation plan.
- `Deferred`: intentionally postponed until its revisit conditions are met.
- `Rejected`: considered and declined, with the reason preserved.
- `Implemented`: delivered; the document should link to the resulting behavior or history.

## Index

| Idea | Status | Summary | Revisit condition |
| --- | --- | --- | --- |
| [CP Watch: Where to Watch and web services](cpwatch.md) | Approved | Combine lazy regional availability on shared movie cards with an unlimited configurable services workspace and secure provider navigation through WebView2. | Complete the Stage 0 mockup and provider-compatibility gates in the implementation plan before production coding. |
| [Managed Ollama runtime](managed-ollama-runtime.md) | Deferred | Let CP supervise a private Ollama runtime as part of a future media-appliance package. | The target mini-PC hardware and distribution model are defined. |

## Workflow

1. Create one Markdown file per idea using [`_template.md`](_template.md).
2. Keep the problem and intended user experience separate from implementation guesses.
3. Add the idea to the index above.
4. When approved for development, create a task-specific implementation plan with acceptance tests.
5. Preserve rejected and implemented ideas so the reasoning is not lost or repeatedly reopened.
