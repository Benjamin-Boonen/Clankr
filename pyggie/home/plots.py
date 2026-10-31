# home/plots.py — graph tools for the model: plot_2d, plot_3d, plot_curve.
#
# The model never draws. It calls a tool with formulas; this module samples them with NumPy
# and builds a Plotly figure (JSON). The figure is stored as an Artifact of kind "plot";
# views.artifact_view serves it as a page that draws it with Plotly.js (zoom / rotate / hover).
#
# SAFETY: formulas are written by the model, so they are NEVER given to eval/exec or sympy's
# parse_expr. They are parsed with `ast` and run by the tiny interpreter `_eval` below, which
# only knows numbers, the variable names of the tool, CONSTS, + - * / ** % and the FUNCS table.
# Anything else (attributes, strings, lambdas, subscripts, comprehensions, other calls) is
# rejected with a message the model can act on. All numbers are float64, so 9**9**9 is just inf.
#
# To add a function: put it in FUNCS (and ARITY if it takes 2 arguments).
# To add a tool: write `def my_tool(args) -> (title, figure_dict, summary_text)`, add its
# schema to TOOLS and the function to NAMES. Agent mode and plain chat pick it up from there.
import ast
import html
import json
import math
import re

import numpy as np

MAX_EXPR_CHARS = 300
MAX_CURVES = 6
N2 = 600          # samples per 2D curve
N3 = 70           # grid points per axis of a surface / contour plot
NCURVE = 800      # samples per parametric curve
BIG = 1e12        # |value| above this counts as undefined (drawn as a gap)
MAX_BOUND = 1e6   # largest allowed |range limit|
PLOTLY_SRC = "https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js"


class PlotError(ValueError):
    """A problem the model can fix by changing its arguments; the message is sent back to it."""


# ─── formulas ───

CONSTS = {"pi": np.float64(math.pi), "e": np.float64(math.e), "tau": np.float64(math.tau)}
FUNCS = {
    "sin": np.sin, "cos": np.cos, "tan": np.tan,
    "asin": np.arcsin, "arcsin": np.arcsin, "acos": np.arccos, "arccos": np.arccos,
    "atan": np.arctan, "arctan": np.arctan, "atan2": np.arctan2, "arctan2": np.arctan2,
    "sinh": np.sinh, "cosh": np.cosh, "tanh": np.tanh,
    "asinh": np.arcsinh, "arcsinh": np.arcsinh, "acosh": np.arccosh, "arccosh": np.arccosh,
    "atanh": np.arctanh, "arctanh": np.arctanh,
    "exp": np.exp, "log": np.log, "ln": np.log, "log10": np.log10, "log2": np.log2,
    "sqrt": np.sqrt, "cbrt": np.cbrt, "abs": np.abs, "sign": np.sign,
    "floor": np.floor, "ceil": np.ceil, "min": np.minimum, "max": np.maximum,
    "step": lambda v: np.heaviside(v, 1.0),          # 0 for v<0, 1 for v>=0
}
ARITY = {"atan2": 2, "arctan2": 2, "min": 2, "max": 2}   # every other function takes 1 argument
_BIN = {ast.Add: np.add, ast.Sub: np.subtract, ast.Mult: np.multiply,
        ast.Div: np.true_divide, ast.Pow: np.power, ast.Mod: np.mod}
_ASCII = str.maketrans({"−": "-", "×": "*", "·": "*", "π": "pi", "τ": "tau"})
_LHS = re.compile(r"^\s*[A-Za-z_]\w*\s*(\([^)]*\))?\s*=(?!=)\s*")     # "y = ", "f(x) = "


def _parse(src):
    """Formula text -> ast expression node (nothing is executed)."""
    src = str(src).strip()
    if not src:
        raise PlotError("empty formula")
    if len(src) > MAX_EXPR_CHARS:
        raise PlotError(f"formula longer than {MAX_EXPR_CHARS} characters")
    src = _LHS.sub("", src.translate(_ASCII)).replace("^", "**")
    try:
        return ast.parse(src, mode="eval").body
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        raise PlotError(f"cannot read the formula '{src}'. Write * for every multiplication "
                        f"(2*x, not 2x) and use only numbers, variables, + - * / ^ and functions "
                        f"like sin(x)") from None


def _eval(node, env):
    """Evaluate a parsed formula. Only the node types below exist; everything else is an error."""
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise PlotError("only numbers are allowed as literals (no text)")
        return np.float64(v)
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        raise PlotError(f"unknown name '{node.id}'. Allowed here: "
                        f"{', '.join(sorted(env))} (functions need brackets, e.g. sin(x))")
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        v = _eval(node.operand, env)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        return _BIN[type(node.op)](_eval(node.left, env), _eval(node.right, env))
    if isinstance(node, ast.Call):
        name = node.func.id if isinstance(node.func, ast.Name) else None
        if name not in FUNCS or node.keywords:
            raise PlotError(f"function '{ast.unparse(node.func)}' is not available. "
                            f"Available: {', '.join(sorted(FUNCS))}")
        if len(node.args) != ARITY.get(name, 1):
            raise PlotError(f"{name}() takes {ARITY.get(name, 1)} argument(s)")
        return FUNCS[name](*[_eval(a, env) for a in node.args])
    raise PlotError(f"'{ast.unparse(node)}' is not allowed (use only numbers, variables, "
                    f"+ - * / ^ and functions such as sin, exp, sqrt)")


def _sample(src, shape, **variables):
    """Evaluate formula `src` on arrays (one per variable). Returns a float array of `shape`."""
    tree = _parse(src)
    env = {**CONSTS, **{k: np.asarray(v, dtype=float) for k, v in variables.items()}}
    try:
        with np.errstate(all="ignore"):
            out = np.asarray(_eval(tree, env), dtype=float)
        return np.broadcast_to(out, shape).copy()
    except PlotError:
        raise
    except (OverflowError, ValueError, TypeError, FloatingPointError, ZeroDivisionError) as e:
        raise PlotError(f"cannot evaluate '{src}': {e}") from None


def _num(v, name):
    """A range limit: a number, or a constant expression such as "2*pi"."""
    if v is None or isinstance(v, bool) or v == "":
        raise PlotError(f"{name} is required")
    if isinstance(v, (int, float)):
        f = float(v)
    elif isinstance(v, str):
        f = float(_sample(v, (), **{}))
    else:
        raise PlotError(f"{name} must be a number")
    if not math.isfinite(f) or abs(f) > MAX_BOUND:
        raise PlotError(f"{name} must be a finite number with absolute value below {MAX_BOUND:g}")
    return f


def _opt(args, name):
    v = args.get(name)
    return None if v is None or v == "" else _num(v, name)


def _range(args, lo, hi):
    a, b = _num(args.get(lo), lo), _num(args.get(hi), hi)
    if a >= b:
        raise PlotError(f"{lo} must be smaller than {hi}")
    return a, b


def _exprs(v):
    if isinstance(v, str):
        v = [s for s in re.split(r"[;\n]", v) if s.strip()]
    if not isinstance(v, (list, tuple)) or not v:
        raise PlotError('exprs must be a list of formulas in x, e.g. ["sin(x)", "x^2/10"]')
    if len(v) > MAX_CURVES:
        raise PlotError(f"at most {MAX_CURVES} curves per plot")
    return [str(s) for s in v]


def _text(args, key, default=""):
    v = args.get(key)
    return str(v).strip()[:200] if v not in (None, "") else default


# ─── numbers → figure data ───

def _undefined(a):
    """Mask of values that cannot be drawn: nan, inf, or absurdly large."""
    with np.errstate(all="ignore"):
        return ~np.isfinite(a) | (np.abs(a) > BIG)


def _clean(a):
    """ndarray -> nested lists for JSON. Undefined values become None (a gap in the plot)."""
    if a.ndim > 1:
        return [_clean(r) for r in a]
    return [None if (v != v or abs(v) > BIG) else float(f"{v:.6g}") for v in a.tolist()]


def _break_poles(y):
    """Cut the line where the function jumps across an asymptote or discontinuity (tan, 1/x),
    so Plotly does not draw a false vertical line through it."""
    y = np.where(_undefined(y), np.nan, y)
    with np.errstate(all="ignore"):
        dy = np.abs(np.diff(y))
        if np.isfinite(dy).sum() < 2:
            return y
        med = np.nanmedian(dy)
        if not med > 0:
            return y
        flip = (np.sign(y[:-1]) * np.sign(y[1:]) < 0) & (dy > 20 * med)
    y[1:][flip] = np.nan
    return y


def _span(label, xs, ys):
    """One line for the model: what the curve does (it cannot see the picture)."""
    bad = int(_undefined(ys).sum())
    ok = np.where(_undefined(ys), np.nan, ys)
    lo, hi = int(np.nanargmin(ok)), int(np.nanargmax(ok))
    s = f"{label}: from {ok[lo]:.4g} (at x={xs[lo]:.4g}) to {ok[hi]:.4g} (at x={xs[hi]:.4g})"
    return s + (f"; undefined at {bad} of {len(ys)} points" if bad else "")


_GRID = "#e6e6e6"
_FONT = {"color": "#222222", "size": 13}
_COLORS = ["#3b6fd4", "#d4553b", "#2f9e6e", "#b07cd8", "#c9a227", "#555555"]


def _layout(title, **extra):
    return {"title": {"text": title}, "paper_bgcolor": "#ffffff", "plot_bgcolor": "#ffffff",
            "font": _FONT, "colorway": _COLORS, "margin": {"l": 55, "r": 20, "t": 50 if title else 20, "b": 50},
            **extra}


def _axis(label, **extra):
    return {"title": {"text": label}, "gridcolor": _GRID, "zerolinecolor": "#999999", **extra}


def _scene(xl, yl, zl, **extra):
    return {"xaxis": _axis(xl), "yaxis": _axis(yl), "zaxis": _axis(zl),
            "camera": {"eye": {"x": 1.6, "y": 1.6, "z": 0.9}}, **extra}


# ─── the tools: each returns (title, figure, summary for the model) ───

def plot_2d(args):
    exprs = _exprs(args.get("exprs", args.get("expr")))
    x0, x1 = _range(args, "x_min", "x_max")
    y0, y1 = _opt(args, "y_min"), _opt(args, "y_max")
    if (y0 is None) != (y1 is None):
        raise PlotError("give both y_min and y_max, or neither")
    if y0 is not None and y0 >= y1:
        raise PlotError("y_min must be smaller than y_max")
    xs = np.linspace(x0, x1, N2)
    traces, notes = [], []
    for src in exprs:
        ys = _break_poles(_sample(src, xs.shape, x=xs))
        if np.isnan(ys).all():
            raise PlotError(f"'{src}' has no finite values for x in [{x0:g}, {x1:g}]")
        traces.append({"type": "scatter", "mode": "lines", "name": src, "connectgaps": False,
                       "x": _clean(xs), "y": _clean(ys)})
        notes.append(_span(src, xs, ys))
    title = _text(args, "title", exprs[0] if len(exprs) == 1 else "")
    yaxis = _axis(_text(args, "y_label", "y"), **({"range": [y0, y1]} if y0 is not None else {}))
    fig = {"data": traces, "layout": _layout(title, xaxis=_axis(_text(args, "x_label", "x")),
                                              yaxis=yaxis, showlegend=len(traces) > 1)}
    return (title or "Plot: " + ", ".join(exprs)), fig, \
        f"Plotted for x in [{x0:g}, {x1:g}]. " + "; ".join(notes) + "."


def plot_3d(args):
    src = _exprs(args.get("expr", args.get("exprs")))
    if len(src) != 1:
        raise PlotError("plot_3d draws one formula z = f(x, y); call it again for another surface")
    src = src[0]
    x0, x1 = _range(args, "x_min", "x_max")
    y0, y1 = _range(args, "y_min", "y_max")
    style = _text(args, "style", "surface").lower()
    if style not in ("surface", "contour"):
        raise PlotError('style must be "surface" or "contour"')
    xs, ys = np.linspace(x0, x1, N3), np.linspace(y0, y1, N3)
    X, Y = np.meshgrid(xs, ys)
    Z = _sample(src, X.shape, x=X, y=Y)
    Z = np.where(_undefined(Z), np.nan, Z)
    if np.isnan(Z).all():
        raise PlotError(f"'{src}' has no finite values on this region")
    zlabel = _text(args, "z_label", "z")
    trace = {"type": style, "x": _clean(xs), "y": _clean(ys), "z": _clean(Z),
             "colorscale": "Viridis", "colorbar": {"title": {"text": zlabel}}}
    if style == "contour":
        trace["contours"] = {"coloring": "heatmap"}
        layout = _layout(_text(args, "title", src), xaxis=_axis(_text(args, "x_label", "x")),
                         yaxis=_axis(_text(args, "y_label", "y")))
    else:
        layout = _layout(_text(args, "title", src),
                         scene=_scene(_text(args, "x_label", "x"), _text(args, "y_label", "y"), zlabel))
    i = int(np.nanargmax(Z)); j = int(np.nanargmin(Z))
    bad = int(np.isnan(Z).sum())
    note = (f"Plotted {style} of {src} for x in [{x0:g}, {x1:g}], y in [{y0:g}, {y1:g}]: "
            f"z from {Z.flat[j]:.4g} (at x={X.flat[j]:.4g}, y={Y.flat[j]:.4g}) to {Z.flat[i]:.4g} "
            f"(at x={X.flat[i]:.4g}, y={Y.flat[i]:.4g})")
    return (_text(args, "title", "") or "Plot: " + src), {"data": [trace], "layout": layout}, \
        note + (f"; undefined at {bad} of {Z.size} grid points." if bad else ".")


def plot_curve(args):
    xe, ye, ze = args.get("x"), args.get("y"), args.get("z")
    if xe in (None, "") or ye in (None, ""):
        raise PlotError("x and y (formulas in t) are required")
    t0, t1 = _range(args, "t_min", "t_max")
    ts = np.linspace(t0, t1, NCURVE)
    comps = [_sample(e, ts.shape, t=ts) for e in (xe, ye)]
    three_d = ze not in (None, "")
    if three_d:
        comps.append(_sample(ze, ts.shape, t=ts))
    bad = np.any([_undefined(c) for c in comps], axis=0)
    if bad.all():
        raise PlotError("the curve has no finite points for this t range")
    comps = [np.where(bad, np.nan, c) for c in comps]
    name = f"({xe}, {ye}" + (f", {ze})" if three_d else ")")
    title = _text(args, "title", "")
    xl, yl = _text(args, "x_label", "x"), _text(args, "y_label", "y")
    xyz = dict(zip("xyz", (_clean(c) for c in comps)))
    if three_d:
        fig = {"data": [{"type": "scatter3d", "mode": "lines", "name": name, **xyz}],
               "layout": _layout(title or name, scene=_scene(xl, yl, _text(args, "z_label", "z"),
                                                             aspectmode="data"))}
    else:
        fig = {"data": [{"type": "scatter", "mode": "lines", "name": name, "connectgaps": False, **xyz}],
               # equal axis scaling: a circle looks like a circle
               "layout": _layout(title or name, xaxis=_axis(xl), yaxis=_axis(yl, scaleanchor="x", scaleratio=1),
                                 showlegend=False)}
    rng = "; ".join(f"{n} in [{np.nanmin(c):.4g}, {np.nanmax(c):.4g}]" for n, c in zip("xyz", comps))
    return (title or "Curve: " + name), fig, \
        f"Plotted the curve {name} for t in [{t0:g}, {t1:g}]: {rng}" + \
        (f"; undefined at {int(bad.sum())} of {len(ts)} points." if bad.any() else ".")


NAMES = {"plot_2d": plot_2d, "plot_3d": plot_3d, "plot_curve": plot_curve}


# ─── tool schemas (what the model sees) ───

def _tool(name, desc, props, req):
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": req}}}


_S, _N = {"type": "string"}, {"type": "number"}
_SYNTAX = ("Formulas: use * for every multiplication (2*x, not 2x), ^ or ** for powers, constants pi and e, "
           "functions sin cos tan asin acos atan atan2 sinh cosh tanh exp log (natural) log10 sqrt cbrt abs sign "
           "floor ceil min max step. Range limits may be numbers or constant formulas like \"2*pi\". ")

TOOLS = [
    _tool("plot_2d", "Draw an interactive 2D graph of one or more functions y = f(x) and show it to the user. "
          "Use ONLY when the user explicitly asks for a graph/plot, or when a visual is essential to explain a relationship that prose and equations cannot communicate clearly. " + _SYNTAX +
          "Optional y_min and y_max (both) crop the vertical range, useful for tan or 1/x.",
          {"exprs": {"type": "array", "items": _S, "description": 'formulas in x, e.g. ["sin(x)", "x^2/10"] (max 6)'},
           "x_min": _N, "x_max": _N, "y_min": _N, "y_max": _N,
           "title": _S, "x_label": _S, "y_label": _S},
          ["exprs", "x_min", "x_max"]),
    _tool("plot_3d", "Draw an interactive 3D surface (or a 2D contour map) of z = f(x, y) and show it to the user. Use ONLY when explicitly requested or when the spatial shape is essential to the explanation; do not create one merely because an equation has multiple variables. " + _SYNTAX,
          {"expr": {"type": "string", "description": "formula in x and y, e.g. sin(x)*cos(y)"},
           "x_min": _N, "x_max": _N, "y_min": _N, "y_max": _N,
           "style": {"type": "string", "enum": ["surface", "contour"], "description": "surface (default, 3D) or contour (2D map)"},
           "title": _S, "x_label": _S, "y_label": _S, "z_label": _S},
          ["expr", "x_min", "x_max", "y_min", "y_max"]),
    _tool("plot_curve", "Draw a parametric curve (x(t), y(t)) in 2D, or (x(t), y(t), z(t)) in 3D if z is given: "
          "trajectories, orbits, Lissajous figures, helices. Use ONLY when explicitly requested or when the path/shape itself is essential to the task; do not plot a formula simply because it contains a parameter. " + _SYNTAX.replace("variables", "t"),
          {"x": {"type": "string", "description": "x(t), e.g. cos(t)"},
           "y": {"type": "string", "description": "y(t), e.g. sin(t)"},
           "z": {"type": "string", "description": "optional z(t), e.g. t/5 (makes the curve 3D)"},
           "t_min": _N, "t_max": _N, "title": _S, "x_label": _S, "y_label": _S, "z_label": _S},
          ["x", "y", "t_min", "t_max"]),
]

PLOT_PROMPT = (
    "\nGraphing is optional, not the default. Prefer a direct explanation in prose and equations. "
    "Create a graph ONLY if the user explicitly asks for a plot/graph/visualization, or if the visual "
    "itself is essential to understanding something that cannot be communicated clearly with prose, "
    "equations, or a small table. Before plotting, ask: what specific insight will this image add? "
    "If you cannot name a concrete insight, do not plot. Never make duplicate or near-duplicate plots, "
    "and never plot the exact solution and a numerical approximation side-by-side unless the user asks "
    "for a visual comparison or the comparison is central to the question. A request to solve, derive, "
    "calculate, apply a method, or explain an equation is NOT by itself a request for a graph. "
    "When unsure, answer without a graph. If the user explicitly requests a graph, create only the "
    "minimum number of plots needed. The graph appears in chat and is interactive. "
    "You cannot see it: use the tool summary to describe it."
)


def is_plot_tool(name):
    return name in NAMES


def run_for_chat(name, args, chat_id):
    """Run a plot tool and store the figure. Returns (text for the model, artifact dict for the UI or None).
    Never raises: a bad formula comes back as text so the model can fix it."""
    from .models import Artifact
    try:
        if not isinstance(args, dict):
            raise PlotError("arguments must be a JSON object")
        if "__raw__" in args:
            raise PlotError("the arguments were not valid JSON")
        if not chat_id:
            raise PlotError("there is no chat to show the plot in")
        title, fig, summary = NAMES[name](args)
        content = json.dumps(fig, allow_nan=False, separators=(",", ":"))
    except PlotError as e:
        return f"Plot error: {e}. Fix the arguments and call the tool again.", None
    except Exception as e:             # a bad formula must never kill the stream
        return f"Plot error ({e.__class__.__name__}): {e}", None
    art = Artifact.objects.create(chat_id=chat_id, title=title[:200], kind="plot", content=content)
    return (summary + " The graph is now shown to the user (interactive). Do not redraw it or repeat "
            "this call; describe what it shows."), {"id": art.id, "title": art.title, "kind": "plot"}


# ─── the page that draws a stored figure (served by views.artifact_view inside a sandboxed iframe) ───

def render_page(title, content):
    data = content.replace("<", "\\u003c")          # JSON stays valid; can't close the <script> tag
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title>"
        "<style>html,body{margin:0;height:100%;background:#fff;font:14px system-ui,sans-serif}"
        "#p{width:100%;height:100%}#err{padding:1rem;color:#a33}</style></head><body>"
        '<div id="p"></div>'
        f'<script src="{PLOTLY_SRC}"></script>'
        f'<script type="application/json" id="fig">{data}</script>'
        "<script>"
        "var el=document.getElementById('p');"
        "if(!window.Plotly){el.innerHTML='<div id=\"err\">Could not load Plotly from the CDN '"
        "+'(is this browser offline?).</div>';}"
        "else{var f=JSON.parse(document.getElementById('fig').textContent);"
        "Plotly.newPlot(el,f.data,f.layout,{responsive:true,displaylogo:false});}"
        "</script></body></html>"
    )
