"""Keep annotation ownership and prompt/target separation explicit."""
import math

from behavior_recorder.core import require


def build_instance_click_targets(instances, boxes, width, height, excluded_clicks=()):
    require(width>0 and height>0 and len(instances)==len(boxes),'Invalid image/instance dimensions')
    excluded=set(excluded_clicks)
    retained=[]
    for slot,clicks in enumerate(instances):
        valid=[]
        for index,click in enumerate(clicks):
            require(len(click)==3,'Invalid click shape')
            x,y,label=click
            require(math.isfinite(x) and math.isfinite(y) and 0<=x<=1 and 0<=y<=1 and label in (0,1),'Invalid publisher click')
            if (slot,index) not in excluded:valid.append((index,x,y,int(label)))
        retained.append(valid)
    require(all(0<=slot<len(instances) and 0<=index<len(instances[slot]) for slot,index in excluded),'Invalid click exclusion')
    rows=[]
    for slot,(clicks,box) in enumerate(zip(retained,boxes)):
        require(len(box)==4 and all(math.isfinite(v) for v in box) and 0<=box[0]<box[2]<=width and 0<=box[1]<box[3]<=height,'Invalid prompt box')
        positive=[c for c in clicks if c[3]==1]
        if len(positive)<2 or not any(c[3]==0 for c in clicks):
            rows.append(None)
            continue
        cx,cy=(box[0]+box[2])/2,(box[1]+box[3])/2
        anchor=min(positive,key=lambda c:((c[1]*width-cx)**2+(c[2]*height-cy)**2,c[0]))
        supervision=[dict(kind='publisher',publisher_click_index=i,x=x,y=y,label=label)
                     for i,x,y,label in clicks if i!=anchor[0]]
        conflicts=0
        for other_slot,other_clicks in enumerate(retained):
            if other_slot==slot:continue
            for i,x,y,label in other_clicks:
                if label!=1:continue
                if any(math.hypot((x-px)*width,(y-py)*height)<=3 for _,px,py,_ in positive):
                    conflicts+=1
                    continue
                supervision.append(dict(kind='other_instance',source_slot=other_slot,
                    source_publisher_click_index=i,x=x,y=y,label=0))
        rows.append(dict(slot=slot,anchor_publisher_click_index=anchor[0],
            anchor_native=[anchor[1]*width,anchor[2]*height],supervision_clicks=supervision,
            ambiguous_other_clicks_excluded=conflicts))
    return rows
