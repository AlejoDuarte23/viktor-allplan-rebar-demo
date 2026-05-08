import json
import math
from pathlib import Path

import NemAll_Python_Geometry as AllplanGeo
import NemAll_Python_Reinforcement as AllplanReinf
from CreateElementResult import CreateElementResult
from TypeCollections.ModelEleList import ModelEleList


STEEL_GRADE = -1
CONCRETE_GRADE = -1


def check_allplan_version(build_ele, version: float) -> bool:
    return True


def create_element(build_ele, doc) -> CreateElementResult:
    with Path(__file__).with_name("inputs.json").open("r", encoding="utf-8") as file:
        data = json.load(file)

    elements = ModelEleList()

    add_concrete_context(elements, data)
    add_cap_rebar(elements, data)
    add_pile_rebar(elements, data)

    result = CreateElementResult(elements)
    result.placement_point = AllplanGeo.Point3D(0.0, 0.0, 0.0)
    result.multi_placement = False

    return result


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
