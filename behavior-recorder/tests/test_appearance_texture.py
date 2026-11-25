"""New synthetic texture contracts; must execute on the PC, not biological proof."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_appearance as fixtures
from behavior_recorder.appearance import collect
from behavior_recorder.core import RecorderError, timestamp

if importlib.util.find_spec('behavior_recorder.appearance_texture'):
    from behavior_recorder import appearance_texture as texture
else:
    texture = None


class AppearanceTextureTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AppearanceTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.row = self.fixture.row
        self.plan = dict(schema_version=1,kind='appearance_texture_plan',observation_input='input.json',
            observation_artifact='colour.json',observation_sha256=None,
            extraction=dict(pixel_offset=1,minimum_pairs=16,max_clipped_fraction=.1,max_scale_relative_error=.05),
            geometry=dict(pixels_per_mm=10.,scale_relative_error=.02,reference_revision='scale-1',
                          pose_revision='pose-1',planar_region_confirmed=True),
            review=dict(observer='fixture-reviewer',flat_lighting_confirmed=True,same_pose_confirmed=True,
                        rights_confirmed=True,owner_id='fixture-creator',rights_evidence='generated test fixture only'),
            evidence_reference='synthetic geometry declaration, not animal observation')
        self.recollect()

    def api(self):
        self.assertIsNotNone(texture,'texture sidecar is not implemented')
        return texture

    def save(self,name,value):
        p=self.root/name;p.write_text(json.dumps(value));return p

    def recollect(self):
        self.save('input.json',self.row)
        path=self.root/('colour-'+str(len(list(self.root.glob('colour-*.json'))))+'.json')
        self.colour=collect(self.root/'input.json',path)
        self.plan['observation_artifact']=path.name
        self.plan['observation_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()

    def measure(self,name='texture.json'):
        return self.api().collect_texture(self.save('texture-plan.json',self.plan),self.root/name)

    def test_constant_and_checkerboard_have_hand_calculated_contrast(self):
        import numpy as np
        api=self.api();mask=np.ones((16,16),dtype=bool)
        constant=api.spatial_contrast(np.full((16,16),.5),mask,1,16)
        self.assertEqual(constant['mean_absolute_difference'],0.)
        self.assertEqual(constant['root_mean_square_difference'],0.)
        self.assertEqual(constant['horizontal']['pairs'],240)
        checker=(np.indices((16,16)).sum(axis=0)%2).astype(float)
        one=api.spatial_contrast(checker,mask,1,16)
        self.assertEqual(one['mean_absolute_difference'],1.)
        self.assertEqual(one['root_mean_square_difference'],1.)
        two=api.spatial_contrast(checker,mask,2,16)
        self.assertEqual(two['mean_absolute_difference'],0.)

    def test_no_spatial_pair_crosses_mask_hole(self):
        import numpy as np
        self.api();mask=np.ones((16,16),dtype=bool);mask[:,8]=False
        measured=texture.spatial_contrast(np.ones((16,16))*.4,mask,2,16)
        self.assertEqual(measured['horizontal']['pairs'],176)
        self.assertEqual(measured['vertical']['pairs'],210)

    def test_background_values_do_not_affect_skin_contrast(self):
        import numpy as np
        self.api();mask=np.zeros((16,16),dtype=bool);mask[2:14,2:14]=True
        a=np.full((16,16),.2);b=a.copy();b[~mask]=1
        self.assertEqual(texture.spatial_contrast(a,mask,1,16),texture.spatial_contrast(b,mask,1,16))

    def test_insufficient_directional_support_is_unknown_not_zero(self):
        import numpy as np
        self.api();mask=np.zeros((16,16),dtype=bool);mask[5,:]=True
        result=texture.spatial_contrast(np.zeros((16,16)),mask,1,16)
        self.assertIsNone(result['mean_absolute_difference'])
        self.assertIsNone(result['root_mean_square_difference'])
        self.assertIn('insufficient_vertical_skin_pairs',result['reasons'])

    def test_transposition_swaps_directional_counts_but_preserves_scalar(self):
        import numpy as np
        self.api();a=np.tile(np.linspace(0,1,16),(12,1));mask=np.ones(a.shape,dtype=bool)
        x=texture.spatial_contrast(a,mask,1,16);y=texture.spatial_contrast(a.T,mask.T,1,16)
        self.assertAlmostEqual(x['mean_absolute_difference'],y['mean_absolute_difference'])
        self.assertAlmostEqual(x['root_mean_square_difference'],y['root_mean_square_difference'])
        self.assertEqual(x['horizontal'],y['vertical'])

    def test_invalid_numeric_inputs_masks_and_limits_rejected(self):
        import numpy as np
        self.api()
        for a,mask,offset,minimum in [(np.array([[float('nan')]]),np.ones((1,1),dtype=bool),1,16),
                (np.zeros((8,8)),np.ones((8,8),dtype=int),1,16),
                (np.zeros((8,8)),np.ones((8,8),dtype=bool),True,16),
                (np.zeros((8,8)),np.ones((8,8),dtype=bool),65,16),
                (np.zeros((8,8)),np.ones((8,8),dtype=bool),1,0)]:
            with self.assertRaises(RecorderError):texture.spatial_contrast(a,mask,offset,minimum)

    def test_sidecar_binds_raw_bytes_geometry_and_processing_availability(self):
        result=self.measure()
        self.assertEqual(result['status'],'measured')
        self.assertEqual(result['features']['mean_absolute_difference'],0.)
        self.assertAlmostEqual(result['physical_offset_mm'],.1)
        self.assertAlmostEqual(result['physical_offset_mm_interval'][0],1/10.2)
        self.assertAlmostEqual(result['physical_offset_mm_interval'][1],1/9.8)
        self.assertEqual(result['files'],self.colour['files'])
        self.assertEqual(result['implementation_sha256']['appearance_texture.py'],hashlib.sha256(Path(texture.__file__).read_bytes()).hexdigest())
        self.assertTrue(result['runtime']['pillow']);self.assertTrue(result['runtime']['numpy'])
        self.assertEqual(result['observation']['record_id'],self.row['record_id'])
        self.assertGreaterEqual(timestamp(result['available_at']),timestamp(result['created_at']))
        self.assertGreaterEqual(timestamp(result['available_at']),timestamp(self.colour['created_at']))
        self.assertIsNone(result['shedding_prediction']);self.assertFalse(result['actuation_allowed'])

    def test_capture_and_rights_exclusions_never_decode_pixels(self):
        self.api()
        for field in ['rights_confirmed','flat_lighting_confirmed','same_pose_confirmed']:
            with self.subTest(field=field):
                self.plan['review'][field]=False
                with patch.object(texture,'local_bytes',side_effect=AssertionError('must not read media')):
                    report=self.measure(field+'.json')
                self.assertEqual(report['status'],'excluded');self.assertIsNone(report['features'])
                self.plan['review'][field]=True
        self.row['capture']['mode']='infrared';self.recollect()
        with patch.object(texture,'local_bytes',side_effect=AssertionError('must not read media')):
            report=self.measure('ir.json')
        self.assertIn('visible_rgb_required',report['reasons'])

    def test_unknown_scale_pose_and_nonplanar_skin_are_excluded(self):
        for field,value in [('pixels_per_mm',None),('scale_relative_error',None),('reference_revision',None),
                            ('pose_revision',None),('planar_region_confirmed',False),('scale_relative_error',.2)]:
            with self.subTest(field=field,value=value):
                previous=copy.deepcopy(self.plan['geometry']);self.plan['geometry'][field]=value
                result=self.measure('excluded-'+str(len(list(self.root.glob('excluded-*'))))+'.json')
                self.assertEqual(result['status'],'excluded');self.assertIsNone(result['features'])
                self.plan['geometry']=previous

    def test_scale_or_pose_change_creates_separate_comparison_group(self):
        original=self.measure('one.json');self.plan['geometry']['pixels_per_mm']=20.
        other=self.measure('two.json');self.assertNotEqual(original['comparison_group'],other['comparison_group'])
        self.assertNotEqual(original['physical_offset_mm'],other['physical_offset_mm'])
        self.plan['geometry']['pose_revision']='pose-2';third=self.measure('three.json')
        self.assertNotEqual(other['comparison_group'],third['comparison_group'])

    def test_changed_media_or_artifact_hash_is_rejected_without_output(self):
        self.api();self.plan['observation_sha256']='0'*64
        with self.assertRaisesRegex(RecorderError,'hash'):self.measure()
        self.assertFalse((self.root/'texture.json').exists())
        self.plan['observation_sha256']=hashlib.sha256((self.root/self.plan['observation_artifact']).read_bytes()).hexdigest()
        from PIL import Image
        Image.new('RGB',(16,16),(30,40,50)).save(self.root/'image.png')
        with self.assertRaisesRegex(RecorderError,'media'):self.measure()
        self.assertFalse((self.root/'texture.json').exists())

    def test_existing_colour_feature_mismatch_cannot_supply_texture(self):
        self.api();path=self.root/self.plan['observation_artifact'];d=json.loads(path.read_text());d['features']['rgb_median']=[1,2,3]
        self.save(path.name,d);self.plan['observation_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(RecorderError,'colour features'):self.measure()

    def test_excess_clipping_is_excluded_after_reverified_pixels(self):
        from PIL import Image
        Image.new('RGB',(16,16),(255,255,255)).save(self.root/'image.png');self.recollect()
        result=self.measure();self.assertEqual(result['status'],'excluded')
        self.assertIn('clipped_skin_fraction_above_limit',result['reasons'])
        self.assertIsNone(result['features'])

    def test_versioned_output_and_guard_failure_do_not_overwrite_or_publish(self):
        self.measure();before=(self.root/'texture.json').read_bytes()
        with self.assertRaisesRegex(RecorderError,'already exists'):self.measure()
        self.assertEqual(before,(self.root/'texture.json').read_bytes())
        def stop():raise RecorderError('budget exhausted')
        with self.assertRaisesRegex(RecorderError,'budget'):
            self.api().collect_texture(self.root/'texture-plan.json',self.root/'failed.json',guard=stop)
        self.assertFalse((self.root/'failed.json').exists())

    def test_cli_runs_only_on_declared_host_and_preserves_unpromoted_status(self):
        import platform
        self.api();self.save('texture-plan.json',self.plan)
        command=[sys.executable,'-B','-m','behavior_recorder.appearance_texture','--plan',str(self.root/'texture-plan.json'),
                 '--output',str(self.root/'cli-texture.json'),'--execution-host',platform.node()]
        result=subprocess.run(command,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        payload=json.loads(result.stdout);self.assertEqual(payload['status'],'measured')
        self.assertFalse(payload['actual_model_fit']);self.assertEqual(payload['preflight']['gpu_allocation_bytes'],0)

    def test_wrong_execution_host_rejects_before_creating_texture_output(self):
        self.api();self.save('texture-plan.json',self.plan)
        command=[sys.executable,'-B','-m','behavior_recorder.appearance_texture','--plan',str(self.root/'texture-plan.json'),
                 '--output',str(self.root/'wrong-host.json'),'--execution-host','definitely-not-this-host']
        result=subprocess.run(command,capture_output=True,text=True,timeout=15)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('declared execution host',result.stderr)
        self.assertFalse((self.root/'wrong-host.json').exists())
