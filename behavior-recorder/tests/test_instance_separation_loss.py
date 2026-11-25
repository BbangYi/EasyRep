import unittest

import torch

from behavior_recorder.core import RecorderError
from scripts.instance_separation_loss import instance_separation_loss


class InstanceSeparationLossTests(unittest.TestCase):
    def test_only_best_mask_receives_segmentation_gradient_and_scores_learn_order(self):
        masks=torch.tensor([[[4.,-4.],[-4.,-4.]],[[-4.,4.],[4.,4.]]],requires_grad=True)
        scores=torch.tensor([.2,.8],requires_grad=True)
        result=instance_separation_loss(masks,scores,torch.tensor([[0.,0.],[1.,0.],[0.,1.]]),torch.tensor([1,0,0]),torch.tensor([False,False,True]))
        self.assertEqual(result['best_index'],0)
        result['loss'].backward()
        self.assertGreater(float(masks.grad[0].abs().sum()),0)
        self.assertEqual(float(masks.grad[1].abs().sum()),0)
        self.assertLess(float(scores.grad[0]),0)
        self.assertGreater(float(scores.grad[1]),0)

    def test_repeated_background_points_do_not_dilute_other_instance_penalty(self):
        masks=torch.tensor([[[4.,-4.],[4.,-4.]]])
        def run(repeats):
            points=torch.tensor([[0.,0.]]+[[1.,0.]]*repeats+[[0.,1.]])
            labels=torch.tensor([1]+[0]*(repeats+1))
            other=torch.tensor([False]*(repeats+1)+[True])
            return instance_separation_loss(masks,torch.tensor([.5]),points,labels,other)
        a,b=run(1),run(30)
        self.assertAlmostEqual(float(a['loss']),float(b['loss']),places=6)
        expected=(torch.nn.functional.softplus(torch.tensor(-4.))*3+torch.nn.functional.softplus(torch.tensor(4.))*2)/5
        self.assertAlmostEqual(float(a['mask_loss']),float(expected),places=6)
        self.assertEqual(float(a['ranking_loss']),0)

    def test_equal_quality_masks_do_not_invent_a_ranking_target(self):
        masks=torch.zeros((2,2,2),requires_grad=True);scores=torch.tensor([.1,.9],requires_grad=True)
        result=instance_separation_loss(masks,scores,torch.tensor([[0.,0.],[1.,1.]]),torch.tensor([1,0]),torch.tensor([False,False]))
        self.assertEqual(float(result['ranking_loss']),0)

    def test_invalid_ownership_shapes_and_nonfinite_scores_fail(self):
        args=[torch.zeros((2,2,2)),torch.tensor([.2,.8]),torch.tensor([[0.,0.],[1.,1.]]),torch.tensor([1,0]),torch.tensor([False,False])]
        for index,value in [(4,torch.tensor([True,False])),(1,torch.tensor([float('nan'),.8])),(1,torch.tensor([.2])),(4,torch.tensor([0,0]))]:
            bad=list(args);bad[index]=value
            with self.assertRaises(RecorderError):instance_separation_loss(*bad)


if __name__=='__main__':unittest.main()
