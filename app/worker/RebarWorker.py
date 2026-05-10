import json
import math
import traceback
from pathlib import Path

import NemAll_Python_BaseElements as AllplanBaseElements
import NemAll_Python_Geometry as AllplanGeo
import NemAll_Python_Reinforcement as AllplanReinf
from CreateElementResult import CreateElementResult
from TypeCollections.ModelEleList import ModelEleList


PROJECT_NAME = "viktor-template"
DRAWING_FILE_NUMBER = 1
STEEL_GRADE = -1
CONCRETE_GRADE = -1


def _log(message: str) -> None:
    log_path = Path(__file__).with_name("worker_log.txt")
    with log_path.open("a", encoding="utf-8") as file:
        file.write(f"{message}\n")


def _write_error(error: BaseException) -> None:
    error_path = Path(__file__).with_name("worker_error.txt")
    error_path.write_text(
        "".join(traceback.format_exception(type(error), error, error.__traceback__)),
        encoding="utf-8",
    )


def check_allplan_version(build_ele, version: float) -> bool:
    return True


def _load_inputs() -> dict:
    with Path(__file__).with_name("inputs.json").open("r", encoding="utf-8") as file:
        return json.load(file)


def _open_project(doc) -> None:
    current_project_name, host_name = AllplanBaseElements.ProjectService.GetCurrentProjectNameAndHost()

    if current_project_name == PROJECT_NAME:
        _log(f"Project '{PROJECT_NAME}' is already active.")
        return

    open_result = AllplanBaseElements.ProjectService.OpenProject(
        doc,
        host_name,
        PROJECT_NAME,
    )

    _log(f"OpenProject returned: {open_result}")

    if open_result not in ("Project opened", "Active project", "project opened"):
        raise RuntimeError(
            f"Could not open Allplan project '{PROJECT_NAME}'. "
            f"Current project was '{current_project_name}'. "
            f"Allplan returned: '{open_result}'."
        )


def _load_drawing_file(doc) -> None:
    drawing_service = AllplanBaseElements.DrawingFileService()

    drawing_service.LoadFile(
        doc,
        DRAWING_FILE_NUMBER,
        AllplanBaseElements.DrawingFileLoadState.ActiveForeground,
    )


def create_element(build_ele, doc) -> CreateElementResult:
    try:
        _log("Rebar PythonPart started.")
        data = _load_inputs()
        run_id = data["run_id"]

        done_marker = Path(__file__).with_name("worker_done.txt")
        result_path = Path(__file__).with_name("result.json")

        _log(f"Run ID: {run_id}.")
        _log("Opening project.")
        _open_project(doc)

        _log("Project opened.")
        _log(f"Loading drawing file {DRAWING_FILE_NUMBER}.")
        _load_drawing_file(doc)

        _log("Drawing file loaded.")
        _log("Creating pile cap, piles, and rebar elements.")
        elements = create_model_elements(data)

        _log("Writing elements to Allplan document.")
        AllplanBaseElements.CreateElements(
            doc,
            AllplanGeo.Matrix3D(),
            elements,
            [],
            None,
        )

        _log("CreateElements finished.")
        result = build_result(data, run_id)
        result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        _log("result.json written.")

        done_marker.write_text("done", encoding="utf-8")
        _log("worker_done.txt written.")

        return CreateElementResult()

    except BaseException as error:
        _log(f"Worker failed: {error}")
        _write_error(error)
        raise


def create_model_elements(data: dict) -> ModelEleList:
    elements = ModelEleList()

    add_concrete_context(elements, data)
    add_cap_rebar(elements, data)
    add_pile_rebar(elements, data)

    return elements


def add_concrete_context(elements: ModelEleList, data: dict) -> None:
    cap_placement = AllplanGeo.AxisPlacement3D(
        AllplanGeo.Point3D(-data["cap_length"] / 2.0, -data["cap_width"] / 2.0, 0.0),
        AllplanGeo.Vector3D(1.0, 0.0, 0.0),
        AllplanGeo.Vector3D(0.0, 0.0, 1.0),
    )
    elements.append_geometry_3d(
        AllplanGeo.BRep3D.CreateCuboid(
            cap_placement,
            data["cap_length"],
            data["cap_width"],
            data["cap_height"],
        )
    )

    for pile in data["pile_centers"]:
        pile_placement = AllplanGeo.AxisPlacement3D(
            AllplanGeo.Point3D(pile["x"], pile["y"], -data["pile_depth"]),
            AllplanGeo.Vector3D(1.0, 0.0, 0.0),
            AllplanGeo.Vector3D(0.0, 0.0, 1.0),
        )
        elements.append_geometry_3d(
            AllplanGeo.BRep3D.CreateCylinder(
                pile_placement,
                data["pile_diameter"] / 2.0,
                data["pile_depth"],
            )
        )


def add_cap_rebar(elements: ModelEleList, data: dict) -> None:
    cover = data["cover"]
    x_min = -data["cap_length"] / 2.0 + cover
    x_max = data["cap_length"] / 2.0 - cover
    y_min = -data["cap_width"] / 2.0 + cover
    y_max = data["cap_width"] / 2.0 - cover
    z_bottom = cover
    z_top = data["cap_height"] - cover

    y_positions = positions_between(y_min, y_max, data["mat_spacing"])
    x_positions = positions_between(x_min, x_max, data["mat_spacing"])

    for y in y_positions:
        elements.append(straight_bar(101, data["mat_bar_diameter"], (x_min, y, z_bottom), (x_max, y, z_bottom)))
        elements.append(straight_bar(201, data["mat_bar_diameter"], (x_min, y, z_top), (x_max, y, z_top)))

    for x in x_positions:
        elements.append(straight_bar(102, data["mat_bar_diameter"], (x, y_min, z_bottom), (x, y_max, z_bottom)))
        elements.append(straight_bar(202, data["mat_bar_diameter"], (x, y_min, z_top), (x, y_max, z_top)))

    for x in positions_between(x_min, x_max, data["stirrup_spacing"]):
        points = [
            (x, y_min, z_bottom),
            (x, y_max, z_bottom),
            (x, y_max, z_top),
            (x, y_min, z_top),
            (x, y_min, z_bottom),
        ]
        elements.append(closed_bar(301, data["stirrup_diameter"], points))


def add_pile_rebar(elements: ModelEleList, data: dict) -> None:
    radius = data["pile_diameter"] / 2.0 - data["cover"]
    z_min = -data["pile_depth"]
    z_max = data["cap_height"] - data["cover"]

    for pile in data["pile_centers"]:
        cx = pile["x"]
        cy = pile["y"]

        for index in range(data["pile_vertical_count"]):
            angle = 2.0 * math.pi * index / data["pile_vertical_count"]
            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle)
            elements.append(straight_bar(401, data["pile_vertical_diameter"], (x, y, z_min), (x, y, z_max)))

        for z in positions_between(z_min, 0.0, data["pile_hoop_spacing"]):
            elements.append(pile_hoop(402, data["pile_hoop_diameter"], cx, cy, radius, z))


def straight_bar(position: int, diameter: float, start: tuple[float, float, float], end: tuple[float, float, float]):
    shape = AllplanReinf.BendingShape(AllplanGeo.Point3D(0.0, 0.0, 0.0), diameter, STEEL_GRADE, CONCRETE_GRADE)
    return AllplanReinf.BarPlacement(
        position,
        1,
        AllplanGeo.Vector3D(0.0, 0.0, 0.0),
        point(start),
        point(end),
        shape,
    )


def pile_hoop(position: int, diameter: float, cx: float, cy: float, radius: float, z: float):
    segments = 20
    points = []
    for index in range(segments + 1):
        angle = 2.0 * math.pi * index / segments
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle), z))
    return closed_bar(position, diameter, points)


def closed_bar(position: int, diameter: float, points: list[tuple[float, float, float]]):
    polyline = AllplanGeo.Polyline3D()
    for coords in points:
        polyline += point(coords)

    rollers = AllplanGeo.VecDoubleList([0.0] * (len(points) - 1))
    shape = AllplanReinf.BendingShape(
        polyline,
        rollers,
        diameter,
        STEEL_GRADE,
        CONCRETE_GRADE,
        AllplanReinf.BendingShapeType.eH1,
    )
    return AllplanReinf.BarPlacement(
        position,
        1,
        AllplanGeo.Vector3D(0.0, 0.0, 0.0),
        point(points[0]),
        point(points[0]),
        shape,
    )


def positions_between(start: float, end: float, spacing: float) -> list[float]:
    count = int((end - start) // spacing) + 1
    if count == 1:
        return [(start + end) / 2.0]
    return [start + index * (end - start) / (count - 1) for index in range(count)]


def point(coords: tuple[float, float, float]):
    return AllplanGeo.Point3D(coords[0], coords[1], coords[2])


def build_result(data: dict, run_id: str) -> dict:
    y_bars = len(positions_between(-data["cap_width"] / 2.0 + data["cover"], data["cap_width"] / 2.0 - data["cover"], data["mat_spacing"]))
    x_bars = len(positions_between(-data["cap_length"] / 2.0 + data["cover"], data["cap_length"] / 2.0 - data["cover"], data["mat_spacing"]))
    cap_link_count = len(positions_between(-data["cap_length"] / 2.0 + data["cover"], data["cap_length"] / 2.0 - data["cover"], data["stirrup_spacing"]))
    pile_hoop_count = len(positions_between(-data["pile_depth"], 0.0, data["pile_hoop_spacing"]))

    return {
        "run_id": run_id,
        "project_name": PROJECT_NAME,
        "drawing_file_number": DRAWING_FILE_NUMBER,
        "created": {
            "pile_cap": 1,
            "piles": len(data["pile_centers"]),
            "cap_mat_bars": 2 * y_bars + 2 * x_bars,
            "cap_links": cap_link_count,
            "pile_vertical_bars": len(data["pile_centers"]) * data["pile_vertical_count"],
            "pile_hoops": len(data["pile_centers"]) * pile_hoop_count,
        },
        "inputs": data,
    }
