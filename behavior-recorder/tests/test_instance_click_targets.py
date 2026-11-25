import unittest

from behavior_recorder.core import RecorderError
from scripts.instance_click_targets import build_instance_click_targets


class InstanceClickTargetsTests(unittest.TestCase):
    def test_input_anchor_is_excluded_and_other_instance_is_negative(self):
        instances=[[[.2,.2,1],[.3,.3,1],[.9,.9,0]],
                   [[.7,.7,1],[.8,.8,1],[.1,.9,0]]]
        rows=build_instance_click_targets(instances,[[10,10,30,30],[60,60,80,80]],100,100)
        self.assertEqual(rows[0]['anchor_publisher_click_index'],0)
        self.assertEqual([(c['publisher_click_index'],c['label']) for c in rows[0]['supervision_clicks'] if c['kind']=='publisher'],[(1,1),(2,0)])
        self.assertEqual(sum(c['kind']=='other_instance' for c in rows[0]['supervision_clicks']),2)
        self.assertTrue(all(c['label']==0 for c in rows[0]['supervision_clicks'] if c['kind']=='other_instance'))

    def test_conflicting_and_explicitly_excluded_clicks_never_become_negatives(self):
        instances=[[[.2,.2,1],[.4,.4,1],[.9,.9,0]],
                   [[.201,.201,1],[.7,.7,1],[.8,.8,1],[.1,.9,0]]]
        rows=build_instance_click_targets(instances,[[10,10,30,30],[60,60,80,80]],100,100,excluded_clicks={(1,2)})
        negatives=[c for c in rows[0]['supervision_clicks'] if c['kind']=='other_instance']
        self.assertEqual([c['source_publisher_click_index'] for c in negatives],[1])
        self.assertEqual(rows[0]['ambiguous_other_clicks_excluded'],1)
        self.assertFalse(any(c.get('publisher_click_index')==2 for c in rows[1]['supervision_clicks']))

    def test_insufficient_foreground_is_not_admitted_and_invalid_coordinates_fail(self):
        rows=build_instance_click_targets([[[.2,.2,1],[.9,.9,0]]],[[10,10,30,30]],100,100)
        self.assertIsNone(rows[0])
        for clicks in [[[1.1,.2,1],[.3,.3,1],[.9,.9,0]],[[.2,.2,2]]]:
            with self.assertRaises(RecorderError):build_instance_click_targets([clicks],[[10,10,30,30]],100,100)


if __name__=='__main__':unittest.main()
