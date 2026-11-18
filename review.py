"""Data-free public review: verify the published snapshot or serve its static dashboard."""
from pathlib import Path
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from functools import partial
from zipfile import ZipFile
from xml.etree import ElementTree as E
import argparse,csv,hashlib,json,re

ROOT=Path(__file__).resolve().parent

def check():
    results={};manifest=ROOT/'public_manifest.json'
    if manifest.exists():
        entries=json.loads(manifest.read_text())['files']
        results['public_file_hashes']=all((ROOT/item['path']).resolve().is_relative_to(ROOT.resolve()) and (ROOT/item['path']).is_file() and hashlib.sha256((ROOT/item['path']).read_bytes()).hexdigest()==item['sha256'] for item in entries)
    site=ROOT/'site' if (ROOT/'site/index.html').exists() else ROOT/'dashboard/dist'
    data=json.loads((site/'dashboard_data.json').read_text())
    with (ROOT/'outputs/rankings_final.csv').open(newline='',encoding='utf-8-sig') as stream:rows=list(csv.DictReader(stream))
    results['twenty_rows']=len(rows)==20
    results['ten_per_discipline']=all(sum(row['discipline']==d for row in rows)==10 for d in ['batter','bowler'])
    results['csv_dashboard_order']=[(r['discipline'],int(r['rank']),int(r['player_id']),r['display_name']) for r in rows]==[(r['discipline'],r['rank'],r['player_id'],r['display_name']) for r in data['final_lists']]
    results['six_source_datasets']=len(data['source_datasets']['datasets'])==6
    pptx=ROOT/'presentations/RR_Pressure_Reliability_Presentation.pptx'
    with ZipFile(pptx) as archive:
        slides=[n for n in archive.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml',n)]
        results['twenty_editable_slides']=len(slides)==20
        for page,discipline in [(4,'batter'),(5,'bowler'),(12,None)]:
            tree=E.fromstring(archive.read(f'ppt/slides/slide{page}.xml'))
            text=' '.join(n.text or '' for n in tree.findall('.//{http://schemas.openxmlformats.org/drawingml/2006/main}t'))
            names=[r['display_name'] for r in rows if discipline is None or r['discipline']==discipline]
            positions=[text.find(name) for name in names]
            results['slide_'+str(page)+'_order']=all(p>=0 for p in positions) and positions==sorted(positions)
    results['report_is_exact_published_file']=(ROOT/'report/RR_Pressure_Reliability_Methodology.pdf').read_bytes()==(site/data['pdf']).read_bytes()
    results['slides_are_exact_published_file']=pptx.read_bytes()==(site/data['pptx']).read_bytes()
    print(json.dumps({'passed':all(results.values()),'checks':results},indent=2))
    return 0 if all(results.values()) else 1

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['check','serve']);parser.add_argument('--port',type=int,default=8455);args=parser.parse_args()
    if args.command=='check':return check()
    site=ROOT/'site' if (ROOT/'site/index.html').exists() else ROOT/'dashboard/dist'
    if not (site/'index.html').exists():raise SystemExit('Prebuilt site missing. Follow docs/REPRODUCIBILITY.md.')
    server=ThreadingHTTPServer(('127.0.0.1',args.port),partial(SimpleHTTPRequestHandler,directory=str(site)))
    print(f'Open http://127.0.0.1:{server.server_port} (local-only; Ctrl+C to stop)',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
    return 0

if __name__=='__main__':raise SystemExit(main())
