from dataclasses import dataclass


@dataclass(frozen=True)
class ShipmateExportContext:
    node_id: str
    depth: int
    parent_id: str | None = None
    with_object_name: bool = True
    convert_coords: bool = True
