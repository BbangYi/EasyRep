"""Import traceable Open Images lizard boxes with source-group safeguards."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
import shutil
import sys
import time
from urllib.parse import urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from behavior_recorder.analysis_features import save_artifact
from behavior_recorder.core import RecorderError, digest, require
from behavior_recorder.vision_data import image_info, load_dataset, output_directory, prepare_dataset

CLASS_ID = '/m/04m9y'
BOX_URL = 'https://storage.googleapis.com/openimages/v6/oidv6-train-annotations-bbox.csv'
METADATA_URL = 'https://storage.googleapis.com/openimages/2018_04/train/train-images-boxable-with-rotation.csv'


def select_boxes(rows):
    selected, rejected = defaultdict(list), {}
    for row in rows:
        if row['LabelName'] != CLASS_ID:
            continue
        key = row['ImageID']
        if row['IsGroupOf'] != '0' or row['IsDepiction'] != '0':
            rejected[key] = 'group or depiction: partial labels would create false background'
            continue
        values = [float(row[name]) for name in ('XMin', 'XMax', 'YMin', 'YMax')]
        require(all(math.isfinite(v) and 0 <= v <= 1 for v in values), 'invalid Open Images coordinates')
        x1, x2, y1, y2 = values
        require(x2 > x1 and y2 > y1, 'empty Open Images box')
        require(row['Source'] in {'xclick', 'activemil'} and row['Confidence'] == '1',
                'unsupported or unverified annotation source')
        selected[key].append({'yolo': [round((x1+x2)/2, 8), round((y1+y2)/2, 8),
                                       round(x2-x1, 8), round(y2-y1, 8)],
                              'publisher_annotation': dict(row)})
    return {key: boxes for key, boxes in selected.items() if key not in rejected}, rejected


def author_family(metadata, image_id):
    profile = metadata.get('AuthorProfileURL', '').strip()
    parsed = urlsplit(profile)
    if parsed.hostname and parsed.path:
        return 'openimages-author:' + parsed.hostname.lower().removeprefix('www.') + parsed.path.rstrip('/')
    author = metadata.get('Author', '').strip().casefold()
    return 'openimages-author-name:' + author if author else 'openimages-unknown:' + image_id


def assign_groups(existing, additions):
    from scripts.import_bearded_research import grouped_splits
    # The existing grouping algorithm fixes rows tagged commons. Use temporary
    # copies so source provenance remains accurate in the resulting inventory.
    working = [dict(r, origin='commons', original_split=r['split'], family='prior:' + r['group_id'])
               for r in existing]
    working += [dict(r, origin='openimages') for r in additions]
    grouped_splits(working)
    return [dict(original, group_id=grouped['group_id'], split=grouped['split'])
            for original, grouped in zip(existing + additions, working)]


def fetch_index(output):
    """Stream the official inventory on the worker; retain only lizard rows/credits."""
    with output_directory(output, 'index_openimages_lizards') as out:
        start, total, matched, checksum = time.monotonic(), 0, [], hashlib.sha256()
        with urlopen(BOX_URL, timeout=45) as response:
            header = response.readline()
            checksum.update(header)
            total += len(header)
            last_report = 0
            for line in response:
                total += len(line)
                require(total < 3_000_000_000 and time.monotonic()-start < 900, 'annotation transfer budget exceeded')
                checksum.update(line)
                if b',/m/04m9y,' in line:
                    matched.append(line.decode('utf-8'))
                if total-last_report >= 250_000_000:
                    print(f'annotation scan {total//1_000_000} MB; lizard boxes {len(matched)}', flush=True)
                    last_report = total
            expected = response.headers.get('Content-Length')
            require(not expected or int(expected) == total, 'annotation response truncated')
        boxes, rejected = select_boxes(csv.DictReader([header.decode('utf-8'), *matched]))
        print(f'eligible annotated images {len(boxes)}; reading credits', flush=True)
        metadata = {}
        with urlopen(METADATA_URL, timeout=45) as response:
            for row in csv.DictReader(io.TextIOWrapper(response, encoding='utf-8')):
                require(time.monotonic()-start < 1200, 'metadata transfer budget exceeded')
                if row['ImageID'] in boxes:
                    metadata[row['ImageID']] = row
        require(set(metadata) == set(boxes), 'missing original image metadata')
        save_artifact(out / 'index.json', dict(schema_version=1, class_id=CLASS_ID,
                      box_url=BOX_URL, metadata_url=METADATA_URL, annotation_bytes=total,
                      annotation_sha256=checksum.hexdigest(), boxes=boxes, metadata=metadata,
                      excluded_images=rejected, capture_context='unknown: includes wild and captive images',
                      behavior_labels=0, anomaly_labels=0))
        print(json.dumps({'images': len(boxes), 'boxes': sum(map(len, boxes.values())),
                          'authors': len({author_family(m, k) for k, m in metadata.items()}),
                          'licenses': dict(Counter(m['License'] for m in metadata.values()))}), flush=True)


def download_assets(index_path, output):
    index = json.loads(index_path.read_text(encoding='utf-8'))
    require(index['class_id'] == CLASS_ID and index['box_url'] == BOX_URL, 'wrong annotation inventory')
    require(0 < len(index['boxes']) <= 10000, 'unexpected dataset size')
    with output_directory(output, 'download_openimages_lizards') as out:
        (out / 'images').mkdir()
        (out / 'labels').mkdir()
        excluded, selected = {}, []
        for key, metadata in sorted(index['metadata'].items()):
            require(re.fullmatch(r'[0-9a-f]{16}', key), 'invalid public image ID')
            if metadata['License'].rstrip('/') != 'https://creativecommons.org/licenses/by/2.0':
                excluded[key] = 'unexpected license declaration'
            elif metadata.get('Rotation') not in {'0', '0.0'}:
                excluded[key] = 'nonzero or unknown orientation requires separate review'
            else:
                selected.append(key)

        deadline = time.monotonic() + 1800
        def fetch(key):
            require(time.monotonic() < deadline, 'image transfer budget exceeded')
            url = f'https://open-images-dataset.s3.amazonaws.com/train/{key}.jpg'
            path = out / 'images' / f'oi-{key}.jpg'
            for attempt in range(3):
                try:
                    with urlopen(url, timeout=30) as response:
                        payload = response.read(4 * 1024**2 + 1)
                        require(0 < len(payload) <= 4 * 1024**2, 'oversized or empty image')
                        size = response.headers.get('Content-Length')
                        require(not size or len(payload) == int(size), 'truncated image')
                    path.write_bytes(payload)
                    info = image_info(path)
                    label = out / 'labels' / f'oi-{key}.txt'
                    label.write_text(''.join('0 ' + ' '.join(map(str, b['yolo'])) + '\n'
                                             for b in index['boxes'][key]), encoding='utf-8')
                    return dict(id='oi-' + key, image=path.relative_to(out).as_posix(),
                                label=label.relative_to(out).as_posix(), openimages_id=key,
                                family=author_family(index['metadata'][key], key), download_url=url,
                                image_sha256=digest(path), label_sha256=digest(label),
                                publisher_metadata=index['metadata'][key],
                                annotations=index['boxes'][key], **info)
                except (OSError, ValueError, RecorderError) as exc:
                    if attempt == 2:
                        return {'failed_id': key, 'reason': str(exc)}
                    time.sleep(attempt + 1)

        rows = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            for number, result in enumerate(pool.map(fetch, selected), 1):
                if 'failed_id' in result:
                    excluded[result['failed_id']] = result['reason']
                else:
                    rows.append(result)
                if number % 200 == 0:
                    print(f'downloaded {number}/{len(selected)}; usable {len(rows)}', flush=True)
        require(rows, 'no usable images downloaded')
        save_artifact(out / 'assets.json', dict(records=rows, excluded=excluded,
                      index_sha256=digest(index_path), image_license='CC BY 2.0 per publisher metadata',
                      annotation_license='CC BY 4.0; Google LLC', independent_human_review=False))
        print(f'usable images: {len(rows)}; excluded: {len(excluded)}', flush=True)


def prepare_combined(assets, existing_path, output, exclusions_path=None):
    from scripts.import_bearded_research import difference_hash
    inventory = json.loads((assets / 'assets.json').read_text(encoding='utf-8'))
    exclusions = json.loads(exclusions_path.read_text(encoding='utf-8')) if exclusions_path else {}
    require(isinstance(exclusions, dict) and all(re.fullmatch(r'[0-9a-f]{16}', k) and
            isinstance(v, str) and v.strip() for k, v in exclusions.items()), 'invalid exclusion inventory')
    previous = load_dataset(existing_path)
    require(previous['species'] == 'lizard', 'existing dataset must target lizards')
    with output_directory(output, 'combine_openimages_lizards') as out:
        raw = out / 'assets'
        (raw / 'images').mkdir(parents=True)
        (raw / 'labels').mkdir()
        existing, additions, sources, excluded = [], [], list(previous['sources']), []
        seen = set()
        for root, records, target in ((existing_path, previous['records'], existing),
                                       (assets, inventory['records'], additions)):
            for old in records:
                if old.get('openimages_id') in exclusions:
                    excluded.append({'id': old['id'], 'reason': exclusions[old['openimages_id']]})
                    continue
                if old['pixel_sha256'] in seen:
                    excluded.append({'id': old['id'], 'reason': 'exact decoded duplicate'})
                    continue
                row = dict(old)
                for field in ('image', 'label'):
                    source = root / old[field]
                    require(digest(source) == old[field + '_sha256'], 'source changed after inventory')
                    destination = raw / ('images' if field == 'image' else 'labels') / source.name
                    require(not destination.exists(), 'asset filename collision')
                    shutil.copyfile(source, destination)
                    row[field] = destination.relative_to(raw).as_posix()
                row['dhash'] = difference_hash(raw / row['image'])
                seen.add(row['pixel_sha256'])
                if target is additions:
                    metadata = row['publisher_metadata']
                    row.update(source_id=row['id'], review_method='publisher_annotations',
                               reviewer='Google LLC / Open Images annotators', species_confirmed=True,
                               origin='openimages', capture_context='unknown', original_split='train')
                    sources.append(dict(id=row['id'], url=metadata['OriginalLandingURL'],
                        license=metadata['License'], attribution=f"{metadata['Author']}: {metadata['Title']}",
                        provenance='public_real', annotation_attribution='Google LLC; CC BY 4.0',
                        license_note='Publisher metadata declaration; individual rights not independently reverified.',
                        changes='CVDF resized image; convert publisher lizard boxes to YOLO; no generated images.'))
                target.append(row)
        records = assign_groups(existing, additions)
        plan = dict(schema_version=1, species='lizard', dataset_kind='real',
                    split_policy='asset_family_disjoint', sources=sources, records=records,
                    grouping_limit='Existing splits fixed; Flickr author profiles and dHash distance <=6 form connected groups. Exact decoded duplicates removed. Capture sessions and individual animals unknown. Old test results already inspected; only development use until a new video evaluation is frozen.')
        save_artifact(raw / 'plan.json', plan)
        summary = prepare_dataset(raw, raw / 'plan.json', out / 'dataset')
        save_artifact(out / 'audit.json', dict(summary=summary, previous_dataset_id=previous['dataset_id'],
            added_openimages=len(additions), excluded=excluded, unconfirmed_captive_images=len(additions),
            behavior_labels=0, anomaly_labels=0, source_inventory_sha256=digest(assets / 'assets.json'),
            exclusions_sha256=digest(exclusions_path) if exclusions_path else None))
        print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest='mode', required=True)
    index_parser = modes.add_parser('index')
    index_parser.add_argument('--output', type=Path, required=True)
    fetch_parser = modes.add_parser('download')
    fetch_parser.add_argument('--index', type=Path, required=True)
    fetch_parser.add_argument('--output', type=Path, required=True)
    prepare_parser = modes.add_parser('prepare')
    prepare_parser.add_argument('--assets', type=Path, required=True)
    prepare_parser.add_argument('--existing', type=Path, required=True)
    prepare_parser.add_argument('--output', type=Path, required=True)
    prepare_parser.add_argument('--exclusions', type=Path)
    args = parser.parse_args()
    if args.mode == 'index':
        fetch_index(args.output)
    elif args.mode == 'download':
        download_assets(args.index, args.output)
    else:
        prepare_combined(args.assets, args.existing, args.output, args.exclusions)
