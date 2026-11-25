"""Class-balanced supervision at human instance clicks, without raster rounding."""
import torch
from torch.nn import functional as F

from behavior_recorder.core import require


def sparse_click_loss(logits, points, labels):
    """Points use image-edge coordinates in [0,1]; bilinear sampling preserves subpixels."""
    require(logits.ndim==2 and min(logits.shape)>1 and bool(torch.isfinite(logits).all()), 'Invalid mask logits')
    require(points.ndim==2 and points.shape[1]==2 and len(points)>0, 'Empty or invalid point shape')
    require(labels.ndim==1 and len(labels)==len(points), 'Point/label count mismatch')
    require(bool(torch.isfinite(points).all()) and bool(((points>=0)&(points<=1)).all()), 'Point outside image')
    require(bool(((labels==0)|(labels==1)).all()), 'Nonbinary click label')
    points=points.to(device=logits.device,dtype=logits.dtype)
    labels=labels.to(device=logits.device)
    sampled=F.grid_sample(logits[None,None],(points*2-1)[None,None],mode='bilinear',
                          padding_mode='border',align_corners=False).reshape(-1)
    pieces=[]
    for label in [0,1]:
        selected=labels==label
        if bool(selected.any()):
            pieces.append(F.binary_cross_entropy_with_logits(sampled[selected],torch.full_like(sampled[selected],float(label))))
    return torch.stack(pieces).mean()
