"""Reproducibly redraw the frozen R15 schematic without changing its circuit.

The generated project is checked independently by tests/hardware/check_safe_r15.py.
No manufacturing output or source archive is overwritten by this script.
"""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import re
from uuid import UUID, uuid5
from zipfile import ZipFile

G = 1.27
NS = UUID('f401cb63-0d94-4fc4-9d46-bd2bfc17df5e')
STEM = 'HabitatOS_SAFE_R15'
# Documentation-only corrections, keyed by exact MPN and original frozen URL.
# Do not substitute parts, values, footprints, electrical pin types or nets.
YAGEO_RC_SOURCE = 'https://yageogroup.com/content/datasheet/asset/file/PYU-RC_GROUP_51_ROHS_L'
DATASHEET_CORRECTIONS = {
    'BC857B-7-F': ('https://www.diodes.com/assets/Datasheets/ds11108.pdf', 'https://www.diodes.com/datasheet/download/BC856A.pdf'),
    'BC847B-7-F': ('https://www.diodes.com/assets/Datasheets/ds11106.pdf', 'https://www.diodes.com/datasheet/download/BC847B.pdf'),
    'BAS116-7-F': ('https://www.diodes.com/assets/Datasheets/ds30259.pdf', 'https://www.diodes.com/datasheet/download/BAS116.pdf'),
    '1N4148W-7-F': ('https://www.diodes.com/assets/Datasheets/ds30086.pdf', 'https://www.diodes.com/datasheet/download/1N4148W.pdf'),
    # Murata-authored 2025 reference sheet, distributed by Mouser.
    'GRM2165C1H131JA01D': ('https://www.murata.com/en-global/products/capacitor/mlcc', 'https://www.mouser.lt/datasheet/3/76/2/GRM2165C1H131JA01_01A.pdf'),
    'GRM21BR71E105KA99L': ('https://www.murata.com/en-global/products/capacitor/mlcc', 'https://search.murata.co.jp/Ceramy/image/img/A01X/G101/ENG/GRM21BR71E105KA99-01.pdf'),
    'GRM21BR71H104KA01L': ('https://www.murata.com/en-global/products/capacitor/mlcc', 'https://search.murata.co.jp/Ceramy/image/img/A01X/G101/ENG/GRM21BR71H104KA01-01.pdf'),
    'RC0805FR-07118KL': ('https://www.digikey.com/en/products/detail/yageo/RC0805FR-07118KL/727566', YAGEO_RC_SOURCE),
    'RC0805FR-071KL': ('https://www.digikey.kr/ko/products/detail/yageo/RC0805FR-071KL/727444', YAGEO_RC_SOURCE),
    'RC1210FR-0768RL': ('https://www.yageo.com/en/Chart/Download/pdf/RC1210FR-0768RL', YAGEO_RC_SOURCE),
    **{mpn: ('https://www.yageo.com/en/Chart/Download/pdf/RC0805FR-0710KL', YAGEO_RC_SOURCE)
       for mpn in ('RC0805FR-07100KL', 'RC0805FR-0710KL', 'RC0805FR-071ML',
                   'RC0805FR-07200KL', 'RC0805FR-0722KL', 'RC0805FR-072K2L',
                   'RC0805FR-07422KL', 'RC0805FR-0747KL', 'RC0805FR-074K7L',
                   'RC0805FR-0762KL', 'RC0805FR-07887KL', 'RC0805FR-0797K6L')},
}


class Quoted(str):
    pass


def parse(text):
    stack, roots = [], []
    for token in re.findall(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+', text):
        if token == '(':
            node = []
            (stack[-1] if stack else roots).append(node)
            stack.append(node)
        elif token == ')':
            if not stack:
                raise ValueError('Unbalanced expression')
            stack.pop()
        else:
            if not stack:
                raise ValueError('Atom outside expression')
            stack[-1].append(Quoted(json.loads(token)) if token.startswith('"') else token)
    if stack or len(roots) != 1:
        raise ValueError('Incomplete expression')
    return roots[0]


def dump(node):
    if isinstance(node, list):
        return '(' + ' '.join(dump(item) for item in node) + ')'
    if isinstance(node, Quoted):
        return json.dumps(str(node), ensure_ascii=False)
    if isinstance(node, (int, float)):
        return format(node, '.6f').rstrip('0').rstrip('.') if isinstance(node, float) else str(node)
    return str(node)


def nodes(node, name):
    return [item for item in node[1:] if isinstance(item, list) and item and item[0] == name]


def one(node, name):
    result = nodes(node, name)
    if len(result) != 1:
        raise ValueError(f'Expected one {name}, found {len(result)}')
    return result[0]


def uid(name):
    return Quoted(str(uuid5(NS, name)))


def effects(size=1.5, justify=None, hide=False):
    result = ['effects', ['font', ['size', size, size]]]
    if justify:
        result.append(['justify', *justify.split()])
    if hide:
        result.append(['hide', 'yes'])
    return result


def stroke(style='default', width=.254):
    return ['stroke', ['width', width], ['type', style]]


def poly(points, style='default', width=.254):
    return ['polyline', ['pts', *[['xy', x * G, y * G] for x, y in points]], stroke(style, width), ['fill', ['type', 'none']]]


def rect(x1, y1, x2, y2):
    return ['rectangle', ['start', x1 * G, y1 * G], ['end', x2 * G, y2 * G], stroke(), ['fill', ['type', 'background']]]


def circle(x, y, radius):
    return ['circle', ['center', x * G, y * G], ['radius', radius * G], stroke(), ['fill', ['type', 'none']]]


def lib_text(text, x, y, size=1.5):
    return ['text', Quoted(text), ['at', x * G, y * G, 0], effects(size)]


def ranges(prefix, first, last):
    return [f'{prefix}{n}' for n in range(first, last + 1)]


GROUPS = [
    ('power', 'Power supervision and reset', ranges('C',101,108)+ranges('R',101,106)+ranges('U',101,104)),
    ('sensors', 'Level and leak contact supervision', ['J102','J103','SW_LEVEL','SW_LEAK']+ranges('R',107,120)+ranges('C',109,114)+ranges('U',105,108)),
    ('watchdog', 'Watchdog and isolated 24V sensing', ['R121','R122','U109','C115','U110','C116','J104','R123','D102','U111','C117']),
    ('timer', 'Mist window and manual button', ['U112','C118','R124','R191','R125','R126','R127','J105','R128','C119','U113','C120']),
    ('health', 'Fault polarity and health conditions', ['R129','U114','U115','U116','C121','C122','C123']),
    ('permits', 'Output permission and valve one-hot logic', ranges('R',131,134)+['U117','U118','U119','U123','C124','C125','C126','C130']),
    ('latches', 'Arm, manual token and timeout memory', ['R130','U120','U121','U122','C127','C128','C129']),
    ('release', 'Opposite-edge arm release', ['U128','U129','C140','C141']),
    ('pump', 'External CUT and RUN driver signals', ranges('Q',101,106)+ranges('R',135,150)+['D103','D104','C131','C132','J106','J107']),
    ('valves12', 'External valve 1 and 2 driver signals', ranges('Q',107,112)+ranges('R',151,166)+['D105','D106','C133','C134','J108','J109']),
    ('valve3', 'External valve 3 driver signal', ranges('Q',113,115)+ranges('R',167,174)+['D107','C135','J110']),
    ('esp', 'ESP request input conditioning', ['U126','U127','C138','C139',*ranges('R',175,190)]),
    ('status', 'ESP connector and open-drain status', ['J112','U124','U125','C136','C137']),
    ('pico', 'Pico H, physical sockets and reset', ['PICO1','SOCKET_PICO_1','SOCKET_PICO_2','J111']),
]


def build_library(original, component):
    """Keep every original pin name/type/number; replace only graphical layout."""
    library = copy.deepcopy(original)
    ref = component['ref']
    mpn = component['mpn']
    name = ('R_IEC' if re.match(r'^R\d+$',ref) else 'C_NONPOLAR' if re.match(r'^C\d+$',ref)
            else 'REMOTE_NC_CONTACT' if ref.startswith('SW_') else mpn.replace('#','_')+'_'+ref if ref.startswith(('J','SOCKET_')) else mpn.replace('#','_'))
    library[1]=Quoted('HabitatOS:'+name)
    old_pins = {}
    for unit in nodes(library, 'symbol'):
        for pin in nodes(unit, 'pin'):
            old_pins[str(one(pin, 'number')[1])] = copy.deepcopy(pin)
    graphics, locations = {}, {}
    def add_unit(number, drawing):
        graphics[number] = drawing
        locations[number] = {}
    def pin(number, x, y, angle, unit=1, style='line'):
        locations[unit][str(number)] = (x,y,angle,style)
    def power(vcc, gnd, unit=1, x=0, y=10):
        pin(vcc,x,y,270,unit)
        pin(gnd,x,-y,90,unit)
    if ref.startswith(('R','C')) and re.match(r'^[RC]\d+$', ref):
        drawing = ([rect(-1.5,3,1.5,-3)] if ref[0]=='R' else [poly([(-3,1),(3,1)]),poly([(-3,-1),(3,-1)])])
        add_unit(1,drawing)
        pin(1,0,7,270);pin(2,0,-7,90)
        library.append(['pin_numbers',['hide','yes']])
        one(library,'pin_names').append(['hide','yes'])
    elif ref.startswith('Q'):
        pnp = 'BC857' in mpn
        emitter_y = 10 if pnp else -10
        collector_y = -10 if pnp else 10
        drawing = [poly([(-4,0),(-1,0)]),poly([(-1,3),(-1,-3)]),poly([(-1,2),(4,5),(4,6)]),poly([(-1,-2),(4,-5),(4,-6)])]
        # Emitter arrow: towards base for PNP, away from base for NPN.
        arrow=poly([(2,4),(0,2),(2,2),(2,4)] if pnp else [(4,-5),(1,-4.5),(2.5,-2),(4,-5)])
        arrow[-1]=['fill',['type','outline']];drawing.append(arrow)
        add_unit(1,drawing)
        pin(1,-9,0,0);pin(2,4,emitter_y,270 if pnp else 90);pin(3,4,collector_y,90 if pnp else 270)
        one(library,'pin_names').append(['hide','yes'])
    elif ref.startswith('D'):
        drawing=[poly([(-2,-3),(-2,3),(2,0),(-2,-3)]),poly([(2,-3),(2,3)])]
        add_unit(1,drawing)
        anode = next(n for n,p in old_pins.items() if str(one(p,'name')[1])=='A')
        cathode = next(n for n,p in old_pins.items() if str(one(p,'name')[1])=='K')
        pin(anode,-7,0,0);pin(cathode,7,0,180)
        for n in old_pins.keys()-{anode,cathode}:
            pin(n,0,-7,90)
        one(library,'pin_names').append(['hide','yes'])
    elif ref.startswith('SW_'):
        add_unit(1,[circle(-2,0,.5),circle(2,0,.5),poly([(-2,0),(2,0)]),poly([(0,0),(0,3)])])
        pin(1,-7,0,0);pin(2,7,0,180)
        one(library,'pin_names').append(['hide','yes'])
    elif any(part in mpn for part in ('SN74LVC08A','SN74LVC32A','SN74LVC14A','SN74LVC74A','SN74LVC2G17')):
        one(library,'pin_names').append(['hide','yes'])
        if '08A' in mpn or '32A' in mpn:
            mapping=[(1,2,3),(4,5,6),(9,10,8),(12,13,11)]
            for unit,(a,b,y) in enumerate(mapping,1):
                add_unit(unit,[rect(-5,5,5,-5),lib_text('&' if '08A' in mpn else '>=1',0,0,2)])
                pin(a,-10,2,0,unit);pin(b,-10,-2,0,unit);pin(y,10,0,180,unit)
        elif '14A' in mpn:
            mapping=[(1,2),(3,4),(5,6),(9,8),(11,10),(13,12)]
            for unit,(a,y) in enumerate(mapping,1):
                add_unit(unit,[poly([(-4,-4),(-4,4),(4,0),(-4,-4)]),circle(5,0,1),poly([(-2,1),(0,1),(0,-1),(2,-1)])])
                pin(a,-9,0,0,unit);pin(y,10,0,180,unit)
        elif '74A' in mpn:
            mapping=[(1,2,3,4,5,6),(13,12,11,10,9,8)]
            for unit,(clr,d,clk,pre,q,qn) in enumerate(mapping,1):
                add_unit(unit,[rect(-9,7,9,-7),poly([(-9,-2),(-7,-3),(-9,-4)]),circle(0,8,1),circle(0,-8,1),circle(10,-3,1)])
                graphics[unit].extend([lib_text('D',-6,3),lib_text('CLK',-4,-3,1.2),lib_text('Q',6,3),lib_text('/Q',6,-3),lib_text('/PRE',0,5,1.2),lib_text('/CLR',0,-5,1.2)])
                pin(d,-14,3,0,unit);pin(clk,-14,-3,0,unit);pin(q,15,3,180,unit);pin(qn,15,-3,180,unit)
                pin(pre,0,13,270,unit);pin(clr,0,-13,90,unit)
        else:
            mapping=[(1,6),(3,4)]
            for unit,(a,y) in enumerate(mapping,1):
                add_unit(unit,[poly([(-4,-4),(-4,4),(4,0),(-4,-4)]),poly([(-2,1),(0,1),(0,-1),(2,-1)])])
                pin(a,-9,0,0,unit);pin(y,9,0,180,unit)
        unit = len(mapping)+1
        add_unit(unit,[rect(-4,5,4,-5),lib_text('PWR',0,0)])
        vcc=next(n for n,p in old_pins.items() if str(one(p,'name')[1])=='VCC')
        gnd=next(n for n,p in old_pins.items() if str(one(p,'name')[1])=='GND')
        power(vcc,gnd,unit,y=10)
    elif 'SN74LVC1G' in mpn:
        one(library,'pin_names').append(['hide','yes'])
        inverted='1G14' in mpn
        drawing=[poly([(-4,-4),(-4,4),(4,0),(-4,-4)])]
        if inverted:drawing.append(circle(5,0,1))
        if '17' in mpn or inverted:drawing.append(poly([(-2,1),(0,1),(0,-1),(2,-1)]))
        if '07' in mpn:drawing.append(lib_text('OD',0,-2,1.2))
        add_unit(1,drawing)
        pin(1,-9,-7,0);pin(2,-9,0,0);pin(4,10,0,180);power(5,3,y=9)
    elif ref=='PICO1':
        add_unit(1,[rect(-15,42,15,-42),lib_text('USB',0,39,2)])
        for n in range(1,21):pin(n,-20,38-(n-1)*4,0)
        for n in range(21,41):pin(n,20,38-(40-n)*4,180)
    elif ref.startswith(('J','SOCKET_')):
        if ref.startswith('J'):one(library,'pin_names').append(['hide','yes'])
        count=len(old_pins);height=max(5,2*(count-1)+3)
        add_unit(1,[rect(-3,height,12,-height)])
        for i,n in enumerate(sorted(old_pins,key=int)):
            pin(n,-8,2*(count-1)-i*4,0)
            if ref.startswith('J'):
                py=2*(count-1)-i*4
                graphics[1].append(poly([(-3,py),(-1,py)]))
                graphics[1].append(rect(-1,py+.7,.5,py-.7))
                label=str(one(old_pins[n],'name')[1])
                label={'PUMP_FUSED_PLUS':'+24V FUSED','POWER_GND':'PWR GND','LOGIC_GND':'GND','RETURN':'GND'}.get(label,label)
                graphics[1].append(lib_text(label,6,py,1.1))
    elif 'TPS3808' in mpn:
        add_unit(1,[rect(-9,7,9,-7)])
        pin(3,-14,4,0);pin(5,-14,0,0);pin(4,-14,-4,0);pin(1,14,0,180);power(6,2,y=12)
    elif 'TLV6700' in mpn:
        add_unit(1,[rect(-10,7,10,-7),lib_text('window',0,0,1.5)])
        pin(3,-15,3,0);pin(4,-15,-3,0);pin(1,15,3,180);pin(6,15,-3,180);power(5,2,y=12)
    elif 'STWD100' in mpn:
        add_unit(1,[rect(-9,7,9,-7)])
        pin(4,-14,3,0);pin(3,-14,-3,0);pin(1,14,0,180);power(5,2,y=12)
    elif 'LTC6993' in mpn:
        add_unit(1,[rect(-10,8,10,-8)])
        pin(1,-15,4,0);pin(3,-15,-4,0);pin(6,15,4,180);pin(4,15,-4,180);power(5,2,y=13)
    elif 'TLP2361' in mpn:
        add_unit(1,[rect(-12,10,12,-10),poly([(0,9),(0,-9)],'dash'),poly([(-8,3),(-5,3),(-5,-3),(-8,-3)]),poly([(3,-3),(3,3),(8,0),(3,-3)])])
        pin(1,-17,3,0);pin(3,-17,-3,0);pin(5,17,0,180);power(6,4,x=6,y=15)
    else:
        raise ValueError('No drawing for '+ref+' '+mpn)
    library=[item for item in library if not(isinstance(item,list) and item and item[0]=='symbol')]
    for unit,drawing in graphics.items():
        part=['symbol',Quoted(f'{name}_{unit}_1'),*drawing]
        for n,(x,y,angle,style) in locations[unit].items():
            p=copy.deepcopy(old_pins[n]);p[2]=style
            one(p,'at')[1:]=[x*G,y*G,angle]
            length=5
            if re.match(r'^R\d+$',ref):length=4
            if re.match(r'^C\d+$',ref):length=6
            if ref.startswith('Q') and n in ('2','3'):length=4
            if 'SN74LVC74A' in mpn and unit<3:
                length=4 if str(one(p,'name')[1]).endswith('Q_N') else 6 if str(one(p,'name')[1]).endswith('Q') else 5
            if 'SN74LVC1G' in mpn and n=='4':length=4 if '1G14' in mpn else 6
            one(p,'length')[1]=length*G
            one(one(p,'name'),'effects')[1]=['font',['size',1.5,1.5]]
            one(one(p,'number'),'effects')[1]=['font',['size',1.5,1.5]]
            part.append(p)
        library.append(part)
    if set(old_pins)!=set(n for pins in locations.values() for n in pins):
        raise ValueError('Lost library pins for '+ref)
    return library,locations


class Sheet:
    def __init__(self,key,title,refs,number,source):
        self.key,self.title,self.refs,self.number,self.source=key,title,refs,number,source
        self.uuid=uid('sheet:'+key);self.items=[];self.placed={};self.endpoints={};self.attached=set();self.wires=[];self.tagged=set()
        self.note(title,12,16,size=3)
    def note(self,text,x,y,size=1.8):
        self.items.append(['text',Quoted(text),['at',x*G,y*G,0],effects(size,'left'),['uuid',uid(f'{self.key}:text:{len(self.items)}')]])
    def graphic(self,points,style='default'):
        item=poly(points,style);item.pop() # Schematic polylines have no fill.
        item.append(['uuid',uid(f'{self.key}:graphic:{len(self.items)}')]);self.items.append(item)
    def box(self,text,x,y,w,h):
        self.graphic([(x,y),(x+w,y),(x+w,y+h),(x,y+h),(x,y)])
        self.note(text,x+3,y+5,size=2)
    def place(self,ref,x,y,unit=1,angle=0):
        if (ref,unit) in self.placed:raise ValueError('Duplicate placement '+ref)
        model=self.source.models[ref];symbol=copy.deepcopy(self.source.instances[ref])
        one(symbol,'lib_id')[1]=model[0][1]
        one(symbol,'at')[1:]=[x*G,y*G,angle];one(symbol,'unit')[1]=unit
        if unit!=1:one(symbol,'uuid')[1]=uid(f'{ref}:unit:{unit}')
        pins=model[1][unit]
        symbol=[item for item in symbol if not(isinstance(item,list) and item and item[0] in ('instances','pin'))]
        physical_uuid=one(symbol,'uuid')[1]
        for n in pins:
            symbol.append(['pin',Quoted(n),['uuid',uid(f'{ref}:pin:{n}')]])
        symbol.append(['instances',['project',Quoted(STEM),['path',Quoted(f'/{self.source.root_uuid}/{self.uuid}'),['reference',Quoted(ref)],['unit',unit]]]])
        for p in nodes(symbol,'property'):
            p[3]=['at',x*G,y*G,0]
            p[4]=effects(hide=p[1] not in ('Reference','Value'))
            if p[1]=='Reference':p[3]=['at',(x+8 if ref[0] in 'RCQD' else x-9)*G,(y-5 if ref[0] in 'RCQD' else y-14)*G,0]
            if p[1]=='Value':p[3]=['at',(x+8 if ref[0] in 'RCQD' else x-9)*G,(y-2 if ref[0] in 'RCQD' else y-11)*G,0]
            if p[1] in ('Reference','Value') and ref[0] not in 'RCQD':p[4]=effects(justify='right')
            if ref[0] in 'RC' and angle in (90,270):
                if p[1]=='Reference':p[3]=['at',x*G,(y-8)*G,angle]
                if p[1]=='Value':p[3]=['at',x*G,(y-4)*G,angle]
            if ref[0] in 'QD':
                if p[1]=='Reference':p[3]=['at',(x+10)*G,(y-6)*G,0];p[4]=effects(1.27,'left')
                if p[1]=='Value':p[3]=['at',(x+10)*G,(y-3)*G,0];p[4]=effects(1.27,'left')
            if ref.startswith('Q'):
                if p[1]=='Reference':p[3]=['at',(x-12)*G,(y-12)*G,0];p[4]=effects(1.27,'right')
                if p[1]=='Value':p[3]=['at',(x-12)*G,(y-9)*G,0];p[4]=effects(1.27,'right')
            if ref=='D102':
                if p[1]=='Reference':p[3]=['at',(x-4)*G,(y-12)*G,0];p[4]=effects(1.27,'right')
                if p[1]=='Value':p[3]=['at',(x-4)*G,(y-9)*G,0];p[4]=effects(1.27,'right')
            if ref.startswith('J'):
                height=max(5,2*(len(model[1][unit])-1)+3)
                if p[1]=='Reference':p[3]=['at',(x+4)*G,(y-height-8)*G,0];p[4]=effects()
                if p[1]=='Value':p[3]=['at',(x+4)*G,(y-height-5)*G,0];p[4]=effects(1.2)
            if ref.startswith('SW_') and p[1]=='Value':p[4]=effects(hide=True)
            if ref.startswith('U') and len(model[1])>1 and unit==max(model[1]):
                if p[1]=='Value':p[4]=effects(hide=True)
                if p[1]=='Reference':p[3]=['at',(x+7)*G,y*G,0];p[4]=effects(1.27,'left')
            elif ref.startswith('U') and len(model[1])==1 and 'SN74LVC1G' in self.source.components[ref]['mpn']:
                if p[1]=='Reference':p[3]=['at',x*G,(y-24)*G,0];p[4]=effects()
                if p[1]=='Value':p[3]=['at',x*G,(y-21)*G,0];p[4]=effects(1.27)
            if ref=='PICO1' or ref.startswith('SOCKET_'):
                if p[1]=='Reference':p[3]=['at',x*G,(y-50)*G,0]
                if p[1]=='Value':p[3]=['at',x*G,(y-47)*G,0]
        self.items.append(symbol);self.placed[(ref,unit)]=(x,y,angle,physical_uuid)
        c,s=round(math.cos(math.radians(angle))),round(math.sin(math.radians(angle)))
        for n,(px,py,pa,_) in pins.items():
            dx,dy=px*c-py*s,px*s+py*c
            self.endpoints[(ref,n)]=(x+dx,y-dy,(pa+angle)%360)
        return ref
    def end(self,ref,pin):return self.endpoints[(ref,str(pin))][:2]
    def net(self,ref,pin):return self.source.components[ref]['pins'][str(pin)]
    def wire(self,net,points):
        for a,b in zip(points,points[1:]):
            if a==b:continue
            if a[0]!=b[0] and a[1]!=b[1]:raise ValueError('Nonorthogonal wire')
            self.wires.append((net,a,b))
    def link(self,a,b,via=()):
        net=self.net(*a)
        if net is None or net!=self.net(*b):raise ValueError(f'Invalid connection {a} {b}')
        pa,pb=self.end(*a),self.end(*b)
        route=[pa,*via,pb]
        if not via and pa[0]!=pb[0] and pa[1]!=pb[1]:route=[pa,(pb[0],pa[1]),pb]
        self.wire(net,route);self.attached.update((tuple(map(str,a)),tuple(map(str,b))))
        return net
    def tag(self,net,x,y,angle=180):
        if net is None:raise ValueError('Cannot label NC')
        key=(net,x,y,angle)
        if key in self.tagged:return
        self.tagged.add(key)
        self.items.append(['global_label',Quoted(net),['shape','bidirectional'],['at',x*G,y*G,angle],effects(1.27,'right' if angle==180 else 'left'),['uuid',uid(f'{self.key}:label:{len(self.items)}')],['property',Quoted('Intersheetrefs'),Quoted('${INTERSHEET_REFS}'),['at',x*G,(y+3)*G,0],effects(1.27,hide=True)]])
    def label_pin(self,ref,pin,distance=6):
        p=(ref,str(pin));x,y,angle=self.endpoints[p];net=self.net(ref,pin)
        if net is None:
            self.items.append(['no_connect',['at',x*G,y*G],['uuid',uid(f'{self.key}:NC:{ref}:{pin}')]])
        else:
            # Extend away from the body: local pin direction points into the body.
            dx=-round(math.cos(math.radians(angle)))*distance
            dy=round(math.sin(math.radians(angle)))*distance
            self.wire(net,[(x,y),(x+dx,y+dy)])
            tagangle=180 if dx<0 or (dx==0 and dy<0) else 0
            if ref=='U111' and str(pin) in ('6','4'):tagangle=0
            self.tag(net,x+dx,y+dy,tagangle)
        self.attached.add(p)
    def cap(self,ref,x,y):
        self.place(ref,x,y)
        self.label_pin(ref,1,3);self.label_pin(ref,2,3)
    def finish(self):
        missing=set(self.refs)-{ref for ref,_ in self.placed}
        if missing:raise ValueError(f'Unplaced {self.key}: {sorted(missing)}')
        for ref in self.refs:
            units=set(self.source.models[ref][1])
            if units!={u for r,u in self.placed if r==ref}:raise ValueError('Missing units '+ref)
        for ref,pin in self.endpoints:
            if (ref,pin) not in self.attached:self.label_pin(ref,pin)
        # Every disconnected drawing of a named net needs its own label.
        # A label on a remote contact does not name the separate PCB-side drawing.
        parent={}
        def find(p):
            parent.setdefault(p,p)
            if parent[p]!=p:parent[p]=find(parent[p])
            return parent[p]
        for net,a,b in self.wires:
            points={p for n,x,y in self.wires if n==net for p in (x,y)
                    if (a[0]==b[0]==p[0] and min(a[1],b[1])<=p[1]<=max(a[1],b[1]))
                    or (a[1]==b[1]==p[1] and min(a[0],b[0])<=p[0]<=max(a[0],b[0]))}
            for p in points:parent[find((net,p))]=find((net,a))
        labelled={find((n,(x,y))) for n,x,y,_ in self.tagged}
        anchors=sorted(self.endpoints,key=lambda p:(self.endpoints[p][2] not in (90,270),p[0][0] not in 'RC',p))
        for ref,pin in anchors:
            net=self.net(ref,pin)
            root=find((net,self.end(ref,pin)))
            if net is not None and root not in labelled:
                self.label_pin(ref,pin);labelled.add(root)
        # Split at wire endpoints before adding true T-junction dots.
        points_by_net={}
        for net,a,b in self.wires:points_by_net.setdefault(net,set()).update((a,b))
        degrees={}
        segments=set()
        for net,a,b in self.wires:
            points=[p for p in points_by_net[net] if (a[0]==b[0]==p[0] and min(a[1],b[1])<=p[1]<=max(a[1],b[1])) or (a[1]==b[1]==p[1] and min(a[0],b[0])<=p[0]<=max(a[0],b[0]))]
            points.sort()
            for start,end in zip(points,points[1:]):segments.add((net,start,end))
        for net,a,b in sorted(segments):
            self.items.append(['wire',['pts',['xy',a[0]*G,a[1]*G],['xy',b[0]*G,b[1]*G]],stroke(width=0),['uuid',uid(f'{self.key}:wire:{len(self.items)}')]])
            for p in (a,b):degrees[(net,p)]=degrees.get((net,p),0)+1
        for (net,p),degree in degrees.items():
            if degree>2:self.items.append(['junction',['at',p[0]*G,p[1]*G],['diameter',0],['color',0,0,0,0],['uuid',uid(f'{self.key}:junction:{net}:{p}')]])
        libraries={str(self.source.models[ref][0][1]):self.source.models[ref][0] for ref in self.refs}
        root=['kicad_sch',['version',20250114],['generator',Quoted('eeschema')],['generator_version',Quoted('9.0')],['uuid',self.uuid],['paper',Quoted('A3')],self.source.titleblock(self.title),['lib_symbols',*[copy.deepcopy(lib) for lib in libraries.values()]],*self.items,['sheet_instances',['path',Quoted('/'),['page',Quoted(str(self.number))]]]]
        return root


class Source:
    def __init__(self,archive):
        self.archive=archive;self.raw={};self.instances={};self.original_libs={};self.models={}
        with ZipFile(archive) as z:
            manifest=json.loads(z.read('HabitatOS_R15/pcb/release_manifest.json'))
            for item in manifest['final_native_project_whitelist']:
                name=item['path_from_r15_root'].removeprefix('pcb/')
                data=z.read('HabitatOS_R15/pcb/'+name)
                if hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('Original hash mismatch')
                self.raw[name]=data
            canonical=json.loads(z.read('HabitatOS_R15/circuit/r15_safety_pin_netlist.json'))
        self.components={c['ref']:c for c in canonical['components']}
        root=parse(self.raw[STEM+'.kicad_sch'].decode());self.root_uuid=one(root,'uuid')[1]
        for name,data in self.raw.items():
            if not name.endswith('.kicad_sch'):continue
            tree=parse(data.decode())
            for sym in nodes(one(tree,'lib_symbols'),'symbol'):self.original_libs[str(sym[1])]=sym
            for sym in nodes(tree,'symbol'):
                ref=next(p[2] for p in nodes(sym,'property') if p[1]=='Reference')
                self.instances[str(ref)]=sym
        for ref,c in self.components.items():
            correction=DATASHEET_CORRECTIONS.get(c['mpn'])
            if correction:
                prop=next(p for p in nodes(self.instances[ref],'property') if p[1]=='Datasheet')
                if c['source_url']!=correction[0] or prop[2]!=correction[0]:
                    raise ValueError('Unexpected original datasheet source: '+ref)
                prop[2]=Quoted(correction[1])
            self.models[ref]=build_library(self.original_libs[str(one(self.instances[ref],'lib_id')[1])],c)
        all_refs=[r for _,_,refs in GROUPS for r in refs]
        if len(all_refs)!=198 or len(set(all_refs))!=198 or set(all_refs)!=set(self.components):raise ValueError('Bad function partition')
    def titleblock(self,title):
        aliases=['Power supervision','Level / leak supervision','Watchdog + 24V sensing','Mist window / button','Health and fault polarity','Permission + one-hot','Arm / token / timeout','Opposite-edge release','CUT / RUN driver interface','Valve 1 / 2 driver interface','Valve 3 driver interface','ESP request inputs','ESP status connector','Pico H and carrier sockets']
        short=dict(zip([t for _,t,_ in GROUPS],aliases)).get(title,'System overview')
        return ['title_block',['title',Quoted('SAFE R15 - '+short)],['date',Quoted('2026-10-05')],['rev',Quoted('R15-DOC1')],['company',Quoted('HabitatOS')],['comment',1,Quoted('Circuit R15 preserved; document redraw. Physical tests pending.')],['comment',2,Quoted('SAFE_GND and POWER_GND are separate electrical domains.')]]


def write_tree(path,tree):
    path.write_text(dump(tree)+'\n',encoding='utf-8')


def power_page(s):
    s.note('Two supervised rails; BOTH TPS3808 devices are supplied from AUX_5V.',12,25)
    for u,rt,rb,ct,cdec,x in [('U101','R102','R103','C103','C104',90),('U102','R104','R105','C105','C106',190)]:
        rx=x-55
        s.place(u,x,75);s.place(rt,rx,58);s.place(rb,rx,90);s.place(ct,x-35,115)
        s.link((rt,2),(rb,1))
        s.link((rt,2),(u,5),[(rx,75)])
        s.link((ct,1),(u,4),[(x-35,79)])
        s.cap(cdec,x+12,115)
    s.place('R101',265,60,angle=180)
    s.link(('U101',1),('U102',1),[(114,75),(114,40),(214,40),(214,75)])
    s.link(('R101',2),('U102',1),[(265,40),(214,40),(214,75)])
    s.place('U103',120,165);s.place('U104',240,165);s.place('R106',285,172)
    s.link(('U104',4),('R106',1))
    for ref,x,y in [('C101',30,160),('C102',55,160),('C107',80,165),('C108',200,165)]:s.cap(ref,x,y)
    s.note('U101: AUX_5V divider    U102: SAFE_3V3 divider',12,205)
    s.note('POR_OK = 3.3V logic; POR_DRV_5V = 5V driver gating.',12,213)


def sensor_channel(s,level,dy):
    j,sw=('J102','SW_LEVEL') if level else ('J103','SW_LEAK')
    r0=107 if level else 114;c0=109 if level else 112;u0=105 if level else 107
    rr=[f'R{r0+i}' for i in range(7)];cc=[f'C{c0+i}' for i in range(3)];u=f'U{u0}';buf=f'U{u0+1}'
    s.note('LEVEL - supervised remote NC contact' if level else 'LEAK - supervised remote NC contact',12,31+dy,2)
    s.place(j,40,82+dy);s.place(rr[0],45,48+dy)
    for ref,x,y in [(rr[1],95,60),(rr[2],95,90),(rr[3],125,60),(rr[4],125,90),(rr[5],190,60)]:s.place(ref,x,y+dy)
    s.place(u,155,75+dy);s.place(buf,235,75+dy)
    s.place(cc[0],68,92+dy)
    s.link((rr[0],2),(j,1),[(10,55+dy),(10,80+dy)])
    for ref in (rr[1],rr[3]):
        x=s.end(ref,1)[0]
        s.link((rr[0],2),(ref,1),[(65,55+dy),(65,38+dy),(x,38+dy)])
    s.link((rr[1],2),(rr[2],1));s.link((rr[3],2),(rr[4],1))
    s.link((rr[1],2),(u,3),[(95,72+dy)])
    s.link((rr[3],2),(u,4),[(125,78+dy)])
    s.link((cc[0],1),(rr[0],2),[(68,55+dy)])
    s.link((u,1),(u,6),[(178,72+dy),(178,78+dy)])
    s.link((rr[5],2),(u,1),[(178,67+dy),(178,72+dy)])
    s.link((u,1),(buf,2),[(178,72+dy),(178,75+dy)])
    s.cap(cc[1],155,106+dy);s.cap(cc[2],215,106+dy)
    # Sensor-side EOL components are explicitly outside the carrier PCB.
    s.graphic([(263,43+dy),(323,43+dy),(323,113+dy),(263,113+dy),(263,43+dy)],'dash')
    s.note('REMOTE / not on this PCB',266,49+dy,1.5)
    s.place(sw,285,65+dy);s.place(rr[6],306,90+dy)
    s.link((sw,2),(rr[6],1),[(306,65+dy)])


def sensors_page(s):
    sensor_channel(s,True,0);sensor_channel(s,False,85)
    s.note('Remote EOL resistors: R113 and R120. Sensor contacts remain normally closed.',12,217,1.6)


def watchdog_page(s):
    s.note('Heartbeat supervision and optically isolated supply presence sensing.',12,26)
    s.place('U109',110,75);s.place('R122',55,85);s.place('R121',165,55);s.place('U110',215,75)
    s.link(('R122',1),('U109',4),[(55,72)])
    s.link(('U109',1),('R121',2),[(165,75)])
    s.link(('U109',1),('U110',2))
    s.cap('C115',110,113);s.cap('C116',215,113)
    s.note('U109.EN_N (pin 3) is tied to SAFE_GND in the original circuit.',20,130)
    s.graphic([(160,143),(160,220)],'dash')
    s.note('POWER_GND side',20,149,2);s.note('SAFE_GND side',185,149,2)
    s.place('J104',35,180);s.place('R123',80,177,angle=90)
    s.place('U111',160,180);s.place('D102',115,200)
    s.link(('J104',1),('R123',1),[(20,178),(20,160),(73,160)])
    s.link(('R123',2),('U111',1))
    s.link(('D102',1),('U111',1),[(130,200),(130,177)])
    s.link(('D102',2),('J104',2),[(98,200),(20,200),(20,182)])
    s.link(('U111',3),('J104',2),[(135,183),(135,213),(20,213),(20,182)])
    s.cap('C117',220,185)
    s.note('J104 senses the fused 24V supply; it is NOT the pump-current path.',12,222,1.5)


def timer_page(s):
    s.note('Original timing resistors and trigger polarity are preserved.',12,26)
    s.place('U112',120,80);s.place('R124',55,99);s.place('R191',55,128)
    s.link(('U112',3),('R124',1),[(55,84)])
    s.link(('R124',2),('R191',1))
    s.place('R125',195,55);s.place('R126',195,90)
    s.link(('R125',2),('R126',1));s.link(('R125',2),('U112',4),[(195,84)])
    s.place('R127',55,55);s.link(('R127',1),('U112',1),[(40,48),(40,76)])
    s.cap('C118',250,80)
    s.note('LTC6993 window: SET resistor chain R124 + R191; DIV divider R125 / R126.',20,150)
    s.place('J105',55,188);s.place('R128',100,170);s.place('C119',130,195);s.place('U113',205,187)
    s.link(('J105',1),('R128',2),[(35,186),(35,177)]);s.link(('R128',2),('U113',2),[(130,177),(130,187)])
    s.link(('C119',1),('R128',2),[(130,177)])
    s.cap('C120',220,208)
    s.note('BTN_RAW is pulled up; the external button connects BTN_RAW to SAFE_GND.',12,222,1.5)


def power_bank(s,items,x=30,y=204,spacing=65):
    for index,(ref,cap) in enumerate(items):
        px=x+index*spacing;unit=max(s.source.models[ref][1])
        s.place(ref,px,y,unit=unit);s.place(cap,px+23,y)
        locations=s.source.models[ref][1][unit]
        vcc=next(p for p in locations if s.net(ref,p)=='SAFE_3V3')
        gnd=next(p for p in locations if s.net(ref,p)=='SAFE_GND')
        s.link((ref,vcc),(cap,1),[(px,y-12),(px+23,y-12)])
        s.link((ref,gnd),(cap,2),[(px,y+12),(px+23,y+12)])
        s.tag('SAFE_3V3',px,y-12,180)
        s.tag('SAFE_GND',px,y+12,180)


def gate(s,ref,unit,x,y):
    s.place(ref,x,y,unit=unit)


def chain(s,a,b):
    pa,pb=s.end(*a),s.end(*b)
    x=pb[0]-5
    s.link(a,b,[(x,pa[1]),(x,pb[1])])


def health_page(s):
    s.note('All conditions in the original hardware health chain are retained.',12,26)
    # Two rows form one continuous AND chain; inputs have meaningful net labels.
    for u,y in [('U115',66),('U116',114)]:
        for unit,x in enumerate([55,125,195,265],1):gate(s,u,unit,x,y)
    for a,b in [(('U115',3),('U115',4)),(('U115',6),('U115',9)),(('U115',8),('U115',12)),(('U116',3),('U116',4)),(('U116',6),('U116',9))]:chain(s,a,b)
    s.link(('U115',11),('U116',1),[(290,66),(290,91),(30,91),(30,112)])
    for unit,x,y in [(1,55,154),(2,150,154),(3,245,154),(4,55,181),(5,150,181),(6,245,181)]:gate(s,'U114',unit,x,y)
    s.place('R129',20,110)
    power_bank(s,[('U114','C121'),('U115','C122'),('U116','C123')])
    s.note('U114: input polarity normalization. U115/U116: health, fault and timeout reset.',12,222,1.5)


def permits_page(s):
    s.note('Pump window, valve permissions and exactly-one-valve gating.',12,26)
    # Functional rows, rather than one rectangle per physical IC.
    rows=[('U117',55),('U118',97),('U119',139),('U123',181)]
    for ref,y in rows:
        for unit,x in enumerate([55,125,195,265],1):gate(s,ref,unit,x,y)
    chain(s,('U117',8),('U117',12))
    chain(s,('U119',8),('U119',13))
    chain(s,('U123',3),('U123',4));chain(s,('U123',8),('U123',12))
    # Local pulldowns are drawn next to their actual command net.
    for ref,x,y in [('R131',302,55),('R132',302,97),('R133',302,139),('R134',302,181)]:s.place(ref,x,y)
    power_bank(s,[('U117','C124'),('U118','C125'),('U119','C126'),('U123','C130')],x=30,y=205,spacing=55)


def latches_page(s):
    s.note('Arm state, single-use manual token and latched window timeout.',12,26)
    gate(s,'U120',1,90,65);gate(s,'U120',2,90,125)
    gate(s,'U121',1,180,65);gate(s,'U122',1,180,135);gate(s,'U121',2,270,135)
    # Explicit feedback from the complemented arm state.
    s.link(('U121',6),('U120',2),[(210,68),(210,96),(65,96),(65,67)])
    s.link(('U120',6),('U121',2),[(145,125),(145,62)])
    s.link(('U120',3),('U122',1),[(115,65),(115,156),(180,156)])
    s.link(('U122',5),('U120',5),[(215,132),(215,108),(40,108),(40,127)])
    gate(s,'U120',3,42,173);gate(s,'U120',4,112,173);gate(s,'U122',2,205,192)
    s.note('Unused gates / flip-flop remain tied off and explicitly NC as in R15.',12,187,1.5)
    s.place('R130',30,56)
    power_bank(s,[('U120','C127'),('U121','C128'),('U122','C129')],x=30,y=208,spacing=67)


def release_page(s):
    s.note('Two stages sample opposite ARM_PULSE edges; actual pin contract is preserved.',12,26)
    gate(s,'U128',1,70,80);s.place('U129',170,80);gate(s,'U128',2,270,80)
    s.link(('U128',5),('U128',12),[(105,77),(105,43),(235,43),(235,77)])
    s.link(('U129',4),('U128',11),[(215,80),(215,83)])
    s.note('Stage 1: ARM_PULSE rising edge',30,115,2)
    s.note('Stage 2: inverted ARM_PULSE rising edge',190,115,2)
    s.note('Both asynchronous clear inputs are driven by FAULT_N.',30,130)
    power_bank(s,[('U128','C140')],x=80,y=170)
    s.cap('C141',225,170)
    s.note('This drawing does not certify real pulse timing or hydraulic commissioning.',12,210)


def output_channel(s,prefix,q0,r0,d,c,j,dx):
    def place(ref,x,y,angle=0):s.place(ref,dx+x,20+y,angle=angle)
    def p(x,y):return (dx+x,20+y)
    qq=[f'Q{q0+i}' for i in range(3)];rr=[f'R{r0+i}' for i in range(8)]
    s.note(prefix+' - external driver signal',dx+5,23,2)
    place(qq[0],100,32);place(qq[1],98,90);place(qq[2],98,128)
    for ref,x,y,angle in [(rr[0],65,22,180),(rr[1],65,50,0),(rr[2],37,90,90),(rr[3],66,106,0),(rr[4],37,128,90),(rr[5],66,143,0),(rr[6],118,78,0),(rr[7],119,42,90)]:place(ref,x,y,angle)
    place(d,79,66);place(c,35,22);place(j,138,90)
    s.link((qq[0],2),(rr[0],2),[p(104,8),p(65,8)])
    s.link((qq[0],2),(c,1),[p(104,8),p(35,8)])
    s.link((qq[0],1),(rr[0],1),[p(65,32)])
    s.link((rr[0],1),(rr[1],1))
    s.link((rr[1],2),(d,1),[p(65,66)])
    s.link((d,3),(qq[1],3),[p(102,66)])
    s.link((rr[2],2),(qq[1],1))
    s.link((qq[1],1),(rr[3],1),[p(66,90)])
    s.link((rr[3],2),(qq[1],2),[p(76,113),p(76,109),p(102,109)])
    s.link((qq[1],2),(qq[2],3))
    s.link((rr[4],2),(qq[2],1))
    s.link((qq[2],1),(rr[5],1),[p(66,128)])
    s.link((qq[2],2),(rr[5],2),[p(102,166),p(66,166)])
    s.link((qq[0],3),(rr[7],1))
    s.link((rr[7],2),(j,1),[p(130,42)])
    s.link((j,1),(rr[6],1),[p(130,71)])
    s.link((rr[6],2),(qq[2],2),[p(118,166),p(102,166)])
    s.link((j,3),(qq[2],2),[p(130,166),p(102,166)])


def outputs_page(s):
    specs={'pump':[('CUT',101,135,'D103','C131','J106',8),('RUN',104,143,'D104','C132','J107',170)],
           'valves12':[('VALVE 1',107,151,'D105','C133','J108',8),('VALVE 2',110,159,'D106','C134','J109',170)],
           'valve3':[('VALVE 3',113,167,'D107','C135','J110',40)]}
    for args in specs[s.key]:output_channel(s,*args)
    s.note('J106-J110: pin 1 = SIG, pin 2 = NC, pin 3 = SAFE_GND.',12,207)
    s.note('Signal interface to external DFR0457 modules. Motor/valve current is external.',12,215,1.6)
    if s.key=='valve3':
        s.note('Supply domains',215,60,2)
        s.note('AUX_5V: PNP high-side signal source',215,72)
        s.note('SAFE_GND: logic return',215,82)
        s.note('No 24V load power on these connectors.',215,94)


def esp_page(s):
    s.note('Four 3.3V request/heartbeat paths; original pulldowns are preserved.',12,26)
    for i,(ref,unit,series,rraw,ra,rb,y) in enumerate([
        ('U126',1,'R179','R175','R180','R181',50),('U126',2,'R182','R176','R183','R184',90),
        ('U127',1,'R185','R177','R186','R187',130),('U127',2,'R188','R178','R189','R190',170)]):
        gate(s,ref,unit,235,y);s.place(series,130,y,angle=90)
        s.place(rraw,80,y+14);s.place(ra,170,y+14);s.place(rb,275,y+14)
        s.link((series,1),(rraw,1),[(80,y)])
        s.link((series,2),(ref,1 if unit==1 else 3))
        s.link((series,2),(ra,1),[(170,y)])
        s.link((ref,6 if unit==1 else 4),(rb,1),[(275,y)])
        s.note(s.net(series,1)+' -> '+s.net(ref,6 if unit==1 else 4),15,y-10,1.8)
    power_bank(s,[('U126','C138'),('U127','C139')],x=45,y=211,spacing=95)


def status_page(s):
    s.note('J112 is a 3.3V logic interface. NC pins 1 and 2 are intentionally unused.',12,26)
    s.place('J112',65,95);s.place('U124',200,70);s.place('U125',200,145)
    s.link(('U124',4),('J112',8),[(235,70),(235,190),(35,190),(35,107)])
    s.link(('U125',4),('J112',9),[(225,145),(225,180),(45,180),(45,111)])
    s.cap('C136',270,70);s.cap('C137',270,145)
    s.note('U124/U125: open-drain status outputs; no pullup is added by this redraw.',120,205)
    s.note('REQ1/2/3 and HB conditioning: see the ESP request input sheet.',12,215)


def pico_page(s):
    s.note('External USB-powered Pico H module and the two physical carrier sockets.',12,26)
    s.place('PICO1',70,100);s.place('SOCKET_PICO_1',178,100);s.place('SOCKET_PICO_2',280,100)
    s.place('J111',70,170)
    s.note('SOCKET_PICO_1.n = Pico physical pin n',120,157)
    s.note('SOCKET_PICO_2.n = Pico physical pin (41 - n)',120,169)
    s.note('USB end aligns physical Pico pins 1 and 40.',120,181)
    s.note('VBUS pin 40 -> AUX_5V; 3V3_OUT pin 36 -> SAFE_3V3.',12,199)
    s.note('No external supply feed into AUX_5V / SAFE_3V3 is introduced.',12,209)
    # Preserve the original USB-ground source declaration, including its identity.
    flag=copy.deepcopy(s.source.instances['#FLG01'])
    one(flag,'at')[1:]=[40*G,220*G,0]
    for prop in nodes(flag,'property'):
        prop[3]=['at',40*G,(216 if prop[1]=='Value' else 220)*G,0]
    one(flag,'instances')[1]=['project',Quoted(STEM),['path',Quoted(f'/{s.source.root_uuid}/{s.uuid}'),['reference',Quoted('#FLG01')],['unit',1]]]
    s.items.append(flag)
    flag_lib=copy.deepcopy(s.source.original_libs[str(one(flag,'lib_id')[1])])
    s.source.models['#FLG01']=(flag_lib,{})
    # Flag has its pin at its origin in the supplied library.
    s.tag('SAFE_GND',40,220,0)


def overview(source,sheets):
    page=Sheet('overview','System overview and drawing index',[],1,source)
    page.note('Independent protection: one 24V pump, three valves, external power drivers.',12,27)
    page.note('Circuit R15 is unchanged. Document revision R15-DOC1. Hardware commissioning pending.',12,36,1.6)
    page.note('Functional flow (conceptual; electrical connections are on the numbered sheets)',15,47,1.5)
    for title,x,y,w in [('Remote level / leak',15,55,85),('Independent supervision',122,55,85),('Hardware permission',230,55,85),('ESP commands',15,100,85),('Pico sequencer',122,100,85),('CUT / RUN / valve signals',230,100,85)]:
        page.box(title,x,y,w,23)
    for text,x,y in [('NC contact + remote EOL',18,69),('POR, heartbeat, 24V, timer',125,69),('Health, arm, token, one-hot',233,69),('REQ1/2/3, heartbeat',18,114),('USB power, sequence I/O',125,114),('To external DFR0457 drivers',233,114)]:page.note(text,x,y,1.5)
    def arrow(points):
        page.graphic(points)
        x,y=points[-1];px,py=points[-2]
        page.graphic([(x-2,y-1.5),(x,y),(x-2,y+1.5)] if x>px else [(x-1.5,y-2),(x,y),(x+1.5,y-2)])
    arrow([(100,66),(122,66)]);arrow([(207,66),(230,66)])
    arrow([(100,111),(122,111)]);arrow([(207,111),(218,111),(218,73),(230,73)])
    arrow([(272,78),(272,100)])
    page.note('External 24V load power and POWER_GND are separate from the SAFE_GND logic.',15,133,1.5)
    page.note('Drawing index',15,143,2)
    for i,sheet in enumerate(sheets):
        col,row=i//7,i%7;x=15+col*156;y=147+row*7
        page.note(f'{sheet.number:02d}  {sheet.title}',x+2,y+3,1.4)
    page.note('Named nets join sheets. Input left / output right; power above / return below.',15,215,1.3)
    page.note('Remote: Pico H, EOL resistors and contacts. Customer fitted: two Pico sockets.',15,222,1.3)
    # Use the actual root UUID so existing symbol identities remain traceable.
    root=['kicad_sch',['version',20250114],['generator',Quoted('eeschema')],['generator_version',Quoted('9.0')],['uuid',source.root_uuid],['paper',Quoted('A3')],source.titleblock('System overview'),['lib_symbols'],*page.items]
    for i,sheet in enumerate(sheets):
        col,row=i//7,i%7;x=15+col*156;y=147+row*7
        root.append(['sheet',['at',x*G,y*G],['size',148*G,6*G],['fields_autoplaced','yes'],stroke(),['fill',['color',0,0,0,0]],['uuid',sheet.uuid],['property',Quoted('Sheetname'),Quoted(sheet.title),['at',x*G,(y-1)*G,0],effects(1.5,hide=True)],['property',Quoted('Sheetfile'),Quoted(sheet.key+'.kicad_sch'),['at',x*G,(y+7)*G,0],effects(1.5,hide=True)],['instances',['project',Quoted(STEM),['path',Quoted('/'+str(source.root_uuid)),['page',Quoted(str(sheet.number))]]]]])
    root.append(['sheet_instances',['path',Quoted('/'),['page',Quoted('1')]]])
    return root


def redraw(source,output):
    if output==source.archive or output.is_file():raise ValueError('Output must be a project directory')
    output.mkdir(parents=True,exist_ok=True)
    for name,data in source.raw.items():
        if name.endswith('.kicad_sch') or name=='HabitatOS.kicad_sym':continue
        target=output/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    functions={'power':power_page,'sensors':sensors_page,'watchdog':watchdog_page,'timer':timer_page,'health':health_page,'permits':permits_page,'latches':latches_page,'release':release_page,'pump':outputs_page,'valves12':outputs_page,'valve3':outputs_page,'esp':esp_page,'status':status_page,'pico':pico_page}
    sheets=[];paths={}
    for number,(key,title,refs) in enumerate(GROUPS,2):
        sheet=Sheet(key,title,refs,number,source);functions[key](sheet)
        tree=sheet.finish()
        if key=='pico':one(tree,'lib_symbols').append(copy.deepcopy(source.models['#FLG01'][0]))
        write_tree(output/(key+'.kicad_sch'),tree);sheets.append(sheet)
        for (ref,unit),(_,_,_,symbol_uuid) in sheet.placed.items():
            if unit==1:paths[ref]=Quoted(f'/{source.root_uuid}/{sheet.uuid}/{symbol_uuid}')
    write_tree(output/(STEM+'.kicad_sch'),overview(source,sheets))
    libraries={str(model[0][1]):model[0] for model in source.models.values()}
    symroot=['kicad_symbol_lib',['version',20241209],['generator',Quoted('kicad_symbol_editor')]]
    for name,lib in libraries.items():
        lib=copy.deepcopy(lib);lib[1]=Quoted(name.split(':',1)[1]);symroot.append(lib)
    write_tree(output/'HabitatOS.kicad_sym',symroot)
    board_text=source.raw[STEM+'.kicad_pcb'].decode()
    board=parse(board_text)
    for fp in nodes(board,'footprint'):
        ref=next(p[2] for p in nodes(fp,'property') if p[1]=='Reference')
        if ref in paths:
            old=dump(one(fp,'path'));new=dump(['path',paths[ref]])
            if board_text.count(old)!=1:raise ValueError('Ambiguous PCB link '+ref)
            board_text=board_text.replace(old,new,1)
        if ref in source.components and len(source.models[ref][1])>1:
            for pad in nodes(fp,'pad'):
                pin=str(pad[1])
                if source.components[ref]['pins'].get(pin,'not-NC') is not None:continue
                net=one(pad,'net');oldname=str(net[2])
                unit=next(u for u,pins in source.models[ref][1].items() if pin in pins)
                newname=oldname.replace(f'({ref}-',f'({ref}{chr(64+unit)}-',1)
                if oldname==newname or not oldname.startswith('unconnected-'):raise ValueError('Unexpected NC name')
                old=json.dumps(oldname);new=json.dumps(newname)
                if board_text.count(old)!=2:raise ValueError('NC net is not a singleton '+ref+'.'+pin)
                board_text=board_text.replace(old,new)
    # The geometry checker allows only the updated schematic linkage paths.
    (output/(STEM+'.kicad_pcb')).write_text(board_text,encoding='utf-8')
    print(json.dumps({'project':str(output),'sheets':len(sheets)+1,'components':len(source.components),'library_symbols':len(libraries),'circuit_changed':False},ensure_ascii=False))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    redraw(Source(args.archive.resolve(strict=True)),args.output.resolve())


if __name__=='__main__':main()
