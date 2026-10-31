# Conservative graph-generation policy

## Purpose

Prevent Pyggie from producing graphs merely because a conversation contains equations, functions, or numerical methods. Graphs should add insight, not decorate an otherwise complete answer.

## Expected model behavior

- Default to a direct explanation using prose and equations.
- Plot when the user explicitly requests a graph/plot/visualization, or when the visual itself is essential to understanding something prose, equations, or a small table cannot communicate clearly.
- Before plotting, identify the concrete insight the image will add. If there is no clear answer, do not plot.
- A request to solve, derive, calculate, apply a method, or explain an equation is not by itself a request for a graph.
- Avoid duplicate or near-duplicate plots. In particular, do not plot an exact solution and a numerical approximation side-by-side unless the user asks for a visual comparison or it is central to the question.
- When unsure, answer without a graph. When a graph is requested, create only the minimum number needed.

## Implementation

- `pyggie/home/plots.py`: tool descriptions and shared `PLOT_PROMPT` are the source of graphing policy.
- `pyggie/home/ollama.py`: includes the shared prompt in normal chat and exposes plot tools to tool-capable models.
- `pyggie/home/agent.py`: includes the same shared prompt in Agent Mode and exposes the same plot tools.
- `pyggie/home/tests.py`: checks that the conservative policy remains present.

Keep this policy shared between normal chat and Agent Mode. Do not add a more permissive mode-specific instruction that overrides it.

## Validation

From the `pyggie` directory:

```bash
python manage.py test home
python manage.py check
```
