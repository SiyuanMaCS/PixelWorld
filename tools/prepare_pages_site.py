"""Build a small Pages artifact while keeping exact media in its source repo.

Only PixelWorld media references are rewritten. The personal homepage and other
sections are copied unchanged. Raw media URLs point to the deployment commit.
"""
from __future__ import annotations

import argparse
import html
import io
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess
import posixpath
import tarfile
import tempfile
from urllib.parse import quote, unquote, urlsplit

MEDIA = ('.png','.jpg','.jpeg','.webp','.gif','.mp4','.webm','.wav','.npz','.gz','.zip')


def is_media(path: str) -> bool:
    return path.startswith('pixelworld/') and path.lower().endswith(MEDIA)


def rewrite(text: str, relative: str, known: set[str], repository: str, revision: str) -> str:
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
    return text


def build(source: Path, destination: Path, repository: str, revision: str) -> dict:
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository) or not re.fullmatch(r'[a-fA-F0-9]{40,64}',revision):
        raise ValueError('Use a public owner/repository and exact commit hash')
    source=source.resolve();destination=destination.resolve()
    if destination==source:raise ValueError('Output must be separate from source')
    git_source = (source/'.git').exists()
    if git_source:
        known=set(subprocess.check_output(['git','-C',str(source),'ls-tree','-r','--name-only',revision],text=True).splitlines())
    else:
        known={str(p.relative_to(source)) for p in source.rglob('*') if p.is_file() and not p.is_relative_to(destination)}
    if destination.exists():raise FileExistsError('Use an empty artifact directory')
    destination.mkdir(parents=True)
    paths=[p for p in sorted(known) if not p.startswith(('.github/','.git/')) and not is_media(p)]
    count=size=rewritten=0
    with tempfile.TemporaryDirectory(prefix='pages-source-snapshot-') as temp:
        snapshot=Path(temp)
        if git_source:
            # Read committed blobs, never publish unrelated unstaged edits.
            for start in range(0,len(paths),500):
                archive=subprocess.check_output(['git','-C',str(source),'archive',revision,'--',*paths[start:start+500]])
                with tarfile.open(fileobj=io.BytesIO(archive),mode='r:') as tar:
                    for member in tar:
                        if not member.isfile():continue
                        relative=Path(member.name)
                        if relative.is_absolute() or '..' in relative.parts:raise ValueError('Unsafe archive path')
                        target=snapshot/relative;target.parent.mkdir(parents=True,exist_ok=True)
                        with tar.extractfile(member) as stream:target.write_bytes(stream.read())
        else:snapshot=source
        for relative in paths:
            original=snapshot/relative
            if not original.is_file():continue
            target=destination/relative;target.parent.mkdir(parents=True,exist_ok=True)
            if relative.startswith('pixelworld/') and relative.endswith('.html'):
                before=original.read_text();after=rewrite(before,relative,known,repository,revision)
                target.write_text(after);rewritten+=before!=after
            else:shutil.copy2(original,target)
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
