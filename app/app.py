import json
import math
import uuid
from pathlib import Path

import viktor as vkt
from viktor.external.python import PythonAnalysis


APP_DIR = Path(__file__).parent
ALLPLAN_WORKER_DIR = APP_DIR / "worker"


class Parametrization(vkt.Parametrization):
    geometry = vkt.Section("Geometry", initially_expanded=True)
    geometry.intro = vkt.Text(
        "# Pile Cap Rebar Demo\n\n"
        "Visual rebar geometry layout for a rectangular pile cap on four piles. "
        "Dimensions are in millimeters."
    )
    geometry.cap_length = vkt.NumberField("Pile cap length", default=4000.0, min=1200.0, suffix="mm", flex=50)
    geometry.cap_width = vkt.NumberField("Pile cap width", default=3000.0, min=1200.0, suffix="mm", flex=50)
    geometry.cap_height = vkt.NumberField("Pile cap height", default=800.0, min=300.0, suffix="mm", flex=50)
    geometry.pile_diameter = vkt.NumberField("Pile diameter", default=600.0, min=250.0, suffix="mm", flex=50)
    geometry.pile_depth = vkt.NumberField("Pile depth", default=3000.0, min=1000.0, suffix="mm", flex=50)
    geometry.pile_spacing_x = vkt.NumberField("Pile spacing X", default=2600.0, min=600.0, suffix="mm", flex=50)
    geometry.pile_spacing_y = vkt.NumberField("Pile spacing Y", default=1800.0, min=600.0, suffix="mm", flex=50)

    reinforcement = vkt.Section("Reinforcement", initially_expanded=True)
    reinforcement.cover = vkt.NumberField("Concrete cover", default=50.0, min=20.0, max=150.0, suffix="mm", flex=50)
    reinforcement.mat_bar_diameter = vkt.NumberField("Mat bar diameter", default=16.0, min=8.0, suffix="mm", flex=50)
    reinforcement.mat_spacing = vkt.NumberField("Mat spacing", default=180.0, min=75.0, suffix="mm", flex=50)
    reinforcement.pile_vertical_diameter = vkt.NumberField("Pile vertical bar diameter", default=16.0, min=8.0, suffix="mm", flex=50)
    reinforcement.pile_vertical_count = vkt.NumberField("Vertical bars per pile", default=8, min=4, max=16, flex=50)
    reinforcement.pile_hoop_diameter = vkt.NumberField("Pile hoop diameter", default=10.0, min=6.0, suffix="mm", flex=50)
    reinforcement.pile_hoop_spacing = vkt.NumberField("Pile hoop spacing", default=200.0, min=100.0, suffix="mm", flex=50)

    allplan = vkt.Section("Allplan", initially_expanded=True)
    allplan.download = vkt.DownloadButton(
        "Download Allplan project",
        method="download_allplan_project",
        longpoll=True,
        flex=100,
    )


class Controller(vkt.Controller):
    label = "Pile Cap Rebar"
    parametrization = Parametrization(width=36)

    @vkt.WebView("Visual rebar sketch", duration_guess=1)
    def rebar_sketch(self, params, **kwargs):
        data = self._worker_input(params)
        html = self._build_rebar_html(data)
        return vkt.WebResult(html=html)

    @vkt.TableView("Visual geometry schedule")
    def bar_schedule(self, params, **kwargs):
        rows = self._bar_schedule(self._worker_input(params))
        return vkt.TableResult(
            rows,
            column_headers=[
                "Item",
                "Geometry",
                "Diameter [mm]",
                "Spacing / count",
                "Quantity",
                "Unit length [m]",
                "Total length [m]",
            ],
            enable_sorting_and_filtering=False,
        )

    def download_allplan_project(self, params, **kwargs):
        worker_input = self._worker_input(params)
        run_id = uuid.uuid4().hex
        worker_input["run_id"] = run_id

        files = [
            ("inputs.json", vkt.File.from_data(json.dumps(worker_input, indent=2))),
            ("template_project.zip", vkt.File.from_path(ALLPLAN_WORKER_DIR / "viktor-template.prj.zip")),
            ("RebarWorker.pyp", vkt.File.from_path(ALLPLAN_WORKER_DIR / "RebarWorker.pyp")),
            ("RebarWorker.py", vkt.File.from_path(ALLPLAN_WORKER_DIR / "RebarWorker.py")),
        ]

        analysis = PythonAnalysis(
            script=vkt.File.from_path(ALLPLAN_WORKER_DIR / "run_allplan_model.py"),
            files=files,
            output_filenames=["result_project.zip", "result.json", "worker_log.txt"],
        )
        vkt.progress_message("Starting Allplan visual rebar worker.")
        analysis.execute(timeout=900)
        result_project_zip = analysis.get_output_file("result_project.zip")
        analysis.get_output_file("result.json")
        analysis.get_output_file("worker_log.txt")

        return vkt.DownloadResult(result_project_zip, f"result_project_{run_id}.zip")

    @classmethod
    def _worker_input(cls, params) -> dict:
        return {
            "cap_length": float(params.geometry.cap_length),
            "cap_width": float(params.geometry.cap_width),
            "cap_height": float(params.geometry.cap_height),
            "pile_diameter": float(params.geometry.pile_diameter),
            "pile_depth": float(params.geometry.pile_depth),
            "pile_centers": cls.get_pile_centers(params.geometry.pile_spacing_x, params.geometry.pile_spacing_y),
            "cover": float(params.reinforcement.cover),
            "mat_bar_diameter": float(params.reinforcement.mat_bar_diameter),
            "mat_spacing": float(params.reinforcement.mat_spacing),
            "pile_vertical_diameter": float(params.reinforcement.pile_vertical_diameter),
            "pile_vertical_count": int(params.reinforcement.pile_vertical_count),
            "pile_hoop_diameter": float(params.reinforcement.pile_hoop_diameter),
            "pile_hoop_spacing": float(params.reinforcement.pile_hoop_spacing),
        }

    @staticmethod
    def get_pile_centers(pile_spacing_x: float, pile_spacing_y: float) -> list[dict[str, float | str]]:
        half_x = pile_spacing_x / 2.0
        half_y = pile_spacing_y / 2.0

        return [
            {"id": "P1", "x": -half_x, "y": -half_y},
            {"id": "P2", "x": half_x, "y": -half_y},
            {"id": "P3", "x": -half_x, "y": half_y},
            {"id": "P4", "x": half_x, "y": half_y},
        ]

    @classmethod
    def _bar_schedule(cls, data: dict) -> list[list[str | int | float]]:
        clear_length = data["cap_length"] - 2.0 * data["cover"]
        clear_width = data["cap_width"] - 2.0 * data["cover"]
        bars_across_width = len(cls._sample_positions(cls._positions_between(clear_width, data["mat_spacing"])))
        bars_across_length = len(cls._sample_positions(cls._positions_between(clear_length, data["mat_spacing"])))
        hoop_count = cls._bar_count(data["pile_depth"], data["pile_hoop_spacing"])

        hoop_diameter = data["pile_diameter"] - 2.0 * data["cover"] - data["pile_hoop_diameter"]
        hoop_length = math.pi * hoop_diameter
        pile_vertical_length = data["pile_depth"] + data["cap_height"] - data["cover"]

        rows = [
            ["C1", "Cap mat X, bottom and top", data["mat_bar_diameter"], f"sampled @ {data['mat_spacing']:.0f} mm", 2 * bars_across_width, clear_length],
            ["C2", "Cap mat Y, bottom and top", data["mat_bar_diameter"], f"sampled @ {data['mat_spacing']:.0f} mm", 2 * bars_across_length, clear_width],
            [
                "P1",
                "Pile verticals",
                data["pile_vertical_diameter"],
                f"{data['pile_vertical_count']} per pile",
                4 * data["pile_vertical_count"],
                pile_vertical_length,
            ],
            ["P2", "Pile hoops", data["pile_hoop_diameter"], f"@ {data['pile_hoop_spacing']:.0f} mm", 4 * hoop_count, hoop_length],
        ]

        return [
            [mark, element, diameter, spacing, quantity, round(unit_length / 1000.0, 2), round(quantity * unit_length / 1000.0, 2)]
            for mark, element, diameter, spacing, quantity, unit_length in rows
        ]

    @staticmethod
    def _bar_count(span: float, spacing: float) -> int:
        return int(span // spacing) + 1

    @classmethod
    def _build_rebar_html(cls, data: dict) -> str:
        schedule = cls._bar_schedule(data)
        total_length = sum(row[-1] for row in schedule)

        plan = cls._plan_svg(data)
        elevation = cls._elevation_svg(data)

        return f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{
      margin: 0;
      background: #ffffff;
      color: #111111;
      font-family: Inter, Arial, sans-serif;
    }}
    .sheet {{
      padding: 24px;
    }}
    .header {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 24px;
      margin-bottom: 16px;
      border-bottom: 1px solid #d9d9d9;
      padding-bottom: 12px;
    }}
    h1 {{
      font-size: 22px;
      font-weight: 650;
      margin: 0;
      letter-spacing: 0;
    }}
    .meta {{
      display: flex;
      gap: 20px;
      color: #333333;
      font-size: 13px;
      white-space: nowrap;
    }}
    svg {{
      width: 100%;
      max-width: 1120px;
      height: auto;
      display: block;
      background: #ffffff;
      border: 1px solid #d9d9d9;
    }}
    .caption {{
      margin-top: 10px;
      color: #444444;
      font-size: 13px;
    }}
  </style>
</head>
<body>
  <div class="sheet">
    <div class="header">
      <h1>Pile Cap Rebar</h1>
      <div class="meta">
        <span>Concrete cover {data["cover"]:.0f} mm</span>
        <span>Visual geometry export</span>
        <span>Mat {data["mat_bar_diameter"]:.0f} @ {data["mat_spacing"]:.0f}</span>
        <span>Total visual length {total_length:.1f} m</span>
      </div>
    </div>
    <svg viewBox="0 0 1120 720" role="img" aria-label="Plan and elevation rebar sketch">
      {plan}
      {elevation}
    </svg>
    <div class="caption">Black lines show the concrete outline and visual rebar geometry. Dashed circles show the four piles.</div>
  </div>
</body>
</html>
"""

    @classmethod
    def _plan_svg(cls, data: dict) -> str:
        panel_x, panel_y, panel_w, panel_h = 40.0, 68.0, 500.0, 560.0
        scale = min(400.0 / data["cap_length"], 340.0 / data["cap_width"])
        cap_w = data["cap_length"] * scale
        cap_h = data["cap_width"] * scale
        x0 = panel_x + (panel_w - cap_w) / 2.0
        y0 = panel_y + 92.0 + (340.0 - cap_h) / 2.0
        cx = x0 + cap_w / 2.0
        cy = y0 + cap_h / 2.0

        clear_w = cap_w - 2.0 * data["cover"] * scale
        clear_h = cap_h - 2.0 * data["cover"] * scale
        clear_x0 = x0 + data["cover"] * scale
        clear_y0 = y0 + data["cover"] * scale

        bars_across_width = len(cls._sample_positions(cls._positions_between(data["cap_width"] - 2.0 * data["cover"], data["mat_spacing"])))
        bars_across_length = len(cls._sample_positions(cls._positions_between(data["cap_length"] - 2.0 * data["cover"], data["mat_spacing"])))

        bar_lines = []
        for index in range(bars_across_width):
            y = clear_y0 + cls._fraction(index, bars_across_width) * clear_h
            bar_lines.append(f'<line x1="{clear_x0:.2f}" y1="{y:.2f}" x2="{clear_x0 + clear_w:.2f}" y2="{y:.2f}" stroke="#111" stroke-width="1"/>')

        for index in range(bars_across_length):
            x = clear_x0 + cls._fraction(index, bars_across_length) * clear_w
            bar_lines.append(f'<line x1="{x:.2f}" y1="{clear_y0:.2f}" x2="{x:.2f}" y2="{clear_y0 + clear_h:.2f}" stroke="#111" stroke-width="1"/>')

        pile_marks = []
        pile_r = data["pile_diameter"] * scale / 2.0
        dot_r = max(1.7, data["pile_vertical_diameter"] * scale / 2.0)
        cage_r = max(1.0, pile_r - data["cover"] * scale)
        for pile in data["pile_centers"]:
            px = cx + pile["x"] * scale
            py = cy - pile["y"] * scale
            pile_marks.append(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="{pile_r:.2f}" fill="none" stroke="#111" stroke-width="1.4" stroke-dasharray="7 5"/>')
            for bar_index in range(data["pile_vertical_count"]):
                angle = 2.0 * math.pi * bar_index / data["pile_vertical_count"]
                bx = px + cage_r * math.cos(angle)
                by = py + cage_r * math.sin(angle)
                pile_marks.append(f'<circle cx="{bx:.2f}" cy="{by:.2f}" r="{dot_r:.2f}" fill="#111"/>')
            pile_marks.append(f'<text x="{px:.2f}" y="{py + pile_r + 18.0:.2f}" text-anchor="middle" font-size="12" fill="#111">{pile["id"]}</text>')

        return f"""
      <text x="{panel_x:.0f}" y="{panel_y:.0f}" font-size="16" font-weight="650" fill="#111">Plan</text>
      <rect x="{x0:.2f}" y="{y0:.2f}" width="{cap_w:.2f}" height="{cap_h:.2f}" fill="#fff" stroke="#111" stroke-width="2"/>
      <rect x="{clear_x0:.2f}" y="{clear_y0:.2f}" width="{clear_w:.2f}" height="{clear_h:.2f}" fill="none" stroke="#111" stroke-width="1" stroke-dasharray="4 4"/>
      {''.join(bar_lines)}
      {''.join(pile_marks)}
      <line x1="{x0:.2f}" y1="{y0 + cap_h + 42.0:.2f}" x2="{x0 + cap_w:.2f}" y2="{y0 + cap_h + 42.0:.2f}" stroke="#111" stroke-width="1"/>
      <text x="{cx:.2f}" y="{y0 + cap_h + 64.0:.2f}" text-anchor="middle" font-size="12" fill="#111">{data["cap_length"]:.0f} mm</text>
"""

    @classmethod
    def _elevation_svg(cls, data: dict) -> str:
        panel_x, panel_y = 610.0, 68.0
        scale = min(410.0 / data["cap_length"], 420.0 / (data["cap_height"] + data["pile_depth"]))
        cap_w = data["cap_length"] * scale
        cap_h = data["cap_height"] * scale
        pile_h = data["pile_depth"] * scale
        x0 = panel_x + (440.0 - cap_w) / 2.0
        y0 = panel_y + 104.0
        base_y = y0 + cap_h
        pile_r = data["pile_diameter"] * scale / 2.0

        cap_rebar = []
        for z in [data["cover"], data["cap_height"] - data["cover"]]:
            y = base_y - z * scale
            cap_rebar.append(f'<line x1="{x0 + data["cover"] * scale:.2f}" y1="{y:.2f}" x2="{x0 + cap_w - data["cover"] * scale:.2f}" y2="{y:.2f}" stroke="#111" stroke-width="2"/>')

        pile_lines = []
        visible_piles = [data["pile_centers"][0], data["pile_centers"][1]]
        hoop_count = cls._bar_count(data["pile_depth"], data["pile_hoop_spacing"])
        for pile in visible_piles:
            px = x0 + cap_w / 2.0 + pile["x"] * scale
            pile_lines.append(f'<line x1="{px - pile_r:.2f}" y1="{base_y:.2f}" x2="{px - pile_r:.2f}" y2="{base_y + pile_h:.2f}" stroke="#111" stroke-width="1.4" stroke-dasharray="6 5"/>')
            pile_lines.append(f'<line x1="{px + pile_r:.2f}" y1="{base_y:.2f}" x2="{px + pile_r:.2f}" y2="{base_y + pile_h:.2f}" stroke="#111" stroke-width="1.4" stroke-dasharray="6 5"/>')
            cage_x = max(2.0, pile_r - data["cover"] * scale)
            for side in [-1.0, 1.0]:
                pile_lines.append(f'<line x1="{px + side * cage_x:.2f}" y1="{base_y - data["cover"] * scale:.2f}" x2="{px + side * cage_x:.2f}" y2="{base_y + pile_h:.2f}" stroke="#111" stroke-width="2"/>')
            for index in range(hoop_count):
                y = base_y + cls._fraction(index, hoop_count) * pile_h
                pile_lines.append(f'<line x1="{px - cage_x:.2f}" y1="{y:.2f}" x2="{px + cage_x:.2f}" y2="{y:.2f}" stroke="#111" stroke-width="1"/>')

        return f"""
      <text x="{panel_x:.0f}" y="{panel_y:.0f}" font-size="16" font-weight="650" fill="#111">Elevation</text>
      <rect x="{x0:.2f}" y="{y0:.2f}" width="{cap_w:.2f}" height="{cap_h:.2f}" fill="#fff" stroke="#111" stroke-width="2"/>
      {''.join(cap_rebar)}
      {''.join(pile_lines)}
      <line x1="{x0 + cap_w + 30.0:.2f}" y1="{y0:.2f}" x2="{x0 + cap_w + 30.0:.2f}" y2="{base_y:.2f}" stroke="#111" stroke-width="1"/>
      <text x="{x0 + cap_w + 44.0:.2f}" y="{y0 + cap_h / 2.0:.2f}" font-size="12" fill="#111">{data["cap_height"]:.0f} mm</text>
"""

    @staticmethod
    def _fraction(index: int, count: int) -> float:
        return index / (count - 1) if count > 1 else 0.5

    @staticmethod
    def _positions_between(span: float, spacing: float) -> list[float]:
        count = int(span // spacing) + 1
        if count == 1:
            return [span / 2.0]
        return [index * span / (count - 1) for index in range(count)]

    @staticmethod
    def _sample_positions(values: list[float], max_count: int = 7) -> list[float]:
        if len(values) <= max_count:
            return values

        last_index = len(values) - 1
        return [values[round(index * last_index / (max_count - 1))] for index in range(max_count)]
