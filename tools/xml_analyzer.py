"""
tools/xml_analyzer.py — ONE TIME script
Parses Alight Motion XMLs → extracts animated segments →
converts to GSAP code → stores in SQLite DB

Usage:
  python tools/xml_analyzer.py xml_library/
  python tools/xml_analyzer.py xml_library/OP02.xml --clear
"""

import os
import sys
import json
import sqlite3
import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

DB_PATH = "effects_library.db"


def am_ease_to_gsap(ease_str: str) -> str:
    if not ease_str or ease_str == 'linear':
        return 'none'
    parts = ease_str.strip().split()
    if parts[0] == 'cubicBezier' and len(parts) >= 5:
        x1,y1,x2,y2 = float(parts[1]),float(parts[2]),float(parts[3]),float(parts[4])
        if y2 >= 1.0 and x2 <= 0.4: return 'power3.out'
        elif y1 == 0.0 and y2 == 1.0: return 'power2.inOut'
        elif x1 == 0.42: return 'power2.in'
        else: return f'cubic-bezier({parts[1]},{parts[2]},{parts[3]},{parts[4]})'
    if parts[0] == 'elastic' and len(parts) >= 3:
        amp = float(parts[1]) if len(parts)>1 else 1.0
        per = float(parts[2]) if len(parts)>2 else 0.3
        return f'elastic.out({round(1/max(per,0.1),2)},{round(amp,2)})'
    if parts[0] == 'bounce':   return 'bounce.out'
    if parts[0] == 'overshoot':
        s = float(parts[1]) if len(parts)>1 else 1.0
        return f'back.out({round(s,2)})'
    return 'power2.out'


def detect_vibe(label, effects, properties, start_ms, end_ms):
    dur = end_ms - start_ms
    effect_ids = [e.lower() for e in effects]

    if 'location' in properties and len(properties['location']) >= 3:
        locs = properties['location']
        xs = [float(k['v'].split(',')[0]) for k in locs if ',' in k['v']]
        if xs and max(xs)-min(xs) > 50: return 'shake'

    if 'scale' in properties:
        eases = [k['ease'] for k in properties['scale']]
        if any('elastic' in e or 'back' in e for e in eases): return 'bounce_in'
        first = properties['scale'][0]['v']
        if '0.0' in first or '0.03' in first: return 'scale_pop'

    if 'location' in properties:
        locs = properties['location']
        if len(locs) >= 2:
            try:
                x0=float(locs[0]['v'].split(',')[0]); x1=float(locs[-1]['v'].split(',')[0])
                y0=float(locs[0]['v'].split(',')[1]); y1=float(locs[-1]['v'].split(',')[1])
                if abs(x1-x0) > 200: return 'slide_horizontal'
                if abs(y1-y0) > 150: return 'slide_vertical'
            except: pass

    if 'opacity' in properties:
        vals = []
        for k in properties['opacity']:
            try: vals.append(float(k['v']))
            except: pass
        if vals:
            return 'fade_in' if vals[-1] > vals[0] else 'fade_out'

    if any('wipe'    in e for e in effect_ids): return 'wipe_transition'
    if any('glow'    in e for e in effect_ids): return 'glow_reveal'
    if any('extrude' in e for e in effect_ids): return 'text_extrude'
    if any('counter' in e for e in effect_ids): return 'counter_anim'
    if any('wave'    in e for e in effect_ids): return 'wave_distort'
    if 'rotation' in properties: return 'spin'
    if dur < 1000:  return 'quick_pop'
    if dur < 3000:  return 'short_anim'
    return 'ambient'


def generate_gsap(label, properties, start_ms, vibe):
    lines  = []
    delay  = round(start_ms / 1000, 2)

    for prop, kfs in properties.items():
        if len(kfs) < 2: continue
        kfs_s = sorted(kfs, key=lambda x: x['t_ms'])
        first, last = kfs_s[0], kfs_s[-1]
        dur  = max((last['t_ms']-first['t_ms'])/1000, 0.1)
        ease = am_ease_to_gsap(last.get('ease','linear'))

        try:
            if prop == 'scale':
                sx0,sy0 = [float(v) for v in first['v'].split(',')[:2]]
                sx1,sy1 = [float(v) for v in last['v'].split(',')[:2]]
                lines.append(f'gsap.fromTo("{{el}}", {{scaleX:{round(sx0,3)},scaleY:{round(sy0,3)}}}, {{scaleX:{round(sx1,3)},scaleY:{round(sy1,3)},duration:{round(dur,2)},ease:"{ease}",delay:{delay}}});')

            elif prop == 'location':
                x0=float(first['v'].split(',')[0]); y0=float(first['v'].split(',')[1])
                x1=float(last['v'].split(',')[0]);  y1=float(last['v'].split(',')[1])
                dx0,dy0 = round(x0-960,1), round(y0-540,1)
                dx1,dy1 = round(x1-960,1), round(y1-540,1)
                lines.append(f'gsap.fromTo("{{el}}", {{x:{dx0},y:{dy0}}}, {{x:{dx1},y:{dy1},duration:{round(dur,2)},ease:"{ease}",delay:{delay}}});')

            elif prop == 'opacity':
                v0=float(first['v']); v1=float(last['v'])
                lines.append(f'gsap.fromTo("{{el}}", {{opacity:{round(v0,2)}}}, {{opacity:{round(v1,2)},duration:{round(dur,2)},ease:"{ease}",delay:{delay}}});')

            elif prop == 'rotation':
                r0=float(first['v']); r1=float(last['v'])
                lines.append(f'gsap.fromTo("{{el}}", {{rotation:{round(r0,1)}}}, {{rotation:{round(r1,1)},duration:{round(dur,2)},ease:"{ease}",delay:{delay}}});')
        except: pass

    return '\n'.join(lines) if lines else ''


def parse_xml(xml_path):
    tree     = ET.parse(xml_path)
    root     = tree.getroot()
    total_ms = int(root.get('totalTime', 40000))
    source   = Path(xml_path).name
    segments = []

    def get_effects(elem):
        return [e.get('id','').split('.')[-1] for e in elem.findall('effect')]

    def get_transform_props(elem):
        t = elem.find('transform')
        if t is None: return {}
        props = {}
        for pname in ['location','scale','rotation','opacity']:
            node = t.find(pname)
            if node is None: continue
            kfs = node.findall('kf')
            if not kfs: continue
            props[pname] = sorted([{
                't_ms': round(float(k.get('t','0'))*total_ms),
                'v':    k.get('v','0'),
                'ease': k.get('e','linear'),
            } for k in kfs], key=lambda x: x['t_ms'])
        return props

    for tag in ['shape','text','video','image','embedScene']:
        for elem in root.iter(tag):
            label    = elem.get('label', elem.get('id','?'))
            start_ms = int(elem.get('startTime',0))
            end_ms   = int(elem.get('endTime',0))
            if end_ms <= start_ms: continue

            props   = get_transform_props(elem)
            effects = get_effects(elem)
            if not props: continue

            vibe = detect_vibe(label, effects, props, start_ms, end_ms)
            gsap = generate_gsap(label, props, start_ms, vibe)
            if not gsap: continue

            segments.append({
                'source_xml':    source,
                'label':         label,
                'vibe_tag':      vibe,
                'start_ms':      start_ms,
                'end_ms':        end_ms,
                'duration_ms':   end_ms - start_ms,
                'keyframe_json': json.dumps({'props': props, 'effects': effects}),
                'gsap_code':     gsap,
            })

    print(f"[PARSE] {source} → {len(segments)} segments")
    return segments


def init_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("""CREATE TABLE IF NOT EXISTS effects_library (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        source_xml    TEXT,
        label         TEXT,
        vibe_tag      TEXT,
        start_ms      INTEGER,
        end_ms        INTEGER,
        duration_ms   INTEGER,
        keyframe_json TEXT,
        gsap_code     TEXT,
        created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vibe ON effects_library(vibe_tag)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dur  ON effects_library(duration_ms)")
    conn.commit()
    return conn


def print_summary(conn):
    print("\n═══ EFFECTS DB SUMMARY ═══")
    rows = conn.execute("""
        SELECT vibe_tag, COUNT(*) as cnt, MIN(duration_ms), MAX(duration_ms)
        FROM effects_library GROUP BY vibe_tag ORDER BY cnt DESC
    """).fetchall()
    for vibe,cnt,mn,mx in rows:
        print(f"  {vibe:<22} {cnt:>4} segments  |  {mn}ms – {mx}ms")
    total = conn.execute("SELECT COUNT(*) FROM effects_library").fetchone()[0]
    print(f"\n  TOTAL: {total} segments | DB: {db_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('path',  help='XML file or folder')
    parser.add_argument('--db',  default='effects_library.db')
    parser.add_argument('--clear', action='store_true')
    args    = parser.parse_args()

    global db_path
    db_path = args.db

    p = Path(args.path)
    xml_files = list(p.glob('*.xml')) if p.is_dir() else ([p] if p.suffix=='.xml' else [])
    if not xml_files:
        print("No XML files found!"); sys.exit(1)

    print(f"Found {len(xml_files)} XML(s)")
    conn = init_db(db_path)

    if args.clear:
        conn.execute("DELETE FROM effects_library")
        conn.commit()
        print("[DB] Cleared")

    for xml_file in xml_files:
        try:
            segs = parse_xml(str(xml_file))
            if segs:
                conn.executemany("""INSERT INTO effects_library
                    (source_xml,label,vibe_tag,start_ms,end_ms,duration_ms,keyframe_json,gsap_code)
                    VALUES (:source_xml,:label,:vibe_tag,:start_ms,:end_ms,:duration_ms,:keyframe_json,:gsap_code)
                """, segs)
                conn.commit()
        except Exception as e:
            print(f"[ERROR] {xml_file}: {e}")
            import traceback; traceback.print_exc()

    print_summary(conn)
    conn.close()


if __name__ == '__main__':
    db_path = 'effects_library.db'
    main()
    