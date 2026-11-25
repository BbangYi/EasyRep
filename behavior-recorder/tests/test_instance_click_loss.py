import unittest

import torch

from behavior_recorder.core import RecorderError
from scripts.instance_click_loss import sparse_click_loss


class InstanceClickLossTests(unittest.TestCase):
    def test_image_edge_coordinates_sample_correct_pixels_and_backpropagate(self):
        logits=torch.tensor([[4.,-4.],[-4.,4.]],requires_grad=True)
        points=torch.tensor([[0.,0.],[1.,0.],[0.,1.],[1.,1.]])
        labels=torch.tensor([1,0,0,1])
        loss=sparse_click_loss(logits,points,labels)
        self.assertAlmostEqual(float(loss.detach()),float(torch.nn.functional.softplus(torch.tensor(-4.))),places=6)
        loss.backward()
        self.assertTrue(bool(torch.isfinite(logits.grad).all()))
        self.assertTrue(bool((logits.grad.abs()>0).all()))

    def test_repeating_background_clicks_does_not_overweight_background(self):
        logits=torch.tensor([[1.,2.],[3.,4.]],requires_grad=True)
        small=sparse_click_loss(logits,torch.tensor([[.25,.25],[.75,.75]]),torch.tensor([1,0]))
        repeated=sparse_click_loss(logits,torch.tensor([[.25,.25],[.75,.75],[.75,.75],[.75,.75]]),torch.tensor([1,0,0,0]))
        self.assertAlmostEqual(float(small.detach()),float(repeated.detach()),places=6)

    def test_empty_out_of_range_and_nonbinary_clicks_are_rejected(self):
        logits=torch.zeros((4,4))
        for points,labels in [(torch.empty((0,2)),torch.empty(0)),
                              (torch.tensor([[1.1,0.]]),torch.tensor([1])),
                              (torch.tensor([[float('nan'),0.]]),torch.tensor([1])),
                              (torch.tensor([[.5,.5]]),torch.tensor([2]))]:
            with self.assertRaises(RecorderError):sparse_click_loss(logits,points,labels)


if __name__=='__main__':unittest.main()
