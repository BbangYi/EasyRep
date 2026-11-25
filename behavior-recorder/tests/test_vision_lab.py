import copy
from datetime import datetime, timedelta, timezone
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from behavior_recorder.analysis_features import fingerprint
from behavior_recorder.behavior_windows import compare_contexts, compare_windows, evaluate_reviewed_windows, fit_reference, fit_reference_bank, window_observations
from behavior_recorder.core import RecorderError, atomic_json, digest, read_json
from behavior_recorder.vision_lab import Handler, Lab, ROOT, ThreadingHTTPServer


def example_rows():
    return [{"offset_seconds": i / 10, "status": "observed", "track_id": 1, "center": [0.3+i/1000,0.5],
             "zone": "middle", "speed_diagonals_per_second": 0.01 if i else None} for i in range(100)]


def examples():
    summary = {"model_id":"test-model", "source":{"duration_seconds":10,"sha256":"source-a","provenance":"real_camera"},
               "config":{"max_gap_seconds":0.6,"zones":{"middle":[0,0,1,1]}}}
    context = {"animal_id":"one","camera_revision":"front1","conditions":"night",
               "captured_at":"2026-10-01T21:00:00+09:00"}
    return summary, context


def normal_windows(day, count=10):
    summary, context = examples()
    windows=[]
    for i in range(count):
        context = {**context, "captured_at":f"2026-10-{day:02d}T21:{i:02d}:00+09:00", "recording_id":f"recording-{day}"}
        summary = copy.deepcopy(summary)
        summary["source"]["sha256"] = f"source-{day}-{i}"
        row=window_observations(summary, example_rows(), context, window_seconds=10)["windows"][0]
        row.update(assessment="normal",reviewer="Test reviewer",review_method="human",run_id=f"run-{day}-{i}")
        windows.append(row)
    return windows


class BehaviorWindowTests(unittest.TestCase):
    def test_time_weighting_does_not_fill_gaps_or_tail(self):
        summary,context=examples()
        window=window_observations(summary,example_rows(),context,window_seconds=10)["windows"][0]
        self.assertAlmostEqual(window["coverage"],0.99)
        self.assertAlmostEqual(window["zone_observed_seconds"]["middle"],9.9)
        rows=example_rows()
        for r in rows[25:75]:
            r.update(status="no_confident_track",center=None,zone=None,speed_diagonals_per_second=None)
        window=window_observations(summary,rows,context,window_seconds=10)["windows"][0]
        self.assertLess(window["coverage"],0.5)
        self.assertEqual(window["quality"],"insufficient_observation")
        self.assertEqual(compare_windows([window])["windows"][0]["reason"],"insufficient_observation")

    def test_duplicate_timestamps_and_nonfinite_features_rejected(self):
        summary,context=examples();rows=example_rows();rows[1]["offset_seconds"]=0
        with self.assertRaisesRegex(RecorderError,"increase"):
            window_observations(summary,rows,context)
        rows=example_rows();rows[0]["center"][0]=float('nan')
        with self.assertRaises(RecorderError):window_observations(summary,rows,context)

    def test_short_video_tail_reports_duration_instead_of_tracking_loss(self):
        summary, context = examples()
        summary['source']['duration_seconds'] = 8
        rows = example_rows()[:80]
        windows = window_observations(summary, rows, context, window_seconds=5)['windows']
        self.assertEqual(windows[0]['quality'], 'usable')
        self.assertGreater(windows[1]['coverage'], 0.9)
        self.assertEqual(windows[1]['quality'], 'insufficient_observation')
        self.assertEqual(windows[1]['quality_reason'], 'short_window')
        self.assertEqual(compare_windows(windows)['windows'][1]['reason'], 'insufficient_observation')

    def test_guided_reference_context_ignores_video_seed_but_separates_automatic_mode(self):
        summary, context = examples()
        automatic = window_observations(summary, example_rows(), context, window_seconds=10)['windows'][0]
        summary['config']['target_seed'] = {'source_sha256':'a'*64, 'xyxy':[0.1,0.1,0.6,0.7]}
        guided = window_observations(summary, example_rows(), context, window_seconds=10)['windows'][0]
        summary['config']['target_seed'] = {'source_sha256':'b'*64, 'xyxy':[0.2,0.3,0.8,0.9]}
        another = window_observations(summary, example_rows(), context, window_seconds=10)['windows'][0]
        self.assertEqual(guided['scope'], another['scope'])
        self.assertNotEqual(automatic['scope'], guided['scope'])
        self.assertEqual(guided['scope']['target_selection_mode'], 'initial_box_guided')
        self.assertNotIn('target_seed', guided['scope']['tracking_config'])

    def test_reference_requires_human_camera_context_and_separate_dates(self):
        refs=normal_windows(1)+normal_windows(2)
        cal=normal_windows(3)+normal_windows(4)
        for change,pattern in [({"reviewer":None},"human-reviewed"),({"review_method":"assistant"},"human-reviewed"),({"provenance":"public_real"},"own camera"),
                               ({"quality":"insufficient_observation"},"insufficient observation")]:
            altered=copy.deepcopy(refs);altered[0].update(change)
            with self.assertRaisesRegex(RecorderError,pattern):fit_reference(altered,cal)
        altered=copy.deepcopy(cal);altered[0]["recording_id"]=refs[0]["recording_id"]
        with self.assertRaisesRegex(RecorderError,"overlap"):fit_reference(refs,altered)
        with self.assertRaisesRegex(RecorderError,"20 reference"):fit_reference(refs[:10],cal)

    def test_contextual_neighbors_change_and_persistence(self):
        refs=normal_windows(1)+normal_windows(2);cal=normal_windows(3)+normal_windows(4)
        model=fit_reference(refs,cal)
        query=normal_windows(5,1)[0]
        within=compare_windows([query],model)["windows"][0]
        self.assertEqual(within["status"],"within_reference")
        self.assertEqual(len(within["neighbors"]),3)
        query["features"]["speed"]=0.15
        next_window=copy.deepcopy(query);next_window.update(start_seconds=10,end_seconds=20,window_id="second")
        result=compare_windows([query,next_window],model)
        self.assertEqual(result["windows"][0]["status"],"change_candidate")
        self.assertEqual(len(result["events"]),1)
        self.assertFalse(result["field_validated"])
        next_window["start_seconds"]=11
        self.assertEqual(compare_windows([query,next_window],model)["events"],[])

    def test_reused_sources_changed_context_and_missing_baseline_abstain(self):
        refs=normal_windows(1)+normal_windows(2);model=fit_reference(refs,normal_windows(3)+normal_windows(4))
        self.assertEqual(compare_windows([refs[0]],model)["windows"][0]["reason"],"reference_data_reuse")
        query=normal_windows(5,1)[0];query["scope"]["conditions"]="day"
        self.assertEqual(compare_windows([query],model)["windows"][0]["reason"],"context_mismatch")
        self.assertEqual(compare_windows([query])["windows"][0]["reason"],"no_reviewed_reference")
        model["threshold"]+=1
        with self.assertRaisesRegex(RecorderError,"integrity"):compare_windows([query],model)

    def test_reference_bank_keeps_unready_contexts_separate(self):
        refs=normal_windows(1)+normal_windows(2);cal=normal_windows(3)+normal_windows(4)
        for row in refs:row['partition']='reference'
        for row in cal:row['partition']='calibration'
        incomplete=copy.deepcopy(refs[0]);incomplete['scope']['conditions']='mist'
        bank=fit_reference_bank(refs+cal+[incomplete])
        self.assertEqual(len(bank['models']),1)
        self.assertEqual(len(bank['pending']),1)
        self.assertEqual(len(bank['reviewed_window_ids']),40)
        query=normal_windows(5,1)[0];changed=copy.deepcopy(query)
        changed['scope']['conditions']='mist'
        result=compare_contexts([query,changed],bank)
        self.assertEqual(result['windows'][0]['status'],'within_reference')
        self.assertEqual(result['windows'][1]['reason'],'no_reviewed_reference')
        bank['pending']=[]
        with self.assertRaisesRegex(RecorderError,'integrity'):compare_contexts([query],bank)

    def test_evaluation_includes_missed_anomalies_and_excludes_training_data(self):
        refs=normal_windows(1)+normal_windows(2);cal=normal_windows(3)+normal_windows(4)
        for row in refs:row['partition']='reference'
        for row in cal:row['partition']='calibration'
        bank=fit_reference_bank(refs+cal)
        queries=normal_windows(5,4)
        for row in queries:row['partition']='evaluation'
        queries[0]['assessment']='anomaly';queries[0]['features']['speed']=0.2
        queries[1]['assessment']='anomaly';queries[1]['quality']='insufficient_observation'
        queries[2]['features']['speed']=0.2
        leaked={**refs[0],'partition':'evaluation'}
        report=evaluate_reviewed_windows(queries+[queries[0],leaked],bank)
        self.assertEqual(report['reviewed_windows'],5)
        self.assertEqual(report['excluded_windows'],1)
        self.assertEqual(report['true_positive'],1)
        self.assertEqual(report['false_positive'],1)
        self.assertEqual(report['false_negative'],1)
        self.assertEqual(report['true_negative'],1)
        self.assertEqual(report['abstentions'],1)
        self.assertEqual(report['recall'],0.5)
        self.assertEqual(report['decision_coverage'],0.75)
        no_model=evaluate_reviewed_windows(queries)
        self.assertIsNone(no_model['recall'])
        self.assertFalse(no_model['reference_available'])


class LabStoreTests(unittest.TestCase):
    def test_visual_memory_report_registers_only_workspace_media(self):
        with tempfile.TemporaryDirectory() as temporary, patch('behavior_recorder.vision_lab.MODELS', {}):
            root = Path(temporary).resolve()
            lab = Lab(root / 'lab', load_catalog=False)
            self.assertIsNone(lab.visual_memory_check())
            (root / 'review.mp4').write_bytes(b'video fixture')
            report = {'schema_version': 1, 'cases': [{'variants': {'automatic': {'video_file': 'review.mp4'}}}]}
            atomic_json(lab.storage / 'visual-memory-check.json', report)
            with patch('behavior_recorder.vision_lab.ROOT', root):
                loaded = lab.visual_memory_check()
                url = loaded['cases'][0]['variants']['automatic']['video']
                self.assertEqual(lab.assets[url.rsplit('/', 1)[1]], root / 'review.mp4')
                self.assertEqual(read_json(lab.storage / 'visual-memory-check.json'), report)
                report['cases'][0]['variants']['automatic']['video_file'] = '../outside.mp4'
                atomic_json(lab.storage / 'visual-memory-check.json', report)
                with self.assertRaises(RecorderError):
                    lab.visual_memory_check()

    def test_job_uses_selected_detector_target(self):
        with tempfile.TemporaryDirectory() as temporary, patch('behavior_recorder.vision_lab.MODELS', {}):
            root = Path(temporary)
            lab = Lab(root, load_catalog=False)
            lab.models = [{'key': 'public_lizard', 'model_id': 'generic-model', 'species': 'lizard'}]
            atomic_json(root / 'uploads/test.json', {'sha256': 'a'*64, 'name': 'test.mp4', 'suffix': '.mp4'})
            job = lab.create_job({'upload_id': 'test', 'model': 'public_lizard', 'provenance': 'synthetic_test', 'context': {}})
            self.assertEqual(job['tracking_config']['species'], 'lizard')

    def test_compared_models_persist_the_evaluated_tracking_settings(self):
        with tempfile.TemporaryDirectory() as temporary, patch('behavior_recorder.vision_lab.MODELS', {}):
            root = Path(temporary)
            lab = Lab(root, load_catalog=False)
            lab.models = [{'key': key, 'model_id': key, 'species': 'lizard'}
                          for key in ['warm_lizard', 'captive_diversity', 'public_lizard']]
            atomic_json(root / 'uploads/test.json', {'sha256': 'a'*64, 'name': 'test.mp4', 'suffix': '.mp4'})
            for key in ['warm_lizard', 'captive_diversity']:
                with self.subTest(model=key):
                    job = lab.create_job({'upload_id': 'test', 'model': key,
                                          'provenance': 'synthetic_test', 'context': {}})
                    config = read_json(root / 'jobs' / job['id'] / 'job.json')['tracking_config']
                    self.assertEqual(config['sample_fps'], 3)
                    self.assertEqual(config['inference_image_size'], 640)
                    self.assertEqual(config['inference_slicing'], 'off')
                    self.assertEqual((config['confidence'], config['nms_iou']), (0.4, 0.5))
                    self.assertEqual(config['species'], 'lizard')
            legacy = lab.create_job({'upload_id': 'test', 'model': 'public_lizard',
                                     'provenance': 'synthetic_test', 'context': {}})
            self.assertEqual(legacy['tracking_config']['sample_fps'], 6)

    def test_manual_target_is_bound_to_uploaded_source_and_retained_on_retry(self):
        with tempfile.TemporaryDirectory() as temporary, patch('behavior_recorder.vision_lab.MODELS',{}):
            root=Path(temporary);lab=Lab(root,load_catalog=False)
            lab.models=[{'key':'baseline','model_id':'test-model'}]
            atomic_json(root/'uploads/test.json',{'sha256':'a'*64,'name':'test.mp4','suffix':'.mp4'})
            request={'upload_id':'test','model':'baseline','provenance':'synthetic_test','context':{},'target_box':[0.1,0.2,0.6,0.7]}
            first=lab.create_job(request)
            self.assertEqual(first['tracking_config']['target_seed'],{'source_sha256':'a'*64,'xyxy':request['target_box']})
            lab.jobs[first['id']]['state']='failed'
            retry=lab.retry_job(first['id'])
            self.assertEqual(retry['target_box'],request['target_box'])
            with self.assertRaises(RecorderError):lab.create_job({**request,'target_box':[0.9,0,0.2,1]})

    def test_extended_gallery_does_not_reuse_predictions_with_changed_labels(self):
        with tempfile.TemporaryDirectory() as temporary, patch('behavior_recorder.vision_lab.MODELS',{}):
            lab=Lab(Path(temporary),load_catalog=False)
            record={'id':'image','image_sha256':'image-hash','label_sha256':'label-hash','group_id':'group','split':'train'}
            old={'dataset_id':'old','records':[record]}
            changed={'dataset_id':'new','records':[{**record,'label_sha256':'changed'}]}
            with patch('behavior_recorder.vision_lab.load_dataset',side_effect=[old,changed]), patch.object(Path,'exists',return_value=True):
                with self.assertRaisesRegex(RecorderError,'changes an earlier'):
                    lab.make_catalog()

    def test_duplicate_jobs_recovery_and_input_path_validation(self):
        with tempfile.TemporaryDirectory() as temporary, patch('behavior_recorder.vision_lab.MODELS',{}):
            root=Path(temporary);lab=Lab(root,load_catalog=False)
            lab.models=[{"key":"baseline", "model_id":"test-model"}]
            atomic_json(root/'uploads/test.json',{"sha256":"x","name":"test.mp4","suffix":".mp4"})
            request={"upload_id":"test","model":"baseline","provenance":"synthetic_test","context":{}}
            first=lab.create_job(request)
            self.assertEqual(first["id"],lab.create_job(request)["id"])
            self.assertEqual(first['tracking_config']['track_lost_seconds'],1.0)
            # Previously completed jobs must not satisfy a new tracking recipe.
            changed=copy.deepcopy(first['tracking_config']);changed['track_lost_seconds']=0.5
            original_read=read_json
            def recipe_read(path,*args,**kwargs):
                return changed if path.name=='vision.tracking.json' else original_read(path,*args,**kwargs)
            with patch('behavior_recorder.vision_lab.read_json',side_effect=recipe_read):
                different=lab.create_job(request)
            self.assertNotEqual(first['id'],different['id'])
            recovered=Lab(root,load_catalog=False)
            self.assertEqual(recovered.jobs[first["id"]]["state"],"interrupted")
            recovered.models=lab.models
            retry=recovered.retry_job(first['id'])
            self.assertNotEqual(first['id'],retry['id'])
            self.assertEqual(retry['model_id'],'test-model')
            with self.assertRaises(RecorderError):lab.create_job({**request,"upload_id":"../../private"})
            with self.assertRaises(RecorderError):lab.create_job({**request,"model":"user-provided-checkpoint"})
            with self.assertRaises(RecorderError):lab.create_job({**request,"zones":{"outside":[0.9,0,1,1]}})

    def test_review_history_does_not_mutate_features(self):
        with tempfile.TemporaryDirectory() as temporary, patch('behavior_recorder.vision_lab.MODELS',{}):
            lab=Lab(Path(temporary),load_catalog=False)
            fake={"state":"complete","features":{"windows":[{"window_id":"window1"}]}}
            with patch.object(lab,'job_detail',return_value=fake):
                record=lab.review({"job_id":"job1","window_id":"window1","assessment":"normal",
                                   "reviewer":"Human","review_method":"human","partition":"evaluation"})
            self.assertEqual(record["partition"],"evaluation")
            self.assertIsNone(lab.reference)
            self.assertEqual(len(list((Path(temporary)/'review-history').glob('*.json'))),1)

    def test_behavior_review_keeps_an_auditable_active_human_label(self):
        with tempfile.TemporaryDirectory() as temporary, patch('behavior_recorder.vision_lab.MODELS',{}):
            lab = Lab(Path(temporary), load_catalog=False)
            window = {"window_id": "window1", "start_seconds": 10.0, "end_seconds": 20.0,
                      "quality": "usable", "source_sha256": "source-a", "recording_id": "recording-a",
                      "scope": {"animal_id": "crested-01"}}
            fake = {"id": "job1", "state": "complete", "features": {"windows": [window]}}
            with patch.object(lab, 'job_detail', return_value=fake):
                record = lab.behavior_review({"job_id": "job1", "window_id": "window1",
                                              "behavior": "moving", "visibility": "visible",
                                              "certainty": "certain", "reviewer": "Human"})
            self.assertEqual(record["behavior"], "moving")
            self.assertEqual(record["clip_id"], "job1")
            self.assertEqual(record["animal_id"], "crested-01")
            self.assertEqual(len(list((Path(temporary) / 'behavior-review-history').glob('*.json'))), 1)
            self.assertEqual(lab.behavior_labels()["labels"][0]["behavior"], "moving")
            with patch.object(lab, 'job_detail', return_value=fake):
                with self.assertRaisesRegex(RecorderError, "fully visible"):
                    lab.behavior_review({"job_id": "job1", "window_id": "window1",
                                         "behavior": "resting", "visibility": "partial",
                                         "certainty": "certain", "reviewer": "Human"})

    def test_behavior_review_requires_unobservable_for_withheld_tracking(self):
        with tempfile.TemporaryDirectory() as temporary, patch('behavior_recorder.vision_lab.MODELS',{}):
            lab = Lab(Path(temporary), load_catalog=False)
            window = {"window_id": "window1", "start_seconds": 10.0, "end_seconds": 20.0,
                      "quality": "insufficient_observation", "scope": {"animal_id": "crested-01"}}
            fake = {"id": "job1", "state": "complete", "features": {"windows": [window]}}
            with patch.object(lab, 'job_detail', return_value=fake):
                with self.assertRaisesRegex(RecorderError, "unobservable"):
                    lab.behavior_review({"job_id": "job1", "window_id": "window1",
                                         "behavior": "moving", "visibility": "visible",
                                         "certainty": "certain", "reviewer": "Human"})

    def test_job_detail_exposes_only_the_active_behavior_review(self):
        with tempfile.TemporaryDirectory() as temporary, patch('behavior_recorder.vision_lab.MODELS',{}):
            lab = Lab(Path(temporary), load_catalog=False)
            job = {"id": "job1", "state": "complete", "source_sha256": "source-a"}
            lab.jobs[job["id"]] = job
            run = lab.storage / "jobs" / job["id"]
            run.mkdir()
            (run / "analysis").mkdir()
            atomic_json(run / "analysis" / "summary.json", {"model_id": "test-model"})
            (run / "analysis" / "observations.jsonl").write_text("")
            (run / "review-browser.mp4").write_bytes(b"browser video")
            atomic_json(run / "features.json", {"windows": [{"window_id": "window1", "quality": "usable"}]})
            lab.behavior_reviews[lab.behavior_review_key("job1", "window1")] = {"behavior": "moving", "label_id": "label1"}
            with patch('behavior_recorder.vision_lab.compare_contexts', return_value={"windows": []}):
                detail = lab.job_detail("job1")
            self.assertEqual(detail["features"]["windows"][0]["behavior_review"]["behavior"], "moving")

    def test_corrected_review_invalidates_active_reference(self):
        with tempfile.TemporaryDirectory() as temporary, patch('behavior_recorder.vision_lab.MODELS',{}):
            lab=Lab(Path(temporary),load_catalog=False)
            lab.reference={'reviewed_window_ids':['window1']}
            atomic_json(lab.storage/'active-reference.json',lab.reference)
            fake={'state':'complete','features':{'windows':[{'window_id':'window1'}]}}
            with patch.object(lab,'job_detail',return_value=fake):
                record=lab.review({'job_id':'job1','window_id':'window1','assessment':'detection_error',
                                   'reviewer':'Human','review_method':'human','partition':'evaluation'})
            self.assertTrue(record['reference_invalidated'])
            self.assertIsNone(lab.reference)
            self.assertFalse((lab.storage/'active-reference.json').exists())

    def test_camera_inbox_hash_validation_idempotency_and_bad_file_isolation(self):
        with tempfile.TemporaryDirectory() as temporary, patch('behavior_recorder.vision_lab.MODELS',{}):
            base=Path(temporary);inbox=base/'inbox';inbox.mkdir()
            source=inbox/'clip.mp4';source.write_bytes(b'Finalized producer bytes; decode is a separate job')
            config=read_json(ROOT/'examples/config.test.json')
            config['input']['inbox']='inbox';config['animals'][0]['species']='crested_gecko'
            config_path=base/'camera.json';atomic_json(config_path,config)
            descriptor={'schema_version':1,'input_id':'one','camera_id':'rgb-01','file':'clip.mp4',
                        'sha256':digest(source),'recording_id':'recording-one','sequence':0,
                        'provenance':'synthetic_test','captured_at':None,
                        'capture_clock':{'source':'unknown','accuracy_ms':None},
                        'placement_revision':None,'calibration_revision':None}
            atomic_json(inbox/'z-good.capture.json',descriptor)
            atomic_json(inbox/'a-bad.capture.json',{**descriptor,'sha256':'0'*64})
            lab=Lab(base/'lab',load_catalog=False,watch_config=config_path,conditions='test')
            lab.models=[{'key':'baseline','model_id':'test-model'}]
            lab.scan_inbox()
            self.assertEqual(len(lab.jobs),1)
            self.assertEqual(lab.watch_state['pending_file_errors'],1)
            self.assertEqual(lab.watch_state['mode'],'finalized_file')
            lab.scan_inbox();self.assertEqual(len(lab.jobs),1)
            copied=next((lab.storage/'uploads').glob('*.mp4'))
            self.assertEqual(digest(copied),digest(source))
            bad={**descriptor,'file':'../outside.mp4'}
            atomic_json(inbox/'escape.capture.json',bad)
            with self.assertRaises(RecorderError):lab.enqueue_descriptor(inbox/'escape.capture.json',config,'test')


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        with patch('behavior_recorder.vision_lab.MODELS',{}):
            self.lab=Lab(Path(self.temp.name),load_catalog=False)
        try:self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        except PermissionError:
            self.temp.cleanup();self.skipTest('loopback sockets unavailable in sandbox')
        self.server.lab=self.lab;self.server.daemon_threads=True
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        if hasattr(self,'server'):
            self.server.shutdown();self.server.server_close();self.thread.join()
        self.temp.cleanup()

    def request(self,method,path,body=None,headers=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        try:
            connection.request(method,path,body,headers or {})
            response=connection.getresponse()
            return response.status,response.read()
        finally:
            connection.close()

    def test_cross_origin_requests_and_mutations_without_token_fail(self):
        status,body=self.request('GET','/api/state');self.assertEqual(status,200)
        self.assertFalse(json.loads(body)['camera_connected'])
        self.assertEqual(self.request('GET','/api/state',headers={'Origin':'https://example.org'})[0],400)
        self.assertEqual(self.request('GET','/api/state',headers={'Host':'attacker.example'})[0],400)
        self.assertEqual(self.request('POST','/api/reference',b'{}',{'Content-Type':'application/json'})[0],400)

    def test_media_allowlist_and_byte_ranges(self):
        media=Path(self.temp.name)/'example.mp4';media.write_bytes(b'0123456789')
        url=self.lab.asset(media)
        self.assertEqual(self.request('GET',url,headers={'Range':'bytes=2-5'}),(206,b'2345'))
        self.assertEqual(self.request('GET',url,headers={'Range':'bytes=30-'})[0],416)
        self.assertEqual(self.request('GET','/media/../private')[0],400)

    def test_disconnected_response_does_not_break_following_requests(self):
        with patch.object(Handler,'send',side_effect=BrokenPipeError('browser cancelled response')):
            with self.assertRaises(http.client.RemoteDisconnected):self.request('GET','/api/state')
        self.assertEqual(self.request('GET','/api/state')[0],200)


if __name__=='__main__':unittest.main()
