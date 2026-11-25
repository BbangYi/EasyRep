"""Import the pinned Zenodo release and existing gecko positives as lizard research data.

Publisher labels remain publisher labels, not independently reviewed truth. Original
asset families and visually similar images stay together; capture identities are unknown.
"""
import argparse
from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from behavior_recorder.analysis_features import save_artifact
from behavior_recorder.core import digest, require
from behavior_recorder.vision_data import image_info, load_dataset, output_directory, prepare_dataset, read_boxes


def asset_family(name):
    name = Path(name).name.split('.rf.')[0].lower()
    name = re.sub(r'_(jpg|jpeg|png|avif)$', '', name)
    if name.startswith(('img_', 'image_', 'videoframe_')):
        return 'unknown-capture-sequences'
    match = re.match(r'screenshot-(\d{4}-\d\d-\d\d)', name)
    return match[0] if match else name


def grouped_splits(rows):
    """Connected components also prevent transitive near-duplicates crossing splits."""
    parents = list(range(len(rows)))
    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    for i, row in enumerate(rows):
        for j in range(i):
            other = rows[j]
            if (row['family'] == other['family'] or row['pixel_sha256'] == other['pixel_sha256'] or
                    (row['dhash'] ^ other['dhash']).bit_count() <= 6):
                parents[root(i)] = root(j)
    components = {}
    for i, row in enumerate(rows):
        components.setdefault(root(i), []).append(row)
    for component in components.values():
        fixed = {r['original_split'] for r in component if r['origin'] == 'commons'}
        require(len(fixed) <= 1, 'near-duplicate existing gecko groups cross splits; review before importing')
        family = min(r['family'] for r in component)
        key = 'research-' + hashlib.sha256(family.encode()).hexdigest()[:20]
        bucket = int(hashlib.sha256(('split-42:' + family).encode()).hexdigest()[:8], 16) % 100
        split = next(iter(fixed)) if fixed else ('train' if bucket < 70 else 'val' if bucket < 85 else 'test')
        for row in component:
            row.update(group_id=key, split=split)
    return rows


def difference_hash(path):
    from PIL import Image
    with Image.open(path) as im:
        pixels = list(im.convert('L').resize((9, 8)).getdata())
    return sum((pixels[y*9+x] > pixels[y*9+x+1]) << (y*8+x) for y in range(8) for x in range(8))


def import_dataset(archive_path, metadata_path, commons_path, output):
    metadata = json.loads(metadata_path.read_text())
    require(metadata['id'] == 15616848, 'wrong publisher record')
    expected = metadata['files'][0]['checksum']
    require(expected == 'md5:e8b025714966316daf205c23465a5bc6', 'unexpected publisher release checksum')
    require(hashlib.md5(archive_path.read_bytes()).hexdigest() == expected[4:], 'archive checksum mismatch')
    commons = load_dataset(commons_path)
    with output_directory(output, 'import_public_reptile_research') as out:
        raw = out / 'assets'
        (raw / 'images').mkdir(parents=True)
        (raw / 'labels').mkdir()
        rows, duplicate_rows, quarantined_rows, seen_pixels = [], [], [], {}
        counts = Counter()
        with zipfile.ZipFile(archive_path) as archive:
            import yaml
            require(yaml.safe_load(archive.read('data.yaml'))['names'] == ['BeardedDragon', 'Cricket', 'HeatingLamp'],
                    'publisher label classes changed')
            for name in sorted(archive.namelist()):
                if '/images/' not in name or not name.endswith('.jpg'):
                    continue
                require(archive.getinfo(name).file_size <= 32*1024**2, 'oversized source image')
                label_name = name.replace('/images/', '/labels/').replace('.jpg', '.txt')
                require(label_name in archive.namelist(), 'missing publisher labels are not negatives')
                lines = archive.read(label_name).decode().splitlines()
                for line in lines:
                    require(len(line.split()) == 5 and line.split()[0] in {'0', '1', '2'}, 'invalid publisher label')
                    counts[line.split()[0]] += 1
                target_lines = [' '.join(line.split()) for line in lines if line.split()[0] == '0']
                if not target_lines:
                    quarantined_rows.append(dict(publisher_image=name, publisher_labels=lines,
                        reason='No target annotation does not establish absence; visual review required.'))
                    continue
                key = 'zenodo-' + hashlib.sha256(name.encode()).hexdigest()[:20]
                image, label = raw / 'images' / (key + '.jpg'), raw / 'labels' / (key + '.txt')
                image.write_bytes(archive.read(name))
                label.write_text(''.join(line + '\n' for line in target_lines))
                read_boxes(label)
                info = image_info(image)
                # Exact duplicates with inconsistent annotations are rejected, not selected arbitrarily.
                if info['pixel_sha256'] in seen_pixels:
                    prior = seen_pixels[info['pixel_sha256']]
                    require(label.read_text() == (raw / prior['label']).read_text(), 'conflicting duplicate labels')
                    duplicate_rows.append({'excluded': name, 'kept': prior['publisher_image']})
                    image.unlink(); label.unlink()
                    continue
                row = dict(id=key, image=image.relative_to(raw).as_posix(), label=label.relative_to(raw).as_posix(),
                           source_id='zenodo-15616848', family='zenodo:' + asset_family(name), origin='zenodo',
                           publisher_image=name, original_split=name.split('/')[0],
                           reviewer='Yermukan and Machado; publisher annotations', review_method='publisher_annotations',
                           species_confirmed=True, original_taxon='Pogona vitticeps', **info)
                seen_pixels[info['pixel_sha256']] = row
                rows.append(row)
        # Species-specific negatives can contain other lizards, so they cannot be reused as lizard negatives.
        for old in commons['records']:
            if not old['box_count']:
                continue
            row = dict(old, family='commons:' + old['group_id'], origin='commons', original_split=old['split'],
                       original_taxon='Correlophus ciliatus')
            for field in ('image', 'label'):
                path = raw / ('images' if field == 'image' else 'labels') / Path(old[field]).name
                shutil.copyfile(commons_path / old[field], path)
                row[field] = path.relative_to(raw).as_posix()
            rows.append(row)
        for row in rows:
            row['dhash'] = difference_hash(raw / row['image'])
        grouped_splits(rows)
        sources = commons['sources'] + [{
            'id': 'zenodo-15616848', 'url': metadata['doi_url'], 'license': 'CC BY 4.0 (publisher repository declaration)',
            'attribution': 'Arsen Yermukan and Pedro Machado (2025), Bearded Dragons activity recognition v1.0',
            'provenance': 'public_real', 'archive_sha256': digest(archive_path),
            'license_note': 'Embedded Roboflow export says Private; publisher Zenodo record says CC BY 4.0. Third-party image rights not independently verified. Research experiment; redistribution not cleared.',
            'changes': 'Keep class 0 as lizard; quarantine images without class 0 because publisher target coverage is incomplete; classes 1 and 2 omitted; regenerate asset-family splits; no pixel augmentation.'}]
        plan = dict(schema_version=1, species='lizard', dataset_kind='real', split_policy='asset_family_disjoint',
                    grouping_limit='Filename families and dHash distance <=6 grouped; exact decoded duplicates removed. Original capture sessions and animal identities unknown. Not a session/individual-disjoint benchmark.',
                    sources=sources, records=rows)
        save_artifact(raw / 'plan.json', plan)
        summary = prepare_dataset(raw, raw / 'plan.json', out / 'dataset')
        save_artifact(out / 'audit.json', dict(summary=summary, publisher_declared_images=694,
                      publisher_box_counts=dict(counts), exact_duplicates_removed=duplicate_rows,
                      quarantined_without_target_annotations=quarantined_rows,
                      excluded_species_specific_negatives=16, behavior_labels=0, anomaly_labels=0,
                      archive_sha256=digest(archive_path), independent_human_review=False))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--metadata', type=Path, required=True)
    parser.add_argument('--commons', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(import_dataset(args.archive, args.metadata, args.commons, args.output), indent=2))
