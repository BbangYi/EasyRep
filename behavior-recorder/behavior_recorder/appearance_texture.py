"""Reviewed spatial contrast sidecars; engineering features, not shedding labels."""
import argparse
from io import BytesIO
import math
from pathlib import Path
import re
import json
import subprocess
import sys

from .analysis_features import fingerprint, save_artifact
from .appearance import color_features, local_bytes
from .appearance_series import ARTIFACT_LIMIT, load_artifact, validate_artifact
from .core import RecorderError, digest, identifier, now, number, read_json, relative, require, timestamp

FEATURE_VERSION = 'reviewed-srgb-spatial-contrast-v1'
MAX_PIXELS = 4 * 1024**2


def validate_plan(plan):
    require(isinstance(plan, dict) and set(plan) == {
        'schema_version', 'kind', 'observation_input', 'observation_artifact', 'observation_sha256',
        'extraction', 'geometry', 'review', 'evidence_reference'}, 'invalid texture plan fields')
    require(type(plan['schema_version']) is int and plan['schema_version'] == 1
            and plan['kind'] == 'appearance_texture_plan', 'unsupported texture plan')
    require(isinstance(plan['observation_sha256'], str)
            and re.fullmatch(r'[0-9a-f]{64}', plan['observation_sha256']), 'observation hash required')
    require(isinstance(plan['evidence_reference'], str) and 0 < len(plan['evidence_reference'].strip()) <= 1024,
            'texture measurement rationale required')
    extraction = plan['extraction']
    require(isinstance(extraction, dict) and set(extraction) == {
        'pixel_offset', 'minimum_pairs', 'max_clipped_fraction', 'max_scale_relative_error'}, 'invalid extraction settings')
    require(type(extraction['pixel_offset']) is int and 1 <= extraction['pixel_offset'] <= 64,
            'pixel offset must be an integer from 1 to 64')
    require(type(extraction['minimum_pairs']) is int and 16 <= extraction['minimum_pairs'] <= MAX_PIXELS,
            'explicit minimum pairs per direction required')
    number(extraction['max_clipped_fraction'], 0, 1)
    number(extraction['max_scale_relative_error'], 0, .5)
    geometry = plan['geometry']
    require(isinstance(geometry, dict) and set(geometry) == {
        'pixels_per_mm', 'scale_relative_error', 'reference_revision', 'pose_revision', 'planar_region_confirmed'},
        'explicit texture geometry required')
    reasons = []
    for key, lower, upper in [('pixels_per_mm', 1e-6, 1e6), ('scale_relative_error', 0, .5)]:
        if geometry[key] is None:
            reasons.append(key + '_unknown')
        else:
            number(geometry[key], lower, upper)
    for key in ('reference_revision', 'pose_revision'):
        if geometry[key] is None:
            reasons.append(key + '_unknown')
        else:
            identifier(geometry[key])
    require(type(geometry['planar_region_confirmed']) is bool, 'planar region review must be boolean')
    if not geometry['planar_region_confirmed']:
        reasons.append('planar_region_not_confirmed')
    if geometry['scale_relative_error'] is not None and geometry['scale_relative_error'] > extraction['max_scale_relative_error']:
        reasons.append('scale_error_above_limit')
    review = plan['review']
    require(isinstance(review, dict) and set(review) == {
        'observer', 'flat_lighting_confirmed', 'same_pose_confirmed', 'rights_confirmed', 'owner_id', 'rights_evidence'},
        'invalid texture review')
    identifier(review['observer'])
    for key in ('flat_lighting_confirmed', 'same_pose_confirmed', 'rights_confirmed'):
        require(type(review[key]) is bool, key + ' must be boolean')
        if not review[key]:
            reasons.append(key + '_not_confirmed')
    if review['owner_id'] is None:
        reasons.append('media_owner_unknown')
    else:
        identifier(review['owner_id'])
    if review['rights_evidence'] is None:
        reasons.append('media_rights_evidence_missing')
    else:
        require(isinstance(review['rights_evidence'], str) and 0 < len(review['rights_evidence'].strip()) <= 1024,
                'media-specific rights evidence required')
    return reasons


def spatial_contrast(intensity, mask, pixel_offset, minimum_pairs, guard=lambda: None):
    """Equal-direction mean absolute and RMS differences of contiguous skin pairs."""
    import numpy as np
    require(isinstance(intensity, np.ndarray) and isinstance(mask, np.ndarray), 'arrays required')
    require(intensity.ndim == mask.ndim == 2 and intensity.shape == mask.shape
            and 0 < intensity.size <= MAX_PIXELS, 'matching bounded intensity and mask arrays required')
    require(mask.dtype == np.bool_ and intensity.dtype.kind in 'fiu', 'boolean mask and numeric intensity required')
    require(bool(np.isfinite(intensity).all()) and bool(((intensity >= 0) & (intensity <= 1)).all()),
            'finite normalized intensity required')
    require(type(pixel_offset) is int and 1 <= pixel_offset <= 64, 'invalid pixel offset')
    require(type(minimum_pairs) is int and 16 <= minimum_pairs <= MAX_PIXELS, 'invalid pair minimum')
    guard()
    intensity = intensity.astype(np.float32, copy=False)
    directions, reasons = {}, []
    for name, axis in [('horizontal', 1), ('vertical', 0)]:
        guard()
        count, absolute, squared = 0, None, None
        if intensity.shape[axis] > pixel_offset:
            # Every pixel along a span must be reviewed skin, not merely its endpoints.
            prefix = np.cumsum(~mask, axis=axis, dtype=np.int32)
            padding = [(0, 0), (0, 0)]
            padding[axis] = (1, 0)
            prefix = np.pad(prefix, padding, constant_values=0)
            span = pixel_offset + 1
            if axis == 1:
                valid = (prefix[:, span:] - prefix[:, :-span]) == 0
                differences = intensity[:, pixel_offset:] - intensity[:, :-pixel_offset]
            else:
                valid = (prefix[span:, :] - prefix[:-span, :]) == 0
                differences = intensity[pixel_offset:, :] - intensity[:-pixel_offset, :]
            count = int(valid.sum())
            if count >= minimum_pairs:
                selected = differences[valid]
                absolute = float(np.abs(selected).mean(dtype=np.float64))
                squared = float(np.square(selected).mean(dtype=np.float64))
        if count < minimum_pairs:
            reasons.append('insufficient_' + name + '_skin_pairs')
        directions[name] = dict(pairs=count, mean_absolute_difference=absolute, mean_squared_difference=squared)
    guard()
    absolute = squared = None
    if not reasons:
        absolute = math.fsum(row['mean_absolute_difference'] for row in directions.values()) / 2
        squared = math.fsum(row['mean_squared_difference'] for row in directions.values()) / 2
    return dict(**directions, mean_absolute_difference=absolute,
                root_mean_square_difference=math.sqrt(squared) if squared is not None else None,
                reasons=reasons)


def collect_texture(plan_path, output_path, guard=lambda: None):
    path, output = Path(plan_path), Path(output_path)
    require(not output.exists(), 'output already exists; choose a new versioned filename')
    guard()
    plan = read_json(path, limit=ARTIFACT_LIMIT)
    reasons = validate_plan(plan)
    artifact_path = relative(path.parent, plan['observation_artifact'])
    artifact, artifact_hash = load_artifact(artifact_path)
    require(artifact_hash == plan['observation_sha256'], 'observation artifact hash mismatch')
    metadata, colour_reasons = validate_artifact(artifact)
    require(metadata['kind'] == 'color_observation', 'texture requires a colour observation')
    input_path = relative(path.parent, plan['observation_input'])
    declared = read_json(input_path, limit=ARTIFACT_LIMIT)
    require(declared == metadata, 'observation input disagrees with reviewed artifact metadata')
    reasons.extend(colour_reasons)
    features, measurements, group = None, None, None
    implementation = {name: digest(Path(__file__).parent / name)
                      for name in ('appearance_texture.py', 'appearance.py')}
    runtime = None
    media_reverified = False
    if not reasons:
        guard()
        image_bytes, image_file = local_bytes(input_path.parent, metadata['image'])
        mask_bytes, mask_file = local_bytes(input_path.parent, metadata['mask'])
        require(dict(image=image_file, mask=mask_file) == artifact['files'], 'media changed since colour review')
        # Reuse the exact RGB/mask/EXIF/ICC gates without changing the verified collector.
        # Decode again below only from the same already-checked bytes, not from mutable paths.
        regenerated = color_features(image_bytes, mask_bytes)
        require(regenerated == artifact['features'], 'recorded colour features disagree with source pixels')
        media_reverified = True
        runtime = dict(python=sys.version.split()[0], numpy=sys.modules['numpy'].__version__,
                       pillow=sys.modules['PIL'].__version__)
        guard()
        if regenerated['clipped_pixel_fraction'] > plan['extraction']['max_clipped_fraction']:
            reasons.append('clipped_skin_fraction_above_limit')
        else:
            import numpy as np
            from PIL import Image
            with Image.open(BytesIO(image_bytes)) as image, Image.open(BytesIO(mask_bytes)) as mask:
                intensity = np.asarray(image).mean(axis=2, dtype=np.float32) / 255.
                selection = np.asarray(mask) == 255
                measurements = spatial_contrast(intensity, selection, plan['extraction']['pixel_offset'],
                                                plan['extraction']['minimum_pairs'], guard)
            reasons.extend(measurements['reasons'])
            if not reasons:
                features = {key: measurements[key] for key in (
                    'mean_absolute_difference', 'root_mean_square_difference')}
                group = fingerprint(dict(feature_version=FEATURE_VERSION, colour_group=artifact['comparison_group'],
                                         extraction=plan['extraction'], geometry=plan['geometry'],
                                         implementation_sha256=implementation, runtime=runtime))
    created = now()
    available = max(timestamp(created), timestamp(artifact['created_at']), timestamp(metadata['observed_at']))
    scale = plan['geometry']['pixels_per_mm']
    scale_error = plan['geometry']['scale_relative_error']
    physical_interval = None
    if scale is not None and scale_error is not None:
        physical_interval = [plan['extraction']['pixel_offset'] / (scale * factor)
                             for factor in (1 + scale_error, 1 - scale_error)]
    result = dict(schema_version=1, kind='appearance_texture_observation', feature_version=FEATURE_VERSION,
        created_at=created, available_at=available.isoformat(), status='excluded' if reasons else 'measured',
        observation={key: metadata[key] for key in ('dataset_kind', 'record_id', 'animal_id', 'species',
                                                 'enclosure_id', 'body_region', 'observed_at')},
        observation_artifact=dict(path=plan['observation_artifact'], sha256=artifact_hash),
        observation_metadata_sha256=artifact['metadata_sha256'], plan_sha256=fingerprint(plan),
        extraction=plan['extraction'], geometry=plan['geometry'], review=plan['review'],
        implementation_sha256=implementation, runtime=runtime,
        physical_offset_mm=plan['extraction']['pixel_offset'] / scale if scale is not None else None,
        physical_offset_mm_interval=physical_interval,
        features=features, measurements=measurements, comparison_group=group, reasons=reasons,
        files=artifact['files'], media_reverified=media_reverified,
        actual_model_fit=False, shedding_prediction=None, actuation_allowed=False,
        evidence='Operator-declared identity, rights, scale, plane, pose and lighting; not independent verification. '
                 'The existing RGB/image/mask checks and source feature equality are reused before spatial measurement. '
                 'Intensity is the mean of encoded sRGB channels, not calibrated luminance. Differences use only '
                 'contiguous reviewed skin spans; horizontal and vertical directions have equal scalar weight. '
                 'Features remain sensitive to illumination, noise, pose and scale. They are engineering candidates, '
                 'not demonstrated skin physiology or shedding predictors. Pixel pairs are not independent animals '
                 'or cycles. Processing availability is not backdated to capture time.')
    guard()
    save_artifact(output, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='Measure reviewed skin spatial contrast on the declared CPU host')
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execution-host', required=True)
    args = parser.parse_args(argv)
    try:
        from .appearance_predictor import native_preflight
        require(not args.output.exists(), 'output already exists; choose a new version')
        preflight, guard = native_preflight(dict(execution_host=args.execution_host))
        result = collect_texture(args.plan, args.output, guard)
        print(json.dumps(dict(output=str(args.output.resolve()), status=result['status'], reasons=result['reasons'],
                              preflight=preflight, actual_model_fit=False, actuation_allowed=False)))
        return 0
    except (RecorderError, OSError, ValueError, KeyError, TypeError, ImportError, subprocess.TimeoutExpired) as exc:
        print(json.dumps(dict(error=type(exc).__name__, message=str(exc))), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
