# Empty-search continuity fix

Branch: `fix/stop-after-empty-search`

## Symptom

The agent narrates a plan to search, receives an empty result or tool error, then issues a slightly reworded search. Exact duplicate detection does not catch the changed query, so the agent wastes a research round and may imply it has gathered evidence when it has not.

## Changes

### `pyggie/home/agent.py`

- Detects empty JSON result lists from `web_search`.
- Detects `Tool error:` results from research tools.
- Detects the fetcher’s `Could not read this page.` result.
- Once any of those outcomes occurs, further calls to the same research tool are blocked for the current AgentRun, even if the next query is rephrased.
- Keeps the existing maximum of two calls for successful results.
- Explicitly instructs the model not to retry an empty/failed search with a reworded query; it must disclose the limitation and proceed from existing knowledge.

The block happens in the existing research-limit gate before execution. The blocked result is recorded in the transcript, and the existing `research_exhausted` flag prevents further tool use in the current run.

### `pyggie/home/test_agent_research_guard.py`

Covers empty search results, search errors, unreadable pages, successful search allowance, the existing two-successful-search cap, and unrelated tools.

## Validation

Run from `pyggie/`:

```bash
python manage.py test home.test_agent_research_guard
python manage.py test home
python manage.py check
```

No local Django runtime was available during remote editing, so these tests have been added but not executed here.

## Parallel-agent handoff

This patch owns `pyggie/home/agent.py` and adds `pyggie/home/test_agent_research_guard.py` plus this document. It is independent of the persistent-state continuity PR, but both touch the agent research/tool-processing path. Rebase onto current main before merging if other agent work lands first.
