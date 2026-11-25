"""Sparse instance supervision with explicit ownership and candidate ranking.

Best-candidate mask supervision follows SAM2's multimask training principle.
The ranking target uses sparse clicks, so predicted scores are not dense-mask IoU.
"""
import torch
from torch.nn import functional as F

from behavior_recorder.core import require
from scripts.instance_click_loss import sparse_click_loss


def instance_separation_loss(masks, scores, points, labels, other):
    require(masks.ndim==3 and len(masks)>0,'Invalid candidate masks')
    require(scores.ndim==1 and len(scores)==len(masks) and bool(torch.isfinite(scores).all()),'Invalid candidate scores')
    require(labels.ndim==1 and other.shape==labels.shape and other.dtype==torch.bool,'Invalid ownership shape/type')
    require(bool(((labels==0)|(labels==1)).all()) and not bool((other&(labels!=0)).any()),'Invalid ownership label')
    require(bool((labels==1).any()) and bool((labels==0).any()),'Foreground and background supervision required')
    groups=[(labels==1,1.),((labels==0)&~other,2.),(other,2.)]
    losses=[]
    for mask in masks:
        pieces=[];weights=[]
        for selected,weight in groups:
            if bool(selected.any()):
                pieces.append(sparse_click_loss(mask,points[selected],labels[selected])*weight)
                weights.append(weight)
        losses.append(torch.stack(pieces).sum()/sum(weights))
    candidate_losses=torch.stack(losses)
    best=int(candidate_losses.detach().argmin())
    ranking=[]
    detached=candidate_losses.detach()
    for better in range(len(masks)):
        for worse in range(len(masks)):
            if float(detached[worse]-detached[better])>.1:
                ranking.append(F.relu(.05+scores[worse]-scores[better]))
    ranking_loss=torch.stack(ranking).mean() if ranking else scores.sum()*0
    return dict(loss=candidate_losses[best]+.5*ranking_loss,mask_loss=candidate_losses[best],
                ranking_loss=ranking_loss,candidate_losses=candidate_losses,best_index=best)
