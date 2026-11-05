#!/usr/bin/env python3
"""Verify real pixel playback and WAV clock advancement in Chromium."""
import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',required=True);parser.add_argument('--report',type=Path,required=True);parser.add_argument('--use-proxy-env',action='store_true')
    args=parser.parse_args();args.report.parent.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as p:
        launch={}
        if args.use_proxy_env:
            value=os.environ.get('https_proxy') or os.environ.get('HTTPS_PROXY')
            if value:
                parsed=urlsplit(value);proxy={'server':f'{parsed.scheme}://{parsed.hostname}:{parsed.port}','bypass':'127.0.0.1,localhost'}
                if parsed.username:proxy['username']=parsed.username
                if parsed.password:proxy['password']=parsed.password
                launch['proxy']=proxy
        browser=p.chromium.launch(headless=True,args=['--no-sandbox','--autoplay-policy=no-user-gesture-required'],**launch)
        page=browser.new_page(viewport={'width':1360,'height':900});errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(args.url,wait_until='networkidle');page.wait_for_function('window.__smokeReady')
        records=[]
        for index in range(page.locator('.player').count()):
            element=page.locator('.player').nth(index)
            element.locator('.play').click()
            page.wait_for_function(f'window.__smokePlayers[{index}].frames!==null',timeout=120000)
            page.wait_for_timeout(650)
            state=page.evaluate(f'({{frame:window.__smokePlayers[{index}].frame,playing:window.__smokePlayers[{index}].playing,n:window.__smokePlayers[{index}].d.frames,canvasAlpha:window.__smokePlayers[{index}].ctx.getImageData(0,0,1,1).data[3],audio:window.__smokePlayers[{index}].audio?{{time:window.__smokePlayers[{index}].audio.currentTime,paused:window.__smokePlayers[{index}].audio.paused}}:null}})')
            assert state['frame']>0 and state['playing'] and state['canvasAlpha']==255,state
            if state['audio']:assert state['audio']['time']>0 and not state['audio']['paused'],state
            element.locator('.play').click();records.append(state)
            element.locator('.seek').evaluate("e=>{e.value=e.max;e.dispatchEvent(new Event('input'))}")
            page.wait_for_function(f'window.__smokePlayers[{index}].frame===window.__smokePlayers[{index}].d.frames-1')
            element.locator('.replay').click();page.wait_for_timeout(200)
            element.locator('.play').click()
        assert not errors,errors
        page.screenshot(path=str(args.report.with_suffix('.desktop.png')),full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        page.screenshot(path=str(args.report.with_suffix('.mobile.png')),full_page=True)
        result={'url':args.url,'players':records,'page_errors':errors}
        args.report.write_text(json.dumps(result,indent=2));print(json.dumps(result));browser.close()


if __name__=='__main__':main()
