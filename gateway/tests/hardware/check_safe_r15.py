"""Run native KiCad ERC/DRC on the frozen R15 ZIP without modifying it.

python -B tests/hardware/check_safe_r15.py ARCHIVE --cli kicad-cli
Add --project DIRECTORY to check a redrawn project against the frozen archive.
--self-test runs small mutation checks without KiCad or writing project files.
Use --cli /path/to/AppRun kicad-cli for the official Linux portable launcher.
Requires the KiCad version recorded in the archive. Work files are temporary.
"""
import argparse
import copy
import csv
import hashlib
import io
import json
import os
import re
import shutil
from pathlib import Path, PurePosixPath
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from zipfile import ZipFile


STEM = 'HabitatOS_SAFE_R15'
EXTERNAL = {'PICO1', 'R113', 'R120', 'SW_LEVEL', 'SW_LEAK'}
SOCKETS = {'SOCKET_PICO_1', 'SOCKET_PICO_2'}
# Independent whitelist: exact MPN + frozen source + reviewed replacement only.
YAGEO_RC_SOURCE = 'https://yageogroup.com/content/datasheet/asset/file/PYU-RC_GROUP_51_ROHS_L'
DATASHEET_CORRECTIONS = {
    'BC857B-7-F': ('https://www.diodes.com/assets/Datasheets/ds11108.pdf', 'https://www.diodes.com/datasheet/download/BC856A.pdf'),
    'BC847B-7-F': ('https://www.diodes.com/assets/Datasheets/ds11106.pdf', 'https://www.diodes.com/datasheet/download/BC847B.pdf'),
    'BAS116-7-F': ('https://www.diodes.com/assets/Datasheets/ds30259.pdf', 'https://www.diodes.com/datasheet/download/BAS116.pdf'),
    '1N4148W-7-F': ('https://www.diodes.com/assets/Datasheets/ds30086.pdf', 'https://www.diodes.com/datasheet/download/1N4148W.pdf'),
    # Murata-authored 2025 reference sheet, distributed by Mouser.
    'GRM2165C1H131JA01D': ('https://www.murata.com/en-global/products/capacitor/mlcc', 'https://www.mouser.lt/datasheet/3/76/2/GRM2165C1H131JA01_01A.pdf'),
    'GRM21BR71E105KA99L': ('https://www.murata.com/en-global/products/capacitor/mlcc', 'https://search.murata.co.jp/Ceramy/image/img/A01X/G101/ENG/GRM21BR71E105KA99-01.pdf'),
    'GRM21BR71H104KA01L': ('https://www.murata.com/en-global/products/capacitor/mlcc', 'https://search.murata.co.jp/Ceramy/image/img/A01X/G101/ENG/GRM21BR71H104KA01-01.pdf'),
    'RC0805FR-07118KL': ('https://www.digikey.com/en/products/detail/yageo/RC0805FR-07118KL/727566', YAGEO_RC_SOURCE),
    'RC0805FR-071KL': ('https://www.digikey.kr/ko/products/detail/yageo/RC0805FR-071KL/727444', YAGEO_RC_SOURCE),
    'RC1210FR-0768RL': ('https://www.yageo.com/en/Chart/Download/pdf/RC1210FR-0768RL', YAGEO_RC_SOURCE),
    **{mpn: ('https://www.yageo.com/en/Chart/Download/pdf/RC0805FR-0710KL', YAGEO_RC_SOURCE)
       for mpn in ('RC0805FR-07100KL', 'RC0805FR-0710KL', 'RC0805FR-071ML',
                   'RC0805FR-07200KL', 'RC0805FR-0722KL', 'RC0805FR-072K2L',
                   'RC0805FR-07422KL', 'RC0805FR-0747KL', 'RC0805FR-074K7L',
                   'RC0805FR-0762KL', 'RC0805FR-07887KL', 'RC0805FR-0797K6L')},
}
# KiCad adds the gate-unit suffix to these eight singleton NC net names.
NC_UNIT_SUFFIXES = {('U120', '8'): 'C', ('U120', '11'): 'D', ('U121', '8'): 'B',
                    ('U122', '6'): 'A', ('U122', '8'): 'B', ('U122', '9'): 'B',
                    ('U128', '6'): 'A', ('U128', '8'): 'B'}


def sexpr(text):
    """Read KiCad's nested lists; retain atom spelling for strict PCB comparison."""
    stack, roots = [], []
    for token in re.findall(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+', text):
        if token == '(':
            item = []
            (stack[-1] if stack else roots).append(item)
            stack.append(item)
        elif token == ')':
            if not stack:
                raise ValueError('Unbalanced KiCad expression')
            stack.pop()
        else:
            if not stack:
                raise ValueError('Unexpected KiCad atom outside expression')
            stack[-1].append(json.loads(token) if token.startswith('"') else token)
    if stack or len(roots) != 1:
        raise ValueError('Incomplete KiCad expression')
    return roots[0]


def children(node, name):
    return [item for item in node[1:] if isinstance(item, list) and item and item[0] == name]


def single(node, name):
    items = children(node, name)
    if len(items) != 1:
        raise ValueError(f'Expected exactly one {name}')
    return items[0]


def properties(node):
    items = children(node, 'property')
    result = {item[1]: item[2] for item in items}
    if len(result) != len(items):
        raise ValueError('Duplicate KiCad properties')
    return result


def equal(label, expected, actual):
    if expected != actual:
        detail = ''
        if isinstance(expected, dict) and isinstance(actual, dict):
            changed = [k for k in expected.keys() | actual.keys()
                       if k not in expected or k not in actual or expected[k] != actual[k]]
            detail = f' ({len(changed)} entries): ' + '; '.join(
                f'{k!r}: {str(expected.get(k, "<missing>"))[:120]!r} -> '
                f'{str(actual.get(k, "<missing>"))[:120]!r}'
                for k in sorted(changed, key=str)[:20])
        raise ValueError(label + ' differs from frozen R15' + detail)


def hierarchy(read, root_name=STEM + '.kicad_sch'):
    """Return all instantiated sheet paths and schematic trees without cycles."""
    trees, paths = {}, set()

    def visit(name, parent_path=None, sheet_uuid=None, ancestors=()):
        relative = PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or '\\' in name or ':' in name:
            raise ValueError('Unsafe schematic hierarchy path')
        if name in ancestors:
            raise ValueError('Cyclic schematic hierarchy')
        if name not in trees:
            trees[name] = sexpr(read(name))
        tree = trees[name]
        if tree[0] != 'kicad_sch':
            raise ValueError('Hierarchy member is not a schematic')
        path = ('/' + single(tree, 'uuid')[1] if parent_path is None
                else parent_path + '/' + sheet_uuid)
        if path in paths:
            raise ValueError('Duplicate sheet instance UUID path')
        paths.add(path)
        for sheet in children(tree, 'sheet'):
            filename = properties(sheet)['Sheetfile']
            child_name = str(relative.parent / filename)
            visit(child_name, path, single(sheet, 'uuid')[1], (*ancestors, name))
    visit(root_name)
    return trees, paths


def symbol_attributes(trees):
    components, units, flags = {}, set(), {}
    for tree in trees.values():
        for symbol in children(tree, 'symbol'):
            props = properties(symbol)
            ref = props['Reference']
            if ref.startswith('#'):
                if ref in flags:
                    raise ValueError('Duplicate power flag reference')
                flags[ref] = single(symbol, 'lib_id')[1]
                continue
            key = (ref, single(symbol, 'unit')[1])
            if key in units:
                raise ValueError('Duplicate component unit')
            units.add(key)
            record = {field: props.get(field, '') for field in ('Value', 'MPN', 'Footprint', 'Datasheet')}
            record.update({field: single(symbol, field)[1] for field in ('in_bom', 'on_board', 'dnp')})
            if ref in components and components[ref] != record:
                raise ValueError('Inconsistent metadata between component units: ' + ref)
            components[ref] = record
    return components, flags


def xml_contract(data):
    root = ET.fromstring(data)
    components, pins = {}, {}
    for comp in root.findall('./components/comp'):
        ref = comp.attrib['ref']
        if ref in components:
            raise ValueError('Duplicate exported component')
        props = {p.attrib['name']: p.get('value', '') for p in comp.findall('property')}
        components[ref] = {'value': comp.findtext('value', ''),
                           'MPN': props.get('MPN', ''),
                           'Datasheet': comp.findtext('datasheet', ''),
                           'footprint': comp.findtext('footprint', ''),
                           'on_board': 'exclude_from_board' not in props,
                           'in_bom': 'exclude_from_bom' not in props,
                           'dnp': 'dnp' in props}
    for net in root.findall('./nets/net'):
        name, nodes = net.attrib['name'], net.findall('node')
        is_nc = name.startswith('unconnected-(')
        if is_nc and (len(nodes) != 1 or '+no_connect' not in nodes[0].get('pintype', '')):
            raise ValueError('Unconnected net is not an explicit singleton NC')
        for node in nodes:
            key = (node.attrib['ref'], node.attrib['pin'])
            if key in pins:
                raise ValueError('Duplicate exported physical pin')
            pin_type = node.get('pintype', '')
            if not pin_type or ('+no_connect' in pin_type) != is_nc:
                raise ValueError('Missing pin type or NC connected to a named net')
            pins[key] = (None if is_nc else name, pin_type)
    return components, pins


def normalize_datasheets(original, candidate):
    """Normalize only explicitly approved source corrections, keeping all other fields."""
    normalized, changes = copy.deepcopy(candidate), []
    equal('Datasheet component set', set(original), set(candidate))
    for ref, record in original.items():
        actual = candidate[ref]
        old, new = record['Datasheet'], actual['Datasheet']
        if old == new:
            continue
        if (record['MPN'] != actual['MPN'] or
                DATASHEET_CORRECTIONS.get(record['MPN']) != (old, new)):
            raise ValueError('Unapproved datasheet source change: ' + ref)
        normalized[ref]['Datasheet'] = old
        changes.append({'ref': ref, 'MPN': record['MPN'], 'original_source': old, 'corrected_source': new})
    return normalized, sorted(changes, key=lambda item: item['ref'])


def check_contract(canonical, original_xml, candidate_xml, original_attributes, candidate_attributes):
    expected = {(c['ref'], str(pin)): net for c in canonical['components'] for pin, net in c['pins'].items()}
    original = xml_contract(original_xml)
    actual = xml_contract(candidate_xml)
    sources = {c['ref']: c['source_url'] for c in canonical['components']}
    equal('Original canonical datasheets', sources, {r: c['Datasheet'] for r, c in original[0].items()})
    equal('Original native datasheets', sources, {r: c['Datasheet'] for r, c in original_attributes[0].items()})
    equal('Original canonical pin map', expected, {k: v[0] for k, v in original[1].items()})
    equal('Candidate canonical pin map', expected, {k: v[0] for k, v in actual[1].items()})
    normalized_xml, source_changes = normalize_datasheets(original[0], actual[0])
    normalized_attributes, attribute_changes = normalize_datasheets(original_attributes[0], candidate_attributes[0])
    equal('Datasheet corrections in native and exported symbols', source_changes, attribute_changes)
    equal('Exported component metadata', original[0], normalized_xml)
    equal('Physical pin types and NC markers', original[1], actual[1])
    equal('Schematic component attributes', original_attributes[0], normalized_attributes)
    equal('Power declarations', original_attributes[1], candidate_attributes[1])
    if len(actual[0]) != 198 or len(actual[1]) != 695 or sum(v[0] is None for v in actual[1].values()) != 47:
        raise ValueError('Unexpected R15 component, pin or NC counts')
    external = {r for r, c in actual[0].items() if not c['on_board']}
    equal('External component set', EXTERNAL, external)
    return {'components': 198, 'pins': 695, 'explicit_nc': 47,
            'external_components': sorted(external), 'pin_mismatches': 0,
            'metadata_mismatches': 0, 'pin_type_changes': 0,
            'datasheet_corrections': source_changes}


def without_paths(node):
    if not isinstance(node, list):
        return node
    return [without_paths(item) for item in node
            if not (isinstance(item, list) and item and item[0] == 'path')]


def nc_names(data):
    # Validate singleton/no-connect markers before retaining generated names.
    xml_contract(data)
    names = {}
    for net in ET.fromstring(data).findall('./nets/net'):
        if net.attrib['name'].startswith('unconnected-('):
            node = net.find('node')
            names[(node.attrib['ref'], node.attrib['pin'])] = net.attrib['name']
    return names


def walk(node):
    if isinstance(node, list):
        yield node
        for item in node:
            yield from walk(item)


def normalize_nc_names(original, candidate, canonical, original_xml, candidate_xml):
    """Allow only proven singleton NC metadata renames, never net/geometry edits."""
    old_names, new_names = nc_names(original_xml), nc_names(candidate_xml)
    equal('NC physical pin set', set(old_names), set(new_names))
    canonical_pins = {(c['ref'], str(p)): n for c in canonical['components'] for p, n in c['pins'].items()}
    normalized, changes = copy.deepcopy(candidate), []
    for key, old_name in sorted(old_names.items()):
        new_name = new_names[key]
        if old_name == new_name:
            continue
        ref, pin = key
        suffix = NC_UNIT_SUFFIXES.get(key)
        expected = old_name.replace(f'unconnected-({ref}-', f'unconnected-({ref}{suffix}-', 1)
        if not suffix or canonical_pins.get(key, 'missing') is not None or new_name != expected:
            raise ValueError('Unapproved automatic NC name change: ' + str(key))
        code = None
        for board, name in ((original, old_name), (normalized, new_name)):
            pads = [p for f in children(board, 'footprint') if properties(f)['Reference'] == ref
                    for p in children(f, 'pad') if p[1] == pin]
            if len(pads) != 1:
                raise ValueError('NC rename requires exactly one physical pad')
            pad_net = single(pads[0], 'net')
            if len(pad_net) != 3 or pad_net[2] != name or (code is not None and pad_net[1] != code):
                raise ValueError('NC pad name or numeric net ID changed unexpectedly')
            code = pad_net[1]
            declarations = [n for n in children(board, 'net') if n[1] == code]
            # Exactly one root declaration and one pad reference: any additional
            # pad, track, arc, via or zone with this net ID is forbidden.
            uses = [n for n in walk(board) if n and n[0] == 'net' and len(n) > 1 and n[1] == code]
            if len(declarations) != 1 or declarations[0] != ['net', code, name] or len(uses) != 2:
                raise ValueError('NC net is not a singleton pad without copper connections')
            if board is normalized:
                declarations[0][2] = pad_net[2] = old_name
        changes.append({'ref': ref, 'pin': pin, 'net_id': code,
                        'original_name': old_name, 'candidate_name': new_name})
    return normalized, changes


def check_board(original, candidate, canonical, bom_text, original_xml=None, candidate_xml=None):
    normalized, nc_changes = candidate, []
    if original_xml is not None and candidate_xml is not None:
        normalized, nc_changes = normalize_nc_names(original, candidate, canonical, original_xml, candidate_xml)
    equal('PCB except UUID paths and verified singleton NC names', without_paths(original), without_paths(normalized))
    footprints = children(candidate, 'footprint')
    functional = {c['ref'] for c in canonical['components']} - EXTERNAL
    refs = [properties(f)['Reference'] for f in footprints]
    if len(refs) != 197 or len(set(refs)) != 197 or not functional <= set(refs) or len(functional) != 193:
        raise ValueError('Expected 193 functional footprints plus four mounting holes')
    holes = [f for f in footprints if properties(f)['Reference'] not in functional]
    if any('board_only' not in single(f, 'attr') for f in holes):
        raise ValueError('Nonfunctional footprints must remain board-only mounting holes')
    vendor = set()
    rows = list(csv.DictReader(io.StringIO(bom_text)))
    for row in rows:
        members = set(re.split(r'[,;\s]+', row['References'].strip()))
        if len(members) != int(row['Quantity']) or vendor & members:
            raise ValueError('Frozen vendor BOM contains duplicate references or wrong quantity')
        vendor.update(members)
    equal('Vendor PCBA references', functional - SOCKETS, vendor)
    if len(vendor) != 191 or len(rows) != 40:
        raise ValueError('Expected 191 vendor placements in 40 MPN groups')
    changed_paths = sum(children(a, 'path') != children(b, 'path')
                        for a, b in zip(children(original, 'footprint'), footprints))
    return {'footprints': 197, 'functional_placements': 193, 'vendor_placements': 191,
            'customer_sockets': 2, 'mounting_holes': 4, 'uuid_paths_changed': changed_paths,
            'nc_automatic_name_changes': nc_changes, 'geometry_changes': 0}


def check_settings(original, candidate, original_rules, candidate_rules):
    for section in ('board', 'net_settings', 'erc'):
        equal('Project ' + section + ' settings', original.get(section), candidate.get(section))
    equal('Custom PCB rules', original_rules, candidate_rules)


def project_files(project):
    suffixes = {'.kicad_sch', '.kicad_pcb', '.kicad_pro', '.kicad_dru', '.kicad_sym', '.kicad_mod'}
    files = {}
    for path in project.rglob('*'):
        if path.suffix not in suffixes and path.name not in {'fp-lib-table', 'sym-lib-table'}:
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(project):
            raise ValueError('Candidate project must not contain linked native files')
        if path.is_file():
            files[path.relative_to(project).as_posix()] = path.read_bytes()
    for required in (STEM + '.kicad_sch', STEM + '.kicad_pcb', STEM + '.kicad_pro', STEM + '.kicad_dru'):
        if required not in files:
            raise ValueError('Missing candidate native file: ' + required)
    return files


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(archive, cli, summary_path=None, pcb_python=None, project=None):
    archive = archive.resolve(strict=True)
    project = project.resolve(strict=True) if project else None
    if summary_path:
        summary_path = summary_path.resolve()
        if summary_path == archive or (summary_path.exists() and summary_path.samefile(archive)):
            raise ValueError('Summary output must not overwrite the source archive')
        if project and summary_path.is_relative_to(project):
            raise ValueError('Summary output must be outside the candidate native project')
    archive_hash = sha256(archive)
    summary = {'checked_at_utc': datetime.now(timezone.utc).isoformat(),
               'archive_sha256': archive_hash, 'physical_tests': 0, 'checks': []}
    project_tmp = Path(__file__).resolve().parents[2] / 'var' / 'tmp'
    project_tmp.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='kicad-r15-', dir=project_tmp) as work:
        root = Path(work)
        env = dict(os.environ, XDG_CONFIG_HOME=str(root / 'config'),
                   XDG_CACHE_HOME=str(root / 'cache'))
        with ZipFile(archive) as z:
            manifest = json.loads(z.read('HabitatOS_R15/pcb/release_manifest.json'))
            native = manifest['final_native_project_whitelist']
            if len(native) != 31:
                raise ValueError('Unexpected R15 native project file count')
            for item in native:
                relative = PurePosixPath(item['path_from_r15_root'])
                if relative.is_absolute() or '..' in relative.parts or relative.parts[0] != 'pcb':
                    raise ValueError('Unsafe or unexpected native project path')
                data = z.read('HabitatOS_R15/' + str(relative))
                if len(data) != item['bytes'] or hashlib.sha256(data).hexdigest() != item['sha256']:
                    raise ValueError(f'Native file differs from release manifest: {relative}')
                target = root.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            if project:
                canonical_data = z.read('HabitatOS_R15/circuit/r15_safety_pin_netlist.json')
                if hashlib.sha256(canonical_data).hexdigest() != manifest['canonical_sha256']:
                    raise ValueError('Canonical circuit differs from release manifest')
                canonical = json.loads(canonical_data)
                original_xml = z.read('HabitatOS_R15/schematic/validation/native_schematic_evidence/native_netlist.xml')
                xml_evidence = json.loads(z.read('HabitatOS_R15/schematic/validation/native_schematic_evidence/native_checks.json'))
                if hashlib.sha256(original_xml).hexdigest() != xml_evidence['native_netlist_sha256']:
                    raise ValueError('Original native XML differs from recorded evidence')
                bom_data = z.read('HabitatOS_R15/pcb/manufacturing/PCBA_BOM.csv')
                bom_record = next(item for item in manifest['manufacturing_files']
                                  if item['path_from_r15_root'] == 'pcb/manufacturing/PCBA_BOM.csv')
                if len(bom_data) != bom_record['bytes'] or hashlib.sha256(bom_data).hexdigest() != bom_record['sha256']:
                    raise ValueError('Frozen vendor BOM differs from release manifest')
                bom_text = bom_data.decode('utf-8-sig')
        pcb = root / 'pcb'
        settings = json.loads((pcb / 'HabitatOS_SAFE_R15.kicad_pro').read_text())
        expected_sheet_paths = None
        if project:
            source_files = project_files(project)
            original_trees, _ = hierarchy(lambda name: (pcb / name).read_text(encoding='utf-8'))
            candidate_trees, expected_sheet_paths = hierarchy(lambda name: source_files[name].decode('utf-8-sig'))
            schematic_names = {name for name in source_files if name.endswith('.kicad_sch')}
            equal('Candidate reachable schematic files', schematic_names, set(candidate_trees))
            original_attributes = symbol_attributes(original_trees)
            candidate_attributes = symbol_attributes(candidate_trees)
            candidate_settings = json.loads(source_files[STEM + '.kicad_pro'])
            check_settings(settings, candidate_settings, (pcb / (STEM + '.kicad_dru')).read_bytes(),
                           source_files[STEM + '.kicad_dru'])
            original_board = sexpr((pcb / (STEM + '.kicad_pcb')).read_text(encoding='utf-8'))
            candidate_board = sexpr(source_files[STEM + '.kicad_pcb'].decode('utf-8-sig'))
            pcb = root / 'candidate'
            for name, data in source_files.items():
                target = pcb / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            settings = candidate_settings
            summary['candidate_project'] = str(project)
            summary['candidate_files_sha256'] = {name: hashlib.sha256(data).hexdigest()
                                                  for name, data in source_files.items()}
            summary['expected_sheet_instances'] = len(expected_sheet_paths)
        rules = settings['board']['design_settings']
        if rules.get('drc_exclusions') or any(v == 'ignore' for v in rules['rule_severities'].values()):
            raise ValueError('R15 project suppresses DRC checks')
        summary['drc_rule_categories'] = len(rules['rule_severities'])
        summary['ignored_rules'] = summary['exclusions'] = 0
        summary['native_files_verified'] = len(native)
        version = subprocess.run([*cli, 'version'], cwd=pcb, env=env, capture_output=True,
                                 text=True, check=True, timeout=45).stdout.strip()
        if version != manifest['tools']['kicad_cli']:
            raise ValueError(f'KiCad {version} differs from original {manifest["tools"]["kicad_cli"]}')
        summary['kicad_version'] = version
        if project:
            output = root / 'candidate-netlist.xml'
            command = [*cli, 'sch', 'export', 'netlist', '--format', 'kicadxml',
                       '--output', str(output), STEM + '.kicad_sch']
            result = subprocess.run(command, cwd=pcb, env=env, text=True,
                                    capture_output=True, timeout=300)
            if result.returncode or not output.is_file():
                raise RuntimeError(f'Native netlist export failed: {result.stderr} {result.stdout}')
            summary['schematic_equivalence'] = check_contract(
                canonical, original_xml, output.read_bytes(), original_attributes, candidate_attributes)
            summary['board_equivalence'] = check_board(original_board, candidate_board, canonical, bom_text,
                                                       original_xml, output.read_bytes())
            summary['netlist_export'] = {'command': command, 'exit_code': result.returncode,
                                         'sha256': sha256(output)}
        before = {item['path_from_r15_root']: item['sha256'] for item in native}
        checks = [('erc', 'HabitatOS_SAFE_R15.kicad_sch'), ('drc', 'HabitatOS_SAFE_R15.kicad_pcb')]
        if pcb_python:
            checks.append(('drc_refilled', 'HabitatOS_SAFE_R15.kicad_pcb'))
        for kind, filename in checks:
            current_pcb = pcb
            if kind == 'drc_refilled':
                current_pcb = root / 'refilled'
                shutil.copytree(pcb, current_pcb)
                code = (
                    'import json, pcbnew; '
                    f'assert pcbnew.GetBuildVersion().startswith({version!r}); '
                    f'board=pcbnew.LoadBoard({filename!r}); '
                    'zones=len(board.Zones()); assert zones > 0; '
                    'ok=pcbnew.ZONE_FILLER(board).Fill(board.Zones()); assert ok; '
                    f'pcbnew.SaveBoard({filename!r}, board); '
                    'print(json.dumps({"zones": zones, "fill_succeeded": bool(ok)}))'
                )
                fill = subprocess.run([*pcb_python, '-c', code], cwd=current_pcb, env=env,
                                      text=True, capture_output=True, timeout=300)
                if fill.returncode:
                    raise RuntimeError(f'Native KiCad zone fill failed: {fill.stderr} {fill.stdout}')
                summary['zone_refill'] = json.loads(fill.stdout.strip().splitlines()[-1])
                summary['refilled_board_sha256'] = sha256(current_pcb / filename)
            output = root / (kind + '.json')
            args = [*cli, 'sch' if kind == 'erc' else 'pcb', 'erc' if kind == 'erc' else 'drc',
                    '--format', 'json', '--severity-all', '--severity-exclusions',
                    '--exit-code-violations']
            if kind != 'erc':
                args += ['--all-track-errors', '--schematic-parity']
            args += ['--output', str(output), filename]
            print(f'Running KiCad {version} {kind.upper()}...', flush=True)
            result = subprocess.run(args, cwd=current_pcb, env=env, text=True,
                                    capture_output=True, timeout=300)
            if not output.exists():
                raise RuntimeError(f'KiCad {kind} did not write a report: {result.stderr} {result.stdout}')
            report = json.loads(output.read_text())
            if report.get('kicad_version') != version:
                raise ValueError('Unexpected report version')
            if report.get('source') != filename:
                raise ValueError('KiCad checked a different source file')
            if set(report.get('included_severities', [])) != {'error', 'warning', 'exclusion'}:
                raise ValueError('KiCad report did not include every severity')
            if kind == 'erc':
                sheets = report['sheets']
                if expected_sheet_paths is not None:
                    paths = [sheet['uuid_path'].rstrip('/') for sheet in sheets]
                    if len(paths) != len(set(paths)) or set(paths) != expected_sheet_paths:
                        raise ValueError('ERC did not inspect exactly the candidate sheet hierarchy')
                elif len(sheets) != 9:
                    raise ValueError('ERC did not inspect all 9 sheets')
                violations = [v for sheet in sheets for v in sheet['violations']]
                counts = {'sheets': len(sheets), 'violations': len(violations)}
            else:
                violations = report['violations']
                counts = {key: len(report[key]) for key in
                          ('violations', 'unconnected_items', 'schematic_parity')}
            check = {'kind': kind, 'command': args, 'exit_code': result.returncode,
                     'report_sha256': sha256(output), 'counts': counts,
                     'source': report['source'], 'included_severities': report['included_severities'],
                     'stdout': result.stdout.strip(), 'stderr': result.stderr.strip(),
                     'violation_examples': violations[:20]}
            if kind != 'erc':
                check['unconnected_examples'] = report['unconnected_items'][:20]
                check['schematic_parity_examples'] = report['schematic_parity'][:20]
            summary['checks'].append(check)
            print(json.dumps({'kind': kind, 'exit_code': result.returncode, **counts}), flush=True)
        summary['native_source_unchanged'] = all(
            sha256(root / filename) == checksum for filename, checksum in before.items())
        if project:
            summary['candidate_source_unchanged'] = project_files(project) == source_files
            summary['candidate_workcopy_unchanged'] = project_files(pcb) == source_files
    summary['archive_unchanged'] = sha256(archive) == archive_hash
    summary['passed'] = summary['native_source_unchanged'] and summary['archive_unchanged'] and all(
        check['exit_code'] == 0 and all(value == 0 for key, value in check['counts'].items()
                                      if key != 'sheets') for check in summary['checks'])
    if project:
        summary['passed'] = summary['passed'] and summary['candidate_source_unchanged'] and summary['candidate_workcopy_unchanged']
    if summary_path:
        summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)
    return 0 if summary['passed'] else 1


def self_test(archive):
    """Exercise preservation boundaries using the real frozen data, in memory."""
    with ZipFile(archive) as z:
        prefix = 'HabitatOS_R15/'
        canonical = json.loads(z.read(prefix + 'circuit/r15_safety_pin_netlist.json'))
        xml = z.read(prefix + 'schematic/validation/native_schematic_evidence/native_netlist.xml')
        trees, paths = hierarchy(lambda name: z.read(prefix + 'pcb/' + name).decode('utf-8-sig'))
        attributes = symbol_attributes(trees)
        board = sexpr(z.read(prefix + 'pcb/' + STEM + '.kicad_pcb').decode('utf-8-sig'))
        bom = z.read(prefix + 'pcb/manufacturing/PCBA_BOM.csv').decode('utf-8-sig')
        settings = json.loads(z.read(prefix + 'pcb/' + STEM + '.kicad_pro'))
        rules = z.read(prefix + 'pcb/' + STEM + '.kicad_dru')
    check_contract(canonical, xml, xml, attributes, attributes)
    check_board(board, board, canonical, bom)
    check_settings(settings, settings, rules, rules)
    if len(paths) != 9:
        raise AssertionError('Original hierarchy fixture differs')
    checks = ['original_contract', 'original_board', 'original_settings', 'original_hierarchy']

    def rejected(label, callback):
        try:
            callback()
        except ValueError:
            checks.append(label)
        else:
            raise AssertionError('Mutation was not detected: ' + label)

    corrected_xml = ET.fromstring(xml)
    corrected_attributes = copy.deepcopy(attributes)
    corrected_mpns = set()
    for comp in corrected_xml.findall('./components/comp'):
        ref = comp.attrib['ref']
        mpn = attributes[0][ref]['MPN']
        if mpn in DATASHEET_CORRECTIONS:
            old, new = DATASHEET_CORRECTIONS[mpn]
            equal('Frozen datasheet whitelist source', old, comp.findtext('datasheet'))
            comp.find('datasheet').text = new
            corrected_attributes[0][ref]['Datasheet'] = new
            corrected_mpns.add(mpn)
    equal('Exact datasheet whitelist coverage', set(DATASHEET_CORRECTIONS), corrected_mpns)
    corrected_bytes = ET.tostring(corrected_xml)
    result = check_contract(canonical, xml, corrected_bytes, attributes, corrected_attributes)
    if not result['datasheet_corrections']:
        raise AssertionError('Approved source corrections were not recorded')
    checks.append('exact_mpn_datasheet_corrections_allowed')
    rejected('native_export_datasheet_disagreement', lambda: check_contract(
        canonical, xml, corrected_bytes, attributes, attributes))
    for label, ref, replacement in (
            ('arbitrary_datasheet_url', 'Q101', 'https://example.invalid/anything.pdf'),
            ('approved_url_for_wrong_part', 'Q101', DATASHEET_CORRECTIONS['BC847B-7-F'][1]),
            ('unlisted_part_datasheet_changed', 'PICO1', DATASHEET_CORRECTIONS['BC857B-7-F'][1])):
        mutated = ET.fromstring(xml)
        mutated.find('./components/comp[@ref="' + ref + '"]/datasheet').text = replacement
        changed = copy.deepcopy(attributes)
        changed[0][ref]['Datasheet'] = replacement
        rejected(label, lambda: check_contract(canonical, xml, ET.tostring(mutated), attributes, changed))
    unknown_original = copy.deepcopy(attributes[0])
    unknown_original['Q101']['Datasheet'] = 'https://example.invalid/original.pdf'
    rejected('unapproved_original_datasheet_source', lambda: normalize_datasheets(
        unknown_original, corrected_attributes[0]))

    for label in ('net_change', 'nc_marker_removed', 'pin_type_weakened', 'mpn_change', 'component_removed'):
        candidate = ET.fromstring(xml)
        if label == 'net_change':
            candidate.find('./nets/net').set('name', 'MUTATED_NET')
        elif label == 'nc_marker_removed':
            node = next(n for n in candidate.findall('./nets/net/node') if '+no_connect' in n.get('pintype', ''))
            node.set('pintype', node.get('pintype').replace('+no_connect', ''))
        elif label == 'pin_type_weakened':
            node = next(n for n in candidate.findall('./nets/net/node') if n.get('pintype') == 'output')
            node.set('pintype', 'passive')
        elif label == 'mpn_change':
            candidate.find('./components/comp/property[@name="MPN"]').set('value', 'WRONG_MPN')
        else:
            candidate.find('components').remove(candidate.find('./components/comp'))
        mutated = ET.tostring(candidate)
        rejected(label, lambda: check_contract(canonical, xml, mutated, attributes, attributes))
    changed_attributes = copy.deepcopy(attributes)
    changed_attributes[0]['PICO1']['on_board'] = 'yes'
    rejected('external_part_moved_onboard', lambda: check_contract(
        canonical, xml, xml, attributes, changed_attributes))
    changed_board = copy.deepcopy(board)
    footprint = next(f for f in children(changed_board, 'footprint') if children(f, 'path'))
    single(footprint, 'path')[1] = '/new/sheet/uuid'
    result = check_board(board, changed_board, canonical, bom)
    if result['uuid_paths_changed'] != 1:
        raise AssertionError('Path-only change was not recorded')
    checks.append('path_only_change_allowed_pending_native_parity')
    single(footprint, 'at')[1] = '999'
    rejected('footprint_moved', lambda: check_board(board, changed_board, canonical, bom))
    changed_board = copy.deepcopy(board)
    pad = next(p for f in children(changed_board, 'footprint') for p in children(f, 'pad') if children(p, 'net'))
    single(pad, 'net')[-1] = 'WRONG_NET'
    rejected('pad_net_changed', lambda: check_board(board, changed_board, canonical, bom))
    changed_settings = copy.deepcopy(settings)
    changed_settings['board']['design_settings']['rule_severities']['clearance'] = 'ignore'
    rejected('rule_suppressed', lambda: check_settings(settings, changed_settings, rules, rules))
    renamed_xml = ET.fromstring(xml)
    renamed_board = copy.deepcopy(board)
    replacements = {}
    for net in renamed_xml.findall('./nets/net'):
        nodes = net.findall('node')
        if len(nodes) == 1:
            key = (nodes[0].get('ref'), nodes[0].get('pin'))
            if key in NC_UNIT_SUFFIXES:
                old = net.attrib['name']
                new = old.replace(f'unconnected-({key[0]}-',
                                  f'unconnected-({key[0]}{NC_UNIT_SUFFIXES[key]}-', 1)
                replacements[old] = new
                net.set('name', new)
    for node in walk(renamed_board):
        if len(node) == 3 and node[0] == 'net' and node[2] in replacements:
            node[2] = replacements[node[2]]
    renamed_bytes = ET.tostring(renamed_xml)
    result = check_board(board, renamed_board, canonical, bom, xml, renamed_bytes)
    if len(result['nc_automatic_name_changes']) != 8:
        raise AssertionError('Expected exactly eight approved NC metadata changes')
    checks.append('eight_singleton_nc_unit_suffix_names_allowed')
    bad_xml = copy.deepcopy(renamed_xml)
    first_nc = next(n for n in bad_xml.findall('./nets/net') if n.get('name') in replacements.values())
    first_nc.set('name', first_nc.get('name') + '_UNAPPROVED')
    rejected('nc_arbitrary_name', lambda: check_board(
        board, renamed_board, canonical, bom, xml, ET.tostring(bad_xml)))
    code = result['nc_automatic_name_changes'][0]['net_id']
    copper_added = copy.deepcopy(renamed_board)
    copper_added.append(['segment', ['start', '0', '0'], ['end', '1', '1'],
                         ['width', '0.25'], ['layer', 'F.Cu'], ['net', code]])
    rejected('nc_copper_added', lambda: check_board(board, copper_added, canonical, bom, xml, renamed_bytes))
    renumbered = copy.deepcopy(renamed_board)
    for node in walk(renumbered):
        if node and node[0] == 'net' and len(node) > 1 and node[1] == code:
            node[1] = '999999'
    rejected('nc_numeric_net_id_changed', lambda: check_board(
        board, renumbered, canonical, bom, xml, renamed_bytes))
    extra_pad = copy.deepcopy(renamed_board)
    owner = next(f for f in children(extra_pad, 'footprint')
                 if any(children(p, 'net') and single(p, 'net')[1] == code for p in children(f, 'pad')))
    pad = copy.deepcopy(next(p for p in children(owner, 'pad')
                             if children(p, 'net') and single(p, 'net')[1] == code))
    pad[1] = '999'
    owner.append(pad)
    rejected('nc_second_pad_added', lambda: check_board(board, extra_pad, canonical, bom, xml, renamed_bytes))
    print(json.dumps({'self_test': 'passed', 'checks': checks, 'count': len(checks),
                      'native_KiCad_executed': False, 'physical_tests': 0}, indent=2))
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--summary', type=Path)
    parser.add_argument('--project', type=Path, help='Redrawn native project directory to compare with the frozen archive')
    parser.add_argument('--self-test', action='store_true', help='Run in-memory preservation/mutation checks without KiCad')
    parser.add_argument('--cli', nargs='+', default=['kicad-cli'])
    parser.add_argument('--pcb-python', nargs='+', help='Matching Python command with KiCad pcbnew available; additionally refills a temporary copy')
    args = parser.parse_args()
    if args.self_test:
        raise SystemExit(self_test(args.archive))
    raise SystemExit(run(args.archive, args.cli, args.summary, args.pcb_python, args.project))
