"""Version-bound display layouts. Never infer coordinates for another cage."""
import json
from pathlib import Path

LAYOUTS = json.loads(Path(__file__).with_name('spatial-layouts.json').read_text())


def layout_for(item, configuration, gateway):
    entry = LAYOUTS.get(str(item.pk))
    if not entry or not gateway:
        return None
    layout = entry['layout']
    if (gateway.edge_gateway_id != entry['gatewayId'] or item.edge_cage_id != entry['cageId']
            or configuration.get('geometry_revision') != layout['geometryRevision']
            or configuration.get('placement_revision') != layout['placementRevision']):
        return None
    temperatures = {s['id'] for s in configuration.get('sensors', []) if s['unit'] == 'degC'}
    if not all(s['id'] in temperatures for s in layout['sensors']):
        return None
    return layout
