"""Build a small Pages artifact while keeping exact media in its source repo.

Only PixelWorld media references are rewritten. The personal homepage and other
sections are copied unchanged. Raw media URLs point to the deployment commit.
"""
from __future__ import annotations

import argparse
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess
import posixpath
from urllib.parse import quote, unquote, urlsplit

MEDIA = ('.png','.jpg','.jpeg','.webp','.gif','.mp4','.webm','.wav','.npz','.gz','.zip')


def is_media(path: str) -> bool:
    return path.startswith('pixelworld/') and path.lower().endswith(MEDIA)


def rewrite(text: str, relative: str, known: set[str], repository: str, revision: str, live_version: str = 'live') -> str:
    base = 'https://raw.githubusercontent.com/' + repository + '/' + revision + '/'
    def asset(value):
        if not isinstance(value,str):return value
        url=urlsplit(value)
        if url.scheme or url.netloc or not url.path:return value
        path=Path('/') / (unquote(url.path).lstrip('/') if url.path.startswith('/') else
                         str(Path(relative).parent / unquote(url.path)))
        normalized=posixpath.normpath(str(path)).lstrip('/')
        if normalized not in known or not is_media(normalized):return value
        return base+quote(normalized,safe='/')+('?' + url.query if url.query else '')+('#' + url.fragment if url.fragment else '')
    def nested(value):
        if isinstance(value,dict):return {k:nested(v) for k,v in value.items()}
        if isinstance(value,list):return [nested(v) for v in value]
        return asset(value)
    offsets=[0]
    offsets.extend(m.end() for m in re.finditer('\n',text))
    edits=[]
    class Parser(HTMLParser):
        def __init__(self):super().__init__(convert_charrefs=False);self.script=False
        def handle_starttag(self,tag,attrs):
            literal=self.get_starttag_text();updated=literal
            for key,value in attrs:
                if value is None:continue
                replacement=value
                if key in ('src','href','poster'):
                    replacement=asset(value)
                elif key.startswith('data-'):
                    try:replacement=json.dumps(nested(json.loads(value)),ensure_ascii=False)
                    except (ValueError,TypeError):replacement=asset(value)
                if replacement==value:continue
                pattern=r'(\b'+re.escape(key)+r'\s*=\s*)(?:"[^"]*"|\x27[^\x27]*\x27|[^\s>]+)'
                updated=re.sub(pattern,lambda m:m[1]+'"'+html.escape(replacement,quote=True)+'"',updated,count=1,flags=re.I)
            if updated!=literal:
                line,column=self.getpos();start=offsets[line-1]+column
                edits.append((start,start+len(literal),updated))
            if tag=='script':self.script=True
        def handle_startendtag(self,tag,attrs):self.handle_starttag(tag,attrs)
        def handle_endtag(self,tag):
            if tag=='script':self.script=False
        def handle_data(self,data):
            if not self.script:return
            # Some legacy players keep their media configuration in inline JS.
            updated=re.sub(r'(["\x27])([^"\x27\n]+)\1',lambda m:m[1]+asset(m[2])+m[1],data)
            if updated!=data:
                line,column=self.getpos();start=offsets[line-1]+column
                edits.append((start,start+len(data),updated))
    parser=Parser();parser.feed(text);parser.close()
    for start,end,value in reversed(edits):text=text[:start]+value+text[end:]
    if relative.startswith('pixelworld/') and relative.endswith('.html'):
        url = '/pixelworld/live_refresh.js?v=' + live_version
        if '/pixelworld/live_refresh.js' in text:
            text = re.sub(r'/pixelworld/live_refresh\.js(?:\?[^\s\"\x27<>]*)?', url, text)
        else:
            script = '<script defer src="' + url + '"></script>'
            text = text.replace('</body>', script + '</body>') if '</body>' in text else text + script
    return text


def build(source: Path, destination: Path, repository: str, revision: str) -> dict:
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository) or not re.fullmatch(r'[a-fA-F0-9]{40,64}',revision):
        raise ValueError('Use a public owner/repository and exact commit hash')
    source=source.resolve();destination=destination.resolve()
    if destination==source:raise ValueError('Output must be separate from source')
    git_source = (source/'.git').exists()
    blobs = {}
    if git_source:
        tree = subprocess.check_output(['git','-C',str(source),'ls-tree','-r','-z',revision])
        known = set()
        for entry in tree.split(b'\0'):
            if not entry:
                continue
            metadata, name = entry.split(b'\t', 1)
            mode, kind, oid = metadata.split()
            name = name.decode('utf-8', errors='surrogateescape')
            known.add(name)
            if kind == b'blob' and mode in (b'100644', b'100755'):
                blobs[name] = oid
    else:
        known={str(p.relative_to(source)) for p in source.rglob('*') if p.is_file() and not p.is_relative_to(destination)}
    if destination.exists():raise FileExistsError('Use an empty artifact directory')
    destination.mkdir(parents=True)
    paths=[p for p in sorted(known) if not p.startswith(('.github/','.git/')) and not is_media(p)]
    count=size=rewritten=0
    def contents():
        if not git_source:
            for relative in paths:
                original = source / relative
                if original.is_file():
                    yield relative, original.read_bytes()
            return
        # Resolve paths once, then stream only committed blobs through one Git
        # process. Avoid repeated archive tree walks and temporary file copies.
        process = subprocess.Popen(['git','-C',str(source),'cat-file','--batch'],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        try:
            for relative in paths:
                oid = blobs.get(relative)
                if oid is None:
                    continue
                name = Path(relative)
                if name.is_absolute() or '..' in name.parts:
                    raise ValueError('Unsafe committed path')
                process.stdin.write(oid + b'\n')
                process.stdin.flush()
                header = process.stdout.readline().split()
                if len(header) != 3 or header[0] != oid or header[1] != b'blob':
                    raise ValueError('Unexpected committed blob response')
                size = int(header[2])
                payload = process.stdout.read(size)
                if len(payload) != size or process.stdout.read(1) != b'\n':
                    raise ValueError('Truncated committed blob')
                yield relative, payload
        finally:
            process.stdin.close()
            process.stdout.close()
            if process.wait(timeout=30):
                raise RuntimeError('Committed blob reader failed')
    for relative, payload in contents():
            target=destination/relative;target.parent.mkdir(parents=True,exist_ok=True)
            if relative.startswith('pixelworld/') and relative.endswith('.html'):
                version = blobs.get('pixelworld/live_refresh.js', revision)[:12].decode() if isinstance(blobs.get('pixelworld/live_refresh.js'), bytes) else revision[:12]
                before=payload.decode('utf-8');after=rewrite(before,relative,known,repository,revision,version)
                target.write_text(after);rewritten+=before!=after
            else:target.write_bytes(payload)
            count+=1;size+=target.stat().st_size
    (destination/'.nojekyll').touch()
    result={'files':count,'artifact_bytes':size,'rewritten_pages':rewritten,
            'excluded_media_files':sum(is_media(p) for p in known),
            'media_repository':repository,'media_revision':revision,'source_media_deleted':False}
    (destination/'pixelworld-publication.json').write_text(json.dumps(result,indent=2))
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--repository',required=True);p.add_argument('--revision',required=True)
    a=p.parse_args();print(json.dumps(build(a.source,a.output,a.repository,a.revision),indent=2))


if __name__=='__main__':main()
