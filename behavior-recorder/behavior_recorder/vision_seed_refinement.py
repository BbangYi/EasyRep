"""Bounded re-segmentation of an automatically detected, possibly partial animal."""
from .core import require
from .vision_benchmark import intersection_over_union
from .vision_sam3 import VERIFIER_THRESHOLD
from .vision_seed import padded_crop


def crop_requests(accepted, details, auxiliary, width, height):
    def intersection(a,b):
        return max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    def area(box):return (box[2]-box[0])*(box[3]-box[1])
    requests=[]
    for index,anchor in enumerate(accepted):
        candidates=[]
        for detail in details:
            proposal=detail['clipped_proposal'];box=proposal['xyxy'];original=anchor['xyxy']
            if not detail['accepted'] or proposal['confidence']<.4 or detail['verifier_score']<VERIFIER_THRESHOLD:
                continue
            if area(box)<=area(original) or intersection(box,original)/area(original)<.8 or intersection_over_union(box,original)>=.5:
                continue
            if any(intersection(box,other['xyxy'])>0 for i,other in enumerate(accepted) if i!=index):
                continue
            if any(intersection(box,other['xyxy'])>0 and intersection_over_union(original,other['xyxy'])<.3
                   and intersection(original,other['xyxy'])/min(area(original),area(other['xyxy']))<.8 for other in auxiliary):
                continue
            candidates.append(dict(object_index=index,primary_prediction_index=detail['prediction_index'],
                                   crop_xyxy=padded_crop(box,width,height,.25)))
        if len(candidates)==1:requests.extend(candidates)
    return requests[:2]


def choose_refinement(original, other_masks, candidates):
    import numpy as np
    require(original.ndim==2 and original.dtype==bool and bool(original.any()),'Invalid seed mask')
    require(all(a.ndim==3 and a.dtype==bool and a.shape[1:]==original.shape for a in [other_masks,candidates]),'Invalid refinement mask geometry/type')
    require(len(other_masks)<=15 and len(candidates)<=16,'Too many refinement masks')
    def box(mask):
        y,x=np.where(mask)
        return [int(x.min()),int(y.min()),int(x.max())+1,int(y.max())+1]
    old_box=box(original);area=int(original.sum());eligible=[];details=[]
    for i,candidate in enumerate(candidates):
        retention=float((candidate&original).sum()/area)
        overlap=int((candidate&other_masks.any(axis=0)).sum()) if len(other_masks) else 0
        new_box=box(candidate) if candidate.any() else None
        grows=bool(new_box and intersection_over_union(old_box,new_box)<.5
                   and (new_box[2]-new_box[0])*(new_box[3]-new_box[1])>(old_box[2]-old_box[0])*(old_box[3]-old_box[1]))
        accepted=retention>=.9 and overlap==0 and grows
        details.append(dict(candidate_index=i,retained_fraction=retention,other_object_pixels=overlap,
                            original_box=old_box,candidate_box=new_box,substantial_extent_growth=grows,eligible=accepted))
        if accepted:eligible.append(i)
    return (eligible[0] if len(eligible)==1 else None),details
