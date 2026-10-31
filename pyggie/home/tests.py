# home/tests.py — run with:  cd pyggie && python manage.py test home
# Covers the graph tools (home/plots.py) and how they are wired into plain chat, agent mode
# and the artifact page. No Ollama or network needed: the Ollama calls are faked.
import json
import re
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from . import agent, ollama, plots
from .agent import _compact_messages, _is_repeat, _research_limit_reached
from .models import Artifact, Chat


class AgentContinuityTests(SimpleTestCase):
    def test_compaction_preserves_recent_messages_and_roles(self):
        messages = [
            {"role": "user", "content": "Original task " + ("x" * 20000)},
            {"role": "tool", "tool_name": "web_search", "content": "Evidence " + ("y" * 20000)},
        ] + [{"role": "user", "content": f"recent-{i}"} for i in range(10)]

        compacted = _compact_messages(messages)

        self.assertEqual(len(compacted), len(messages))
        self.assertEqual(compacted[-1], messages[-1])
        self.assertEqual(compacted[-2], messages[-2])
        self.assertIn("older context compacted", compacted[0]["content"])
        self.assertEqual(compacted[1]["role"], "tool")
        self.assertEqual(compacted[1]["tool_name"], "web_search")

    def test_repeat_guard_detects_same_read_only_call(self):
        class Run:
            msgs = [
                {"role": "assistant", "tool_calls": [
                    {"function": {"name": "web_search", "arguments": {"query": "RC circuit"}}}
                ]},
                {"role": "assistant", "tool_calls": [
                    {"function": {"name": "web_search", "arguments": {"query": "RC circuit"}}}
                ]},
            ]

        self.assertTrue(_is_repeat(Run(), "web_search", {"query": "RC circuit"}))
        self.assertFalse(_is_repeat(Run(), "web_search", {"query": "different query"}))
        self.assertFalse(_is_repeat(Run(), "run_python", {"code": "print(1)"}))

    def test_research_limit_stops_semantically_different_searches(self):
        class Run:
            msgs = [
                {"role": "tool", "tool_name": "web_search", "content": "no useful results"},
                {"role": "tool", "tool_name": "web_search", "content": "same idea, rephrased"},
            ]

        self.assertTrue(_research_limit_reached(Run(), "web_search"))
        self.assertFalse(_research_limit_reached(Run(), "fetch_page"))
        self.assertFalse(_research_limit_reached(Run(), "run_python"))

def build(name, args):
    """Run a plot tool and return its figure; also checks the figure is strict JSON (no NaN)."""
    title, fig, summary = plots.NAMES[name](args)
    json.dumps(fig, allow_nan=False)
    return fig


class FormulaSafety(TestCase):
    """Formulas come from the model: anything but plain maths must be refused."""

    EVIL = [
        "__import__('os').system('id')", "().__class__", "x.__class__", "x.real", "open('f')",
        "lambda: 1", "[x for x in (1,)]", "(x for x in [1])", "{1: 2}", "'a'", "b'a'", "1j", "x[0]",
        "sin", "x if 1 else 2", "1 < 2", "x and 1", "not x", "exec('1')", "print(x)", "eval('1')",
        "sin(x, x)", "sin(x=1)", "f(x)", "x @ x", "x // 2", "x := 3", "sin(*x)", "...", "",
        "x" * 400,
    ]

    def test_rejected(self):
        for src in self.EVIL:
            with self.subTest(src=src[:40]):
                with self.assertRaises(plots.PlotError):
                    plots._sample(src, (3,), x=np.arange(3.0))

    def test_plain_maths_works(self):
        x = np.array([0.0, 1.0, 2.0])
        cases = {
            "sin(x)^2 + cos(x)^2": np.ones(3),
            "-x**2": -(x ** 2),                      # unary minus binds looser than **, as in maths
            "y = 2*x": 2 * x,                        # "y =" / "f(x) =" prefixes are accepted
            "f(x) = x + 1": x + 1,
            "e^-x": np.exp(-x),
            "π*x": np.pi * x,
            "x − 1": x - 1,                          # unicode minus
            "atan2(x, 1)": np.arctan2(x, 1),
            "step(x - 1)": np.heaviside(x - 1, 1),
            "3": np.full(3, 3.0),                    # constants are broadcast
        }
        for src, want in cases.items():
            with self.subTest(src=src):
                np.testing.assert_allclose(plots._sample(src, (3,), x=x), want, atol=1e-12)

    def test_huge_power_does_not_hang(self):
        t = time.time()
        with self.assertRaises(plots.PlotError):                  # all inf -> "no finite values"
            plots.plot_2d({"exprs": ["9**9**9"], "x_min": 0, "x_max": 1})
        self.assertLess(time.time() - t, 2)

    def test_names_are_per_tool(self):
        with self.assertRaises(plots.PlotError):                  # plot_2d has no variable y
            plots.plot_2d({"exprs": ["x*y"], "x_min": 0, "x_max": 1})


class Plot2D(TestCase):
    def test_two_curves(self):
        fig = build("plot_2d", {"exprs": ["sin(x)", "cos(x)"], "x_min": 0, "x_max": 6})
        self.assertEqual([t["name"] for t in fig["data"]], ["sin(x)", "cos(x)"])
        self.assertEqual(len(fig["data"][0]["x"]), plots.N2)
        self.assertTrue(all(-1 <= v <= 1 for v in fig["data"][0]["y"]))
        self.assertTrue(fig["layout"]["showlegend"])

    def test_range_formulas_and_single_string(self):
        fig = build("plot_2d", {"exprs": "sin(x); cos(x)", "x_min": "-2*pi", "x_max": "2*pi"})
        self.assertEqual(len(fig["data"]), 2)
        self.assertAlmostEqual(fig["data"][0]["x"][0], -2 * np.pi, places=4)

    def test_tan_is_cut_at_the_poles(self):
        y = build("plot_2d", {"exprs": ["tan(x)"], "x_min": -3.14159, "x_max": 3.14159})["data"][0]["y"]
        self.assertIn(None, y)
        for a, b in zip(y, y[1:]):
            if a is not None and b is not None and a * b < 0:
                self.assertLess(abs(a - b), 5)        # no false vertical line through a pole

    def test_reciprocal_has_gap(self):
        y = build("plot_2d", {"exprs": ["1/x"], "x_min": -5, "x_max": 5})["data"][0]["y"]
        for a, b in zip(y, y[1:]):
            if a is not None and b is not None:
                self.assertFalse(a < 0 < b and abs(a - b) > 5)

    def test_y_crop(self):
        fig = build("plot_2d", {"exprs": ["x"], "x_min": 0, "x_max": 9, "y_min": -2, "y_max": 2})
        self.assertEqual(fig["layout"]["yaxis"]["range"], [-2, 2])

    def test_summary_describes_curve(self):
        _, _, s = plots.plot_2d({"exprs": ["sin(x)"], "x_min": 0, "x_max": 6.2832})
        self.assertIn("sin(x)", s)
        self.assertIn("from -1", s)

    def test_bad_arguments(self):
        bad = [
            {"exprs": ["x"], "x_min": 1, "x_max": 1},
            {"exprs": ["x"], "x_min": 0},
            {"exprs": ["x"], "x_min": 0, "x_max": 1e9},
            {"exprs": ["x"], "x_min": 0, "x_max": 1, "y_min": 0},
            {"exprs": ["x"], "x_min": 0, "x_max": 1, "y_min": 2, "y_max": 1},
            {"exprs": ["x"] * 7, "x_min": 0, "x_max": 1},
            {"exprs": [], "x_min": 0, "x_max": 1},
            {"exprs": ["sqrt(-1-x^2)"], "x_min": 0, "x_max": 1},      # undefined everywhere
            {"exprs": ["x"], "x_min": "x", "x_max": 1},               # range limits cannot use variables
            {"exprs": ["x"], "x_min": True, "x_max": 1},
        ]
        for args in bad:
            with self.subTest(args=args):
                with self.assertRaises(plots.PlotError):
                    plots.plot_2d(args)


class Plot3D(TestCase):
    def test_surface_orientation(self):
        d = build("plot_3d", {"expr": "x + 10*y", "x_min": 0, "x_max": 1, "y_min": 0, "y_max": 2})["data"][0]
        self.assertEqual(d["type"], "surface")
        self.assertEqual((len(d["y"]), len(d["x"]), len(d["z"]), len(d["z"][0])), (plots.N3,) * 4)
        # z[row j][column i] = f(x_i, y_j)
        self.assertAlmostEqual(d["z"][2][5], d["x"][5] + 10 * d["y"][2], places=4)

    def test_contour_and_gaps(self):
        fig = build("plot_3d", {"expr": "sqrt(1 - x^2 - y^2)", "x_min": -1.5, "x_max": 1.5,
                                 "y_min": -1.5, "y_max": 1.5, "style": "contour"})
        d = fig["data"][0]
        self.assertEqual(d["type"], "contour")
        self.assertTrue(any(v is None for row in d["z"] for v in row))     # outside the disc: undefined
        self.assertNotIn("scene", fig["layout"])

    def test_bad_arguments(self):
        base = {"expr": "x*y", "x_min": 0, "x_max": 1, "y_min": 0, "y_max": 1}
        for patch in ({"style": "wireframe"}, {"y_min": None}, {"expr": ["x", "y"]}, {"expr": "z"}):
            with self.subTest(patch=patch):
                with self.assertRaises(plots.PlotError):
                    plots.plot_3d({**base, **patch})


class PlotCurve(TestCase):
    def test_circle_2d(self):
        fig = build("plot_curve", {"x": "cos(t)", "y": "sin(t)", "t_min": 0, "t_max": "2*pi"})
        d = fig["data"][0]
        self.assertEqual(d["type"], "scatter")
        self.assertTrue(all(abs(x * x + y * y - 1) < 1e-4 for x, y in zip(d["x"], d["y"])))
        self.assertEqual(fig["layout"]["yaxis"]["scaleanchor"], "x")       # round circle

    def test_helix_3d(self):
        d = build("plot_curve", {"x": "cos(t)", "y": "sin(t)", "z": "t/5", "t_min": 0, "t_max": 20})["data"][0]
        self.assertEqual(d["type"], "scatter3d")
        self.assertEqual(len(d["z"]), plots.NCURVE)

    def test_bad_arguments(self):
        for args in ({"x": "t", "t_min": 0, "t_max": 1}, {"x": "t", "y": "x", "t_min": 0, "t_max": 1},
                     {"x": "t", "y": "t", "t_min": 1, "t_max": 0}):
            with self.subTest(args=args):
                with self.assertRaises(plots.PlotError):
                    plots.plot_curve(args)


class Wiring(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("a", password="pw")
        self.chat = Chat.objects.create(user=self.user, title="t")

    def test_run_for_chat_stores_artifact(self):
        out, art = plots.run_for_chat("plot_2d", {"exprs": ["sin(x)"], "x_min": 0, "x_max": 3}, self.chat.id)
        self.assertEqual(art["kind"], "plot")
        stored = Artifact.objects.get(id=art["id"])
        self.assertEqual((stored.chat_id, stored.kind), (self.chat.id, "plot"))
        self.assertEqual(len(json.loads(stored.content)["data"]), 1)
        self.assertIn("shown to the user", out)

    def test_run_for_chat_errors_come_back_as_text(self):
        for args, chat_id in (({"exprs": ["__import__('os')"], "x_min": 0, "x_max": 1}, self.chat.id),
                              ({"exprs": ["x"], "x_min": 0, "x_max": 1}, None),
                              ({"__raw__": "{oops"}, self.chat.id), ([], self.chat.id)):
            out, art = plots.run_for_chat("plot_2d", args, chat_id)
            self.assertIsNone(art)
            self.assertTrue(out.startswith("Plot error"), out)
        self.assertEqual(Artifact.objects.count(), 0)

    def test_artifact_page(self):
        _, art = plots.run_for_chat("plot_3d", {"expr": "sin(x)*cos(y)", "x_min": -3, "x_max": 3,
                                                "y_min": -3, "y_max": 3}, self.chat.id)
        self.client.force_login(self.user)
        r = self.client.get(f"/artifact/{art['id']}/")
        page = r.content.decode()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r["Content-Type"].startswith("text/html"))
        self.assertIn("sandbox allow-scripts", r["Content-Security-Policy"])
        self.assertIn("plotly.js-dist-min", page)
        data = re.search(r'id="fig">(.*?)</script>', page, re.S).group(1)
        self.assertEqual(json.loads(data)["data"][0]["type"], "surface")
        # chat reload lists it, so it comes back after a refresh
        self.assertEqual(self.client.get(f"/chat/{self.chat.id}/").json()["artifacts"][0]["kind"], "plot")

    def test_artifact_page_other_user_404(self):
        _, art = plots.run_for_chat("plot_2d", {"exprs": ["x"], "x_min": 0, "x_max": 1}, self.chat.id)
        User.objects.create_user("b", password="pw")
        self.client.login(username="b", password="pw")
        self.assertEqual(self.client.get(f"/artifact/{art['id']}/").status_code, 404)

    def test_page_cannot_be_broken_out_of(self):
        page = plots.render_page("</title><script>x()</script>",
                                 json.dumps({"data": [{"name": "</script><script>x()</script>"}], "layout": {}}))
        self.assertEqual(page.count("</script>"), 3)            # only our own three script tags
        self.assertNotIn("<script>x()", page)

    def test_agent_execute_and_process(self):
        run = SimpleNamespace(id=1, chat_id=self.chat.id, msgs=[], allowed=[], pending=[],
                              new_artifacts=[], summary="", done=False)
        call = {"function": {"name": "plot_2d", "arguments": {"exprs": ["x^2"], "x_min": -2, "x_max": 2}}}
        events = list(agent._process(run, [call]))
        self.assertEqual([k for k, _ in events], ["tool", "result", "artifact"])
        self.assertEqual(events[2][1]["kind"], "plot")
        self.assertFalse(agent.needs_approval("plot_2d", {}))
        self.assertFalse((Path(settings.BASE_DIR) / "agent_workspaces" / str(self.chat.id)).exists())
        names = {t["function"]["name"] for t in agent.TOOLS}
        self.assertTrue({"plot_2d", "plot_3d", "plot_curve", "finish"} <= names)

    def test_agent_does_not_redraw_identical_plot(self):
        args = {"exprs": ["x"], "x_min": 0, "x_max": 1}
        call = {"function": {"name": "plot_2d", "arguments": args}}
        run = SimpleNamespace(msgs=[{"role": "assistant", "tool_calls": [call, call]}])
        self.assertTrue(agent._is_repeat(run, "plot_2d", args))

    def test_plain_chat_stream_draws_plot(self):
        class Resp:
            ok = True
            def __init__(self, *chunks): self.chunks = chunks
            def iter_lines(self): return (json.dumps(c).encode() for c in self.chunks)
            def close(self): pass
        plot_call = {"function": {"name": "plot_2d",
                                  "arguments": {"exprs": ["sin(x)"], "x_min": 0, "x_max": 6}}}
        responses = [Resp({"message": {"tool_calls": [plot_call]}, "done": True}),
                     Resp({"message": {"content": "It oscillates."}, "done": True})]
        with mock.patch.object(ollama, "get_caps", return_value=("completion", "tools")), \
             mock.patch.object(ollama, "is_loaded", return_value=True), \
             mock.patch.object(ollama.requests, "post", side_effect=responses) as post:
            events = list(ollama.chat_stream("m", [{"role": "user", "content": "plot sin"}], chat_id=self.chat.id))
        # tool -> result (closes the notice in the page) -> artifact -> answer, the same order as agent mode
        self.assertEqual([k for k, _ in events], ["tool", "result", "artifact", "token"])
        self.assertEqual(events[1][1]["name"], "plot_2d")
        self.assertIn("Plotted", events[1][1]["out"])
        first, second = (c.kwargs["json"] for c in post.call_args_list)
        self.assertIn("plot_3d", [t["function"]["name"] for t in first["tools"]])
        self.assertIn("plot_2d", first["messages"][0]["content"])            # system prompt mentions the tools
        self.assertIn("Plotted", second["messages"][-1]["content"])          # the model gets a summary back
        self.assertEqual(Artifact.objects.filter(chat=self.chat, kind="plot").count(), 1)

    def test_plain_chat_closes_every_tool_with_a_result(self):
        """Regression: plain chat sent "tool" but never "result", so the page left the notice on "running…"."""
        class Resp:
            ok = True
            def __init__(self, *chunks): self.chunks = chunks
            def iter_lines(self): return (json.dumps(c).encode() for c in self.chunks)
            def close(self): pass
        search = {"function": {"name": "web_search", "arguments": {"query": "rc circuit"}}}
        responses = [Resp({"message": {"tool_calls": [search]}, "done": True}),
                     Resp({"message": {"content": "ok"}, "done": True})]
        with mock.patch.object(ollama, "get_caps", return_value=("completion", "tools")), \
             mock.patch.object(ollama, "is_loaded", return_value=True), \
             mock.patch.object(ollama, "run_tool", return_value="[]" + "x" * 3000), \
             mock.patch.object(ollama.requests, "post", side_effect=responses):
            events = list(ollama.chat_stream("m", [{"role": "user", "content": "q"}], chat_id=self.chat.id))
        self.assertEqual([k for k, _ in events], ["tool", "result", "token"])
        self.assertEqual(events[1][1]["name"], "web_search")
        self.assertLessEqual(len(events[1][1]["out"]), 1500)             # clipped like agent mode

    def test_no_plot_prompt_without_tool_support(self):
        class Resp:
            ok = True
            def iter_lines(self): return iter([json.dumps({"message": {"content": "hi"}, "done": True}).encode()])
            def close(self): pass
        with mock.patch.object(ollama, "get_caps", return_value=("completion",)), \
             mock.patch.object(ollama, "is_loaded", return_value=True), \
             mock.patch.object(ollama.requests, "post", return_value=Resp()) as post:
            list(ollama.chat_stream("m", [{"role": "user", "content": "hi"}], chat_id=self.chat.id))
        sent = post.call_args.kwargs["json"]
        self.assertNotIn("tools", sent)
        self.assertNotIn("plot_2d", sent["messages"][0]["content"])


class ModelCapabilityFailureTests(SimpleTestCase):
    @mock.patch("home.ollama.get_caps", side_effect=RuntimeError(
        'Ollama 500: unsupported tensor "output.weight" size overflows'))
    @mock.patch("home.ollama.requests.get")
    def test_broken_model_does_not_break_model_listing(self, get, get_caps):
        get.return_value.ok = True
        get.return_value.json.return_value = {
            "models": [{"name": "broken-model:latest"}]
        }

        models = ollama.get_models()

        self.assertEqual(len(models), 1)
        self.assertEqual(models[0]["name"], "broken-model:latest")
        self.assertEqual(models[0]["caps"], [])
        self.assertIn("size overflows", models[0]["caps_error"])
