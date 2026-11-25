"""Import a bounded camera-disjoint SAWIT adaptation set, preserving existing splits."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from behavior_recorder.analysis_features import save_artifact
from behavior_recorder.core import digest, require
from behavior_recorder.vision_data import image_info, load_dataset, output_directory, prepare_dataset
from scripts.import_bearded_research import difference_hash


def select_frames(labels, videos, excluded_cameras, max_per_video=8, frame_gap=12):
    selected = []
    for video in videos:
        name = video['video']
        camera = name.split('--')[0]
        if camera in excluded_cameras:
            continue
        available = sorted((int(Path(r['path']).stem.rsplit('_', 1)[1]), r)
                           for r in labels if r['path'].startswith(name + '_'))
        count = min(max_per_video, len(available))
        indexes = sorted({round(i * (len(available) - 1) / max(1, count - 1)) for i in range(count)})
        last = -frame_gap
        for index in indexes:
            frame, entry = available[index]
            if frame - last >= frame_gap:
                selected.append(dict(entry, camera=camera, video=name, frame=frame))
                last = frame
    return selected


def convert_labels(yolo, voc, width, height):
    rows, named = [s.split() for s in yolo.splitlines() if s.strip()], [s.split() for s in voc.splitlines() if s.strip()]
    require(rows and len(rows) == len(named), 'missing or partial publisher annotations')
    output = []
    for row, target in zip(rows, named):
        require(len(row) == 5 and row[0] == '1' and len(target) == 5 and target[0] == 'Lizard',
                'publisher class mapping differs from Lizard=1')
        x, y, w, h = map(float, row[1:])
        require(all(math.isfinite(v) and 0 < v <= 1 for v in (x, y, w, h)), 'invalid normalized box')
        xyxy = [(x-w/2)*width, (y-h/2)*height, (x+w/2)*width, (y+h/2)*height]
        require(all(abs(a-float(b)) <= 2 for a, b in zip(xyxy, target[1:])), 'YOLO and VOC boxes disagree')
        output.append('0 ' + ' '.join(row[1:]) + '\n')
    return ''.join(output)


def fetch_blob(entry, prefix):
    require('/' not in entry['path'] and '\\' not in entry['path'], 'unexpected source path')
    url = 'https://raw.githubusercontent.com/dtnguyen0304/sawit/main/' + prefix + '/' + entry['path']
    with urllib.request.urlopen(url, timeout=30) as response:
        payload = response.read(4 * 1024**2 + 1)
    require(len(payload) <= 4 * 1024**2, 'oversized source asset')
    actual = hashlib.sha1(b'blob ' + str(len(payload)).encode() + b'\0' + payload).hexdigest()
    require(actual == entry['sha'], 'source changed since pinned Git tree: ' + entry['path'])
    return payload


def import_camera(evidence, previous_path, evaluation_manifest, output):
    previous = load_dataset(previous_path)
    research = ROOT / 'data/public-reptile-research-20261018'
    labels = json.loads((research / 'sawit-train-label-index.json').read_text())
    images = json.loads((evidence / 'part2-index.json').read_text())
    voc = json.loads((evidence / 'voc-full-index.json').read_text())
    require(not any(d['truncated'] for d in (labels, images, voc)), 'truncated source index')
    require(labels['sha'] == '733c839c0ae8be8b676d120c69d60de6cd8b79ef' and
            images['sha'] == 'b039106f307843066cb573975dbc1df82d57c1fe' and
            voc['sha'] == '5d990788433d1e96cdafeb0079719ea78cb95ef8', 'source revision changed')
    evaluation = json.loads(evaluation_manifest.read_text())
    excluded_cameras = {v['file'].split('--')[0] for v in evaluation['videos']}
    inventory = json.loads((ROOT / 'data/openimages-lizard-20261019/next-source-inventory.json').read_text())
    selected = select_frames(labels['tree'], inventory['matched_training_label_families'], excluded_cameras)
    require(selected and {r['camera'] for r in selected} == {'TE1-015'}, 'unexpected adaptation cameras')
    image_index, voc_index = ({r['path']: r for r in index['tree']} for index in (images, voc))
    with output_directory(output, 'import_sawit_camera') as out:
        assets = out / 'assets'
        (assets / 'images').mkdir(parents=True)
        (assets / 'labels').mkdir()
        (assets / 'publisher-labels').mkdir()
        def download(row):
            image_entry = image_index[Path(row['path']).with_suffix('.jpeg').name]
            original = fetch_blob(row, 'data/labels/YOLO_format/train')
            named = fetch_blob(voc_index[row['path']], 'data/labels/VOC_format')
            image = assets / 'images' / image_entry['path']
            image.write_bytes(fetch_blob(image_entry, 'data/images/train/part2'))
            info = image_info(image)
            label = assets / 'labels' / row['path']
            label.write_text(convert_labels(original.decode(), named.decode(), info['width'], info['height']))
            (assets / 'publisher-labels' / row['path']).write_bytes(named)
            return dict(id='sawit-' + hashlib.sha256(row['path'].encode()).hexdigest()[:20],
                        image=image.relative_to(assets).as_posix(), label=label.relative_to(assets).as_posix(),
                        source_id='sawit-camera-te015', group_id='sawit-camera-TE1-015', split='train',
                        reviewer='Nguyen et al. (2023); publisher annotations', review_method='publisher_annotations',
                        species_confirmed=True, original_taxon='Lampropholis guichenoti',
                        publisher_image=image_entry['path'], source_video=row['video'], source_frame=row['frame'],
                        capture_context='wild_camera_trap', camera_id=row['camera'],
                        image_git_sha1=image_entry['sha'], label_git_sha1=row['sha'],
                        voc_git_sha1=voc_index[row['path']]['sha'], **info)
        with ThreadPoolExecutor(max_workers=3) as pool:
            candidates = list(pool.map(download, selected))
        seen_pixels = {r['pixel_sha256'] for r in previous['records']}
        heldout_hashes = [difference_hash(previous_path / r['image']) for r in previous['records'] if r['split'] != 'train']
        additions, rejected = [], []
        for row in candidates:
            image_hash = difference_hash(assets / row['image'])
            if row['pixel_sha256'] in seen_pixels or any((image_hash ^ h).bit_count() <= 6 for h in heldout_hashes):
                rejected.append(dict(id=row['id'], reason='duplicate or perceptual overlap with validation/test'))
            else:
                additions.append(row)
                seen_pixels.add(row['pixel_sha256'])
        records = []
        for old in previous['records']:
            row = dict(old)
            for field in ('image', 'label'):
                source = previous_path / old[field]
                target = assets / ('images' if field == 'image' else 'labels') / source.name
                require(not target.exists(), 'asset collision')
                shutil.copyfile(source, target)
                require(digest(target) == old[field + '_sha256'], 'previous source changed during copy')
                row[field] = target.relative_to(assets).as_posix()
            records.append(row)
        records += additions
        source = dict(id='sawit-camera-te015', url='https://github.com/dtnguyen0304/sawit',
                      attribution='Nguyen et al. (2023). SAWIT: A small-sized animal wild image dataset with annotations.',
                      license='MIT repository declaration; related source videos CC BY-NC-SA 4.0', provenance='public_real',
                      license_note='Research use; mixed image/video terms preserved; no unrestricted redistribution claim.',
                      changes='Verify Git blobs; compare YOLO/VOC labels; remap Lizard=1 to 0; sample at most 8 per video with frame gap >=12.')
        plan = {k: previous[k] for k in ('schema_version', 'species', 'dataset_kind', 'split_policy')}
        plan.update(sources=previous['sources'] + [source], records=records,
                    grouping_limit=previous['grouping_limit'] + ' Added one new wild camera, all frames train only; all evaluation cameras excluded. Adjacent adaptation frames remain correlated.')
        save_artifact(assets / 'plan.json', plan)
        summary = prepare_dataset(assets, assets / 'plan.json', out / 'dataset')
        save_artifact(out / 'audit.json', dict(summary=summary, previous_dataset_id=previous['dataset_id'],
            added_images=len(additions), new_cameras=1, new_videos=len({r['source_video'] for r in additions}),
            excluded_evaluation_cameras=sorted(excluded_cameras), rejected=rejected,
            previous_split_changes=0, validation_and_test_unchanged=True, independent_human_review=False,
            source_tree_sha1={k: v['sha'] for k, v in [('images', images), ('yolo', labels), ('voc', voc)]}))
        print(json.dumps({'added_images': len(additions), 'summary': summary}, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--previous', type=Path, required=True)
    parser.add_argument('--evaluation-manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    import_camera(args.evidence, args.previous, args.evaluation_manifest, args.output)
