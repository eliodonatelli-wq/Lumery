"""Pure chain adapter contract; registration requires approval of shared files."""
from dataclasses import dataclass
from .automatic_mask import MaskSettings
from .manual_mask import MaskDocument, Geometry


@dataclass(frozen=True)
class NodeSettings:
    automatic: MaskSettings = MaskSettings(enabled=True)
    # Future chain serialization stores corrections separately from photo pixels.


def evaluate(ingress, state, settings, *, offset=(0, 0), source_id='', document=None):
    """Return the exact ingress object and independent native mask document."""
    geometry = Geometry(tuple(ingress.shape[:2]), tuple(offset), source_id)
    if not settings.automatic.enabled:
        return ingress, state, None
    result = MaskDocument(ingress, settings.automatic, geometry)
    if document is not None:
        if document.geometry != geometry:
            raise ValueError('Manual mask corrections require matching image geometry and source')
        result.tiles = {key: value.copy() for key, value in document.tiles.items()}
        result.strokes = None if document.strokes is None else document.strokes.copy()
    return ingress, state, result
