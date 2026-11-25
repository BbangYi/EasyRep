"""Complete-instance selection and bounded remote ZIP reads for Open Images."""
from collections import defaultdict
import io
import math
import re

from behavior_recorder.core import require


def parse_masks(rows):
    result, names = [], set()
    for row in rows:
        image_id, box_id = row['ImageID'], row['BoxID']
        require(re.fullmatch(r'[0-9a-f]{16}', image_id) is not None, 'Invalid image ID')
        require(re.fullmatch(r'[0-9a-f]+', box_id) is not None, 'Invalid box ID')
        name = f'{image_id}_m04m9y_{box_id}.png'
        require(row['LabelName']=='/m/04m9y' and row['MaskPath']==name, 'Unexpected class or unsafe mask path')
        require(name not in names, 'Duplicate mask name')
        names.add(name)
        box = [float(row[key]) for key in ('BoxXMin','BoxYMin','BoxXMax','BoxYMax')]
        require(all(math.isfinite(v) and 0<=v<=1 for v in box), 'Invalid mask starting box')
        require(box[0]<box[2] and box[1]<box[3], 'Empty mask starting box')
        quality = float(row['PredictedIoU']) if row.get('PredictedIoU') else None
        require(quality is None or math.isfinite(quality) and 0<=quality<=1, 'Invalid predicted quality')
        clicks = []
        for click in row.get('Clicks','').split(';'):
            if not click.strip():
                continue
            parts = click.split()
            require(len(parts)==3 and parts[2] in {'0','1'}, 'Invalid annotation click')
            x,y = map(float,parts[:2])
            require(math.isfinite(x) and math.isfinite(y) and 0<=x<=1 and 0<=y<=1, 'Click outside image')
            clicks.append([x,y,int(parts[2])])
        result.append(dict(image_id=image_id,box_id=box_id,mask_path=name,starting_box=box,
                           predicted_iou=quality,clicks=clicks,publisher_annotation=dict(row)))
    return result


def select_complete_masks(records, boxes):
    """Never turn an annotated animal lacking a mask into training background."""
    masks = defaultdict(list)
    for row in records:
        masks[row['image_id']].append(row)
    eligible, excluded = {}, {}
    for image_id, source_boxes in boxes.items():
        candidates = masks.get(image_id, [])
        if not candidates:
            excluded[image_id] = 'no lizard masks'
            continue
        if len(candidates)!=len(source_boxes):
            excluded[image_id] = 'incomplete or extra mask coverage of publisher lizard boxes'
            continue
        matched = set()
        for mask in candidates:
            matches = []
            for index, source in enumerate(source_boxes):
                source = source['publisher_annotation']
                box = [float(source[key]) for key in ('XMin','YMin','XMax','YMax')]
                if all(abs(a-b)<=2e-6 for a,b in zip(mask['starting_box'],box)):
                    matches.append(index)
            if len(matches)!=1 or matches[0] in matched:
                excluded[image_id] = 'ambiguous or unmatched mask-to-box association'
                break
            matched.add(matches[0])
        if image_id not in excluded:
            eligible[image_id] = candidates
    return eligible, excluded


def validate_range(status, headers, payload, start, end, total, etag):
    require(status==206, 'Server ignored byte range; full archive download refused')
    headers = {key.lower():value for key,value in headers.items()}
    require(headers.get('content-range')==f'bytes {start}-{end}/{total}', 'Unexpected byte range response')
    require(headers.get('etag')==etag, 'Archive version changed')
    require(len(payload)==end-start+1, 'Truncated byte range')
    return payload


class RangeReader(io.RawIOBase):
    """Seekable byte window for zipfile, with a small cache and hard transfer caps."""
    def __init__(self, size, fetch, *, max_request=32*1024**2, max_total=64*1024**2):
        super().__init__()
        require(type(size) is int and size>0, 'Invalid remote archive size')
        require(type(max_request) is int and max_request>0 and type(max_total) is int and max_total>0, 'Invalid byte caps')
        self.size, self.fetch = size, fetch
        self.max_request, self.max_total = max_request, max_total
        self.position, self.bytes_downloaded = 0, 0
        self.cache_start, self.cache = 0, b''

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        if self.closed:
            raise ValueError('Read from closed archive')
        if type(offset) is not int or whence not in (0,1,2):
            raise ValueError('Invalid seek')
        position = offset+(0 if whence==0 else self.position if whence==1 else self.size)
        if not 0<=position<=self.size:
            raise ValueError('Seek outside archive')
        self.position = position
        return position

    def read(self, count=-1):
        if self.closed:
            raise ValueError('Read from closed archive')
        require(type(count) is int and count>=-1, 'Invalid read size')
        count = self.size-self.position if count==-1 else min(count,self.size-self.position)
        require(count<=self.max_request, 'Remote read exceeds request cap')
        if count==0:
            return b''
        start, end = self.position, self.position+count
        if not (self.cache_start<=start and end<=self.cache_start+len(self.cache)):
            amount = min(self.size-start,self.max_request,max(count,64*1024))
            require(self.bytes_downloaded+amount<=self.max_total, 'Remote archive transfer cap exceeded')
            payload = self.fetch(start,start+amount-1)
            require(isinstance(payload,bytes) and len(payload)==amount, 'Short remote ZIP read')
            self.bytes_downloaded += len(payload)
            self.cache_start, self.cache = start,payload
        offset = start-self.cache_start
        self.position = end
        return self.cache[offset:offset+count]
