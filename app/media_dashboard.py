#!/usr/bin/env python3
"""Media Hub Studio Controller (v2.9.8) - http://localhost:8080"""
import http.server, socketserver, json, os, urllib.parse, re, subprocess, shutil, threading, time, mimetypes, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ai_common import read_srt, HUB, JOBS, META, conf, parse_range, estimate, load_timings, status, s2ts, set_hook_text, safe_name, read_cuts, timeline, effective_cuts
from slice_clips import slice_text

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
BASE_HUB = os.path.realpath(HUB)
YT_IN = os.path.join(HUB, "youtube_long/input")
YT_OUT = os.path.join(HUB, "youtube_long/output")
SPLIT_IN = os.path.join(HUB, "split_screen/input")
SHORTS_IN = os.path.join(HUB, "shorts_daily/input")
TARGETS = {"youtube": YT_IN, "shorts": SHORTS_IN, "split": SPLIT_IN}
OUT_DIRS = ["youtube_long/output", "podcast_audio/output", "split_screen/output", "shorts_daily/output"]
GPU_LOCK = "/tmp/mediahub_gpu.lock"
PORT = int(os.environ.get("MH_PORT", "8080"))

HTML = r"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Media Hub Studio</title>
<style>
body{font-family:system-ui,sans-serif;background:#111;color:#f4f4f5;margin:0;padding:22px}
.wrap{max-width:1280px;margin:0 auto}h1{color:#3b82f6;margin:0;font-size:24px}
.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;gap:12px;flex-wrap:wrap}
.pill{background:#1c1c1f;border:1px solid #2e2e32;border-radius:999px;padding:6px 14px;font-size:13px}
.grid{display:grid;grid-template-columns:1.15fr .85fr;gap:18px}
@media(max-width:980px){.grid{grid-template-columns:1fr}}
.card{background:#1c1c1f;border:1px solid #2e2e32;border-radius:10px;padding:16px;margin-bottom:16px}
label{display:block;font-weight:600;margin-bottom:6px;font-size:14px}
select,input,textarea{width:100%;box-sizing:border-box;background:#121214;border:1px solid #3f3f46;color:#fff;padding:9px;border-radius:6px;font-family:ui-monospace,monospace;font-size:14px;margin-bottom:10px}
textarea{height:96px}
.tbox{height:360px;overflow-y:auto;background:#09090b;border:1px solid #27272a;border-radius:6px;font-family:ui-monospace,monospace;font-size:13px}
.seg{padding:3px 8px;cursor:pointer;border-left:3px solid transparent}.seg:hover{background:#1f1f23}
.seg b{color:#a1a1aa;font-weight:400;margin-right:8px}.seg.cur{background:#2a1a05;border-left-color:#3b82f6}
.seg.pick{background:#3b82f6;color:#000}.seg.pick b{color:#000}
.row{display:flex;gap:8px;align-items:center;margin-bottom:10px;flex-wrap:wrap}
.btn{background:#3b82f6;color:#000;font-weight:700;border:none;padding:11px;border-radius:6px;cursor:pointer;width:100%}
.btn:disabled,.btn-sec:disabled{opacity:.5;cursor:not-allowed}
.btn-sec{background:#27272a;color:#fff;font-weight:600;border:1px solid #3f3f46;padding:7px 11px;border-radius:6px;cursor:pointer;font-size:13px}
.tgt label{display:inline-flex;align-items:center;gap:5px;font-weight:500;margin:0 10px 0 0;font-size:13px}.tgt input{width:auto;margin:0}
video{width:100%;max-height:330px;background:#000;border-radius:6px;margin-bottom:10px}
.job{background:#121214;border:1px solid #27272a;border-radius:6px;padding:8px 10px;margin-bottom:6px;font-size:13px}
.bar{height:5px;background:#27272a;border-radius:3px;margin-top:6px;overflow:hidden}.bar i{display:block;height:100%;background:#3b82f6}
.job.done .bar i{background:#22c55e}.job.error .bar i{background:#ef4444}.job.error{border-color:#7f1d1d}
pre{white-space:pre-wrap;background:#09090b;border:1px solid #27272a;padding:12px;border-radius:6px;font-size:13px;max-height:420px;overflow:auto;margin:0}
.grid>*{min-width:0}#files a{color:#3b82f6;text-decoration:none;word-break:break-all;margin-right:10px}#files>div{display:flex;justify-content:space-between;gap:10px;font-size:13px;padding:5px 0;border-bottom:1px solid #222}#files span{white-space:nowrap}
.muted{color:#a1a1aa;font-size:13px}
.dial{display:flex;gap:12px;align-items:center}@keyframes spin{to{transform:rotate(360deg)}}.spin{animation:spin 1.1s linear infinite;transform-origin:29px 29px}
.tw{cursor:pointer;padding:1px 0;border-radius:3px}.tw:hover{background:#27272a}.tw.cut{color:#52525b;text-decoration:line-through}.tw.del{background:#7f1d1d;color:#fff;text-decoration:line-through}.tw.sel{background:#3b82f6;color:#000}.tw.q{background:#78350f;color:#fde68a;text-decoration:line-through}.tw.keep{background:#14532d;color:#fff}.tw.asel{background:#3b82f6;color:#000}
#order div{display:flex;gap:6px;align-items:center;font-size:13px;padding:3px 0}#order button{padding:2px 8px}.dial svg{flex:none}.dial .t{font-size:12px;color:#a1a1aa;margin-top:3px}
.btn-red{background:#7f1d1d;color:#fff;font-weight:600;border:1px solid #b91c1c;padding:6px 12px;border-radius:999px;cursor:pointer;font-size:13px}
.btn-go{background:linear-gradient(90deg,#3b82f6,#ffb347);color:#000;font-weight:800;border:none;padding:14px;border-radius:8px;cursor:pointer;width:100%;font-size:16px}
#status{position:sticky;bottom:10px;padding:12px;border-radius:6px;background:#18181b;border-left:4px solid #3b82f6;display:none;white-space:pre-wrap}
</style></head><body><div class="wrap">
<div class="top"><h1>Media Hub Studio Controller</h1><div class="row" style="margin:0"><span class="pill" id="disk">Disk: ...</span><button class="btn-red" onclick="purge()" title="Delete every file of the selected episode from the Ubuntu box">Purge Episode Files</button></div></div>

<div id="ready" style="display:none;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;background:#0f2a18;border:1px solid #22c55e;border-radius:10px;padding:12px 16px;margin-bottom:16px"></div>
<div class="grid"><div>
<div class="card"><label>0. Upload Video Directly</label>
<div class="row" style="margin:0"><input type="file" id="vf" multiple style="margin:0;flex:2;min-width:200px" onchange="showOrder()">
<select id="vt" style="margin:0;flex:1.2;min-width:160px" onchange="showOrder()"><option value="youtube">Long YouTube + Podcast</option><option value="shorts">Daily 9:16 Short</option><option value="split">2-Person Split-Screen</option><option value="stitch_solo">Stitch clips into ONE short (solo)</option><option value="stitch_split">Stitch clips into ONE short (split-screen)</option></select>
<button class="btn" id="ub" style="flex:.6;min-width:90px" onclick="up()">Upload</button></div>
<input type="text" id="uh" autocomplete="off" style="margin:10px 0 0" placeholder="Shorts hook text, slams in for 2 s (optional). *WORD* = orange">
<div id="order"></div>
<div id="ut" class="muted" style="margin-top:6px"></div></div>

<div class="card"><label>Promo Clips: upload once, used in every production automatically</label>
<div id="promo" class="muted">Loading...</div>
<div class="muted" style="margin-top:6px">Each new upload replaces the old one. Already-finished episodes keep what they had; just rebuild them to pick up a new clip.</div></div>

<div class="card"><div class="row" style="margin:0"><div style="flex:1"><label>1. Select Master Episode</label>
<select id="ep" onchange="lt()" style="margin:0"></select></div>
<button class="btn-sec" style="margin-top:22px" onclick="re()">Refresh</button></div>
<button class="btn-go" id="frb" style="margin-top:12px" onclick="fullrun()">Run Full Production</button>
<div class="row" style="margin:8px 0 0"><input type="checkbox" id="fs" style="width:auto;margin:0"><label for="fs" style="margin:0;font-weight:500">Also cut AI shorts afterwards (off = shorts only when you ask)</label></div>
<div class="muted" style="margin-top:6px">AI trim, edited video + podcast MP3 + captions + content pack. Uses the hook box and outro tick below if set.</div></div>

<div class="card"><div class="row" style="justify-content:space-between;margin-bottom:8px"><label style="margin:0">Player</label>
<select id="pvs" style="width:auto;margin:0" onchange="loadPlayer()"><option value="master">Master (full recording)</option><option value="edited">Edited video</option></select></div>
<video id="pv" controls preload="metadata"></video>
<div class="row tgt" style="justify-content:space-between"><span class="muted">Click a line to set START, click another to set END, then it goes to:</span></div>
<div class="row tgt">
<label><input type="radio" name="tg" value="keep" checked>Keep-range</label>
<label><input type="radio" name="tg" value="hook">Hook</label>
<label><input type="radio" name="tg" value="split">Clip: split</label>
<label><input type="radio" name="tg" value="solo">Clip: solo</label>
<label><input type="radio" name="tg" value="wide">Clip: wide</label>
<label><input type="radio" name="tg" value="audio">Clip: audio</label>
<label><input type="radio" name="tg" value="remove">Remove from edit</label></div>
<div id="tr" class="tbox"><div class="seg">Loading...</div></div></div>
</div>

<div>
<div class="card"><div class="row" style="justify-content:space-between;margin-bottom:8px"><label style="margin:0">Live Jobs</label><button class="btn-sec" onclick="clearJobs()">Clear finished</button></div><div id="jobs" class="muted">No jobs yet.</div></div>

<div class="card"><div class="row" style="justify-content:space-between;margin-bottom:6px"><label style="margin:0">2. Cold-Open Hook (Optional)</label>
<button class="btn-sec" onclick="aihook()">Use AI Hook</button></div>
<input type="text" id="hk" value="" autocomplete="off" placeholder="Empty = no cold open (max 25 seconds)">
<div class="row" style="justify-content:space-between;margin-bottom:6px"><label style="margin:0">3. Main Episode Keep-Ranges</label>
<button class="btn-sec" id="atb" onclick="at()">AI Auto-Trim Start &amp; End</button></div>
<textarea id="cr" placeholder="00:01:15 - 00:28:50"></textarea>
<div class="row"><input type="checkbox" id="ao" style="width:auto;margin:0"><label for="ao" style="margin:0">Append Video Outro (outro.mp4)</label></div>
<div class="row"><input type="checkbox" id="cf" style="width:auto;margin:0" checked><label for="cf" style="margin:0">Remove ums, stumbles &amp; long pauses</label></div>
<button class="btn" onclick="sc()">Build Edited Video + Podcast MP3</button>
<button class="btn-sec" style="width:100%;margin-top:8px" onclick="po()">Pop Outro Onto Master Now</button></div>

<div class="card"><label>4. Slice &amp; Dice Social Clips</label>
<div class="row"><select id="am" style="margin:0;flex:1"><option value="solo">AI shorts: one person, follows the speaker</option><option value="split">AI shorts as split-screen</option></select>
<button class="btn-sec" id="asb" onclick="as2(0)">AI Pick &amp; Cut Shorts</button>
<button class="btn-sec" onclick="as2(1)" title="Ask the AI again instead of using the saved picks">Re-pick</button></div>
<textarea id="cl" style="height:90px" placeholder="00:03:15 - 00:04:02 | split | OPTIONAL HOOK TEXT *ORANGE*"></textarea>
<button class="btn-sec" style="width:100%" onclick="scl()">Slice &amp; Dispatch Clips Now</button>
<div id="picks" class="muted" style="margin-top:8px"></div></div>

<div class="card"><label>5. Remove a Section from the Edited Video</label>
<div class="muted" style="margin-bottom:8px">Play the EDITED video above, press Start at the bad bit and End where it should resume. Only the seconds around the cut are re-rendered.</div>
<div class="row"><button class="btn-sec" onclick="mark(0)">Start = player time</button><button class="btn-sec" onclick="mark(1)">End = player time</button></div>
<input type="text" id="rm" placeholder="Times in the edited video, e.g. 00:12:10 - 00:12:25">
<button class="btn" style="background:#b45309;color:#fff" onclick="rmsec()">Remove Section &amp; Rebuild</button></div>
</div></div>

<div class="card"><div class="row" style="justify-content:space-between;margin-bottom:6px"><label style="margin:0">6. Text Editing: delete words, the video follows</label>
<div class="row" style="margin:0"><button class="btn-sec" onclick="loadWords()">Reload</button><button class="btn" id="teb" style="width:auto;padding:8px 14px" onclick="applyText()">Apply 0 edits</button></div></div>
<div class="muted" style="margin-bottom:8px"><b>Double-click a word</b> to delete it, or click a first word then a last word for a whole passage (red). Click red to undo. Then press Apply once. <span style="color:#fde68a">Amber = queued, rebuilding</span>; grey = cut from the video.</div>
<div id="tx" class="tbox" style="height:300px;padding:10px;font-family:system-ui,sans-serif;font-size:15px;line-height:1.7;white-space:normal">Select an episode.</div></div>

<div class="card"><label>7. Audio Export: pick passages on a topic, get one MP3 with your intro</label>
<div class="row"><input type="text" id="atp" placeholder="Topic, e.g. AI and the future of work" style="margin:0;flex:3;min-width:220px">
<input type="number" id="amin" value="10" min="1" max="120" style="margin:0;width:90px" title="Target minutes"><span class="muted">min</span>
<button class="btn-sec" id="apb" onclick="aiAudio()">AI Pick on Topic</button><button class="btn-sec" onclick="clearAudio()">Clear</button></div>
<div class="muted" style="margin-bottom:8px">Green = in the MP3. Click a first word then a last word to add a passage; click green text to remove it. <b id="atot" style="color:#3b82f6">Selected: 0:00</b></div>
<div id="ax" class="tbox" style="height:300px;padding:10px;font-family:system-ui,sans-serif;font-size:15px;line-height:1.7;white-space:normal">Select an episode.</div>
<div class="row" style="margin-top:10px"><input type="text" id="atl" placeholder="MP3 title, e.g. Monique Morrow on AI and work" style="margin:0;flex:3;min-width:220px">
<input type="checkbox" id="ain" checked style="width:auto;margin:0"><label for="ain" style="margin:0;font-weight:500">Add intro</label>
<button class="btn" style="width:auto;padding:10px 16px" onclick="exportAudio()">Export MP3</button></div>
<div class="muted">Intro used: Z:\brand\audio_intro.mp3 if it exists, otherwise Z:\youtube_long\intro.mp3. Runs on its own; other jobs keep going.</div></div>

<div class="card"><div class="row" style="justify-content:space-between;margin-bottom:8px"><label style="margin:0">8. Shorts Editor: cut stumbles, fix misheard words, rebuild</label>
<div class="row" style="margin:0"><select id="sb" style="margin:0;width:auto;min-width:260px" onchange="loadShort()"></select><button class="btn-sec" onclick="shortsList(1)">Refresh</button></div></div>
<video id="sv" controls preload="metadata" style="max-height:440px"></video>
<div class="muted" style="margin-bottom:8px">Click a word to select it and jump the player there (shift-click selects a run of words). <b>Cut / Restore</b> takes it out or puts it back. <span style="color:#fde68a">Amber</span> = cut automatically (um, repeat or stumble); <span style="color:#fca5a5">red</span> = cut by you. To fix a misheard word, select it, type the correct spelling and press Fix word. Then Apply once: only the final encode runs again, no new transcription.</div>
<div class="row"><button class="btn-sec" onclick="toggleCut()">Cut / Restore selected</button><input type="text" id="sfix" autocomplete="off" placeholder="Correct spelling of the selected word" style="margin:0;flex:1;min-width:200px"><button class="btn-sec" onclick="fixWord()">Fix word</button><button class="btn" style="width:auto;padding:8px 14px" onclick="applyShort()">Apply &amp; Rebuild</button></div>
<div id="sx" class="tbox" style="height:260px;padding:10px;font-family:system-ui,sans-serif;font-size:15px;line-height:1.7;white-space:normal">Loading...</div></div>

<div class="grid"><div class="card"><div class="row" style="justify-content:space-between;margin-bottom:8px"><label style="margin:0">Content Pack (titles, description, chapters, quotes)</label>
<button class="btn-sec" onclick="cp()">Copy</button></div><pre id="pack">Select an episode.</pre></div>
<div class="card files"><label>Recent Finished Files</label><div id="files" class="muted">...</div></div></div>
<div id="status"></div></div>
<script>
const $=id=>document.getElementById(id);let SEGS=[],pickA=null,lastCur=-1;
function st(m){const b=$('status');b.style.display='block';b.textContent=m}
function f2(s){s=Math.max(0,Math.floor(s));return [s/3600|0,(s%3600)/60|0,s%60].map(x=>String(x).padStart(2,'0')).join(':')}
function c2(s){return f2(Math.ceil(s))}
function esc(t){return t.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
let ORDER=[];
function showOrder(){ORDER=[...$('vf').files];drawOrder()}
function drawOrder(){const stitch=$('vt').value.startsWith('stitch');$('order').innerHTML=(stitch&&ORDER.length)?'<div class="muted" style="margin-top:8px">Stitch order (top plays first):</div>'+ORDER.map((f,i)=>'<div><button class="btn-sec" onclick="mv('+i+',-1)">&uarr;</button><button class="btn-sec" onclick="mv('+i+',1)">&darr;</button> '+(i+1)+'. '+esc(f.name)+'</div>').join(''):(ORDER.length>1?'<div class="muted" style="margin-top:8px">'+ORDER.length+' files: each becomes its own job.</div>':'')}
function mv(i,d){const j=i+d;if(j<0||j>=ORDER.length)return;[ORDER[i],ORDER[j]]=[ORDER[j],ORDER[i]];drawOrder()}
function send(f,hdr,label){return new Promise(res=>{const x=new XMLHttpRequest();x.open('POST','/api/upload',true);x.setRequestHeader('X-Filename',encodeURIComponent(f.name));for(const k in hdr)x.setRequestHeader(k,hdr[k]);x.upload.onprogress=e=>{if(e.lengthComputable)$('ut').textContent=label+' '+Math.round(e.loaded/e.total*100)+'%'};x.onload=()=>{let d={};try{d=JSON.parse(x.responseText)}catch(e){d={message:'Upload error'}}res(d)};x.onerror=()=>res({message:'Upload failed (connection lost)'});x.send(f)})}
async function up(){if(!ORDER.length)ORDER=[...$('vf').files];if(!ORDER.length)return alert('Choose a file');const t=$('vt').value,stitch=t.startsWith('stitch');if(stitch&&ORDER.length<2)return alert('Pick at least 2 clips to stitch');const b=$('ub');b.disabled=true;const id=Date.now().toString(36);let d={};
for(let i=0;i<ORDER.length;i++){const h={'X-Target':t,'X-Hook':encodeURIComponent($('uh').value.trim())};if(stitch){h['X-Stitch-Id']=id;h['X-Stitch-Index']=String(i);h['X-Stitch-Count']=String(ORDER.length)}d=await send(ORDER[i],h,'Uploading '+(i+1)+'/'+ORDER.length+':');if(d.error){break}}
b.disabled=false;$('ut').textContent=d.message||'';st(d.message||'');$('uh').value='';$('vf').value='';ORDER=[];drawOrder()}
async function re(){const d=await (await fetch('/api/episodes')).json();EPS=d.episodes;const s=$('ep'),cur=s.value;s.innerHTML='';d.episodes.forEach(e=>{const o=document.createElement('option');o.value=e;o.textContent=e;s.appendChild(o)});if(cur&&d.episodes.includes(cur))s.value=cur;lt()}
async function lt(){const e=$('ep').value;if(!e){$('tr').innerHTML='<div class="seg">No episodes yet.</div>';return}
$('hk').value='';$('picks').innerHTML='';loadPlayer();
const d=await (await fetch('/api/transcript?ep='+encodeURIComponent(e))).json();SEGS=d.segs||[];pickA=null;lastCur=-1;
$('tr').innerHTML=SEGS.length?SEGS.map((x,i)=>'<div class="seg" data-i="'+i+'"><b>'+f2(x[0])+'</b>'+esc(x[2])+'</div>').join(''):'<div class="seg">No transcript yet.</div>';
loadPack();loadWords()}
$('tr').addEventListener('click',ev=>{const el=ev.target.closest('.seg');if(!el||el.dataset.i===undefined)return;const i=+el.dataset.i,s=SEGS[i];$('pv').currentTime=s[0];
if(pickA===null){pickA=i;document.querySelectorAll('.seg.pick').forEach(x=>x.classList.remove('pick'));el.classList.add('pick');st('Start set at '+f2(s[0])+'. Now click the END line.');return}
const a=Math.min(pickA,i),b=Math.max(pickA,i),r=f2(SEGS[a][0])+' - '+c2(SEGS[b][1]),t=document.querySelector('input[name=tg]:checked').value;pickA=null;document.querySelectorAll('.seg.pick').forEach(x=>x.classList.remove('pick'));
if(t==='remove'){if(confirm('Remove '+r+' (master recording time) from the edited video and rebuild it?'))post('/api/remove',{ep:$('ep').value,range:r,timeline:'master'}).then(d=>st(d.message))}else if(t==='hook'){$('hk').value=r;st('Hook set: '+r)}else if(t==='keep'){$('cr').value=($('cr').value.trim()?$('cr').value.trim()+'\n':'')+r;st('Keep-range added: '+r)}else{$('cl').value=($('cl').value.trim()?$('cl').value.trim()+'\n':'')+r+' | '+t;st('Clip added: '+r+' | '+t)}});
$('pv').addEventListener('timeupdate',()=>{const t=$('pv').currentTime;let i=SEGS.findIndex(x=>t>=x[0]&&t<x[1]);if(i===lastCur)return;const segs=$('tr').children;if(lastCur>=0&&segs[lastCur])segs[lastCur].classList.remove('cur');lastCur=i;if(i>=0&&segs[i]){segs[i].classList.add('cur');if(!$('pv').paused)segs[i].scrollIntoView({block:'center'})}});
async function loadPack(){const e=$('ep').value;if(!e)return;const d=await (await fetch('/api/pack?ep='+encodeURIComponent(e))).json();$('pack').textContent=d.text||'No content pack yet. It is written automatically after the edit is built.';$('pack').dataset.hook=d.hook||''}
function aihook(){const h=$('pack').dataset.hook;if(h){$('hk').value=h;st('AI hook loaded: '+h)}else st('No AI hook for this episode yet.')}
function cp(){navigator.clipboard.writeText($('pack').textContent).then(()=>st('Content pack copied.'))}
async function at(){const e=$('ep').value;if(!e)return;const b=$('atb');b.disabled=true;b.textContent='AI reading...';st('Asking the local AI for the real start and end (waits if the GPU is busy)...');try{const d=await (await fetch('/api/autotrim?ep='+encodeURIComponent(e))).json();if(d.range){$('cr').value=d.range;st('AI detected: '+d.range+(d.reason?' ('+d.reason+')':''))}else st(d.error||'Failed')}finally{b.disabled=false;b.textContent='AI Auto-Trim Start & End'}}
async function as2(fresh){const e=$('ep').value;if(!e)return;const b=$('asb');b.disabled=true;b.textContent='AI picking...';st(fresh?'Asking the AI for new picks across the whole episode...':'Loading the AI picks and cutting...');try{const d=await (await fetch('/api/autoshorts?ep='+encodeURIComponent(e)+'&mode='+$('am').value+'&fresh='+fresh)).json();if(d.clips){$('cl').value=d.clips;$('picks').innerHTML=(d.picks||[]).map((p,i)=>'<div>'+(i+1)+'. <b style="color:#3b82f6">'+p.score+'/10</b> '+esc(p.title||'')+'<br><span>'+esc(p.reason||'')+'</span></div>').join('');st('Cutting '+d.clips.split('\n').length+' shorts now. Watch Live Jobs.')}else st(d.error||'Failed')}finally{b.disabled=false;b.textContent='AI Pick & Cut Shorts'}}
async function post(u,o){return (await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(o)})).json()}
async function sc(){const e=$('ep').value;if(!e)return;st((await post('/api/cut',{ep:e,hook:$('hk').value.trim(),cuts:$('cr').value.trim(),outro:$('ao').checked,clean:$('cf').checked})).message)}
async function po(){const e=$('ep').value;if(!e)return;st((await post('/api/outro',{ep:e})).message)}
async function scl(){const e=$('ep').value;if(!e)return;st((await post('/api/clips',{ep:e,clips:$('cl').value.trim()})).message)}
function ago(ts){const s=Date.now()/1000-ts;return s<60?'just now':s<3600?Math.round(s/60)+' min ago':Math.round(s/3600)+' h ago'}
function mins(s){if(s==null)return 'working (time estimate appears after the first run of this kind)';if(s<60)return 'under a minute left';const m=Math.round(s/60);return m<60?'~'+m+' min left':'~'+Math.floor(m/60)+' h '+(m%60)+' min left'}
function dial(p,unk){const r=22,c=2*Math.PI*r;if(unk)return '<svg width="58" height="58" viewBox="0 0 58 58"><circle cx="29" cy="29" r="'+r+'" fill="none" stroke="#27272a" stroke-width="6"/><circle class="spin" cx="29" cy="29" r="'+r+'" fill="none" stroke="#3b82f6" stroke-width="6" stroke-linecap="round" stroke-dasharray="'+(c*0.28)+' '+c+'"/><text x="29" y="33" text-anchor="middle" fill="#fff" font-size="11" font-weight="700">'+p+'%</text></svg>';return '<svg width="58" height="58" viewBox="0 0 58 58"><circle cx="29" cy="29" r="'+r+'" fill="none" stroke="#27272a" stroke-width="6"/><circle cx="29" cy="29" r="'+r+'" fill="none" stroke="#3b82f6" stroke-width="6" stroke-linecap="round" stroke-dasharray="'+c+'" stroke-dashoffset="'+(c*(1-p/100))+'" transform="rotate(-90 29 29)"/><text x="29" y="33" text-anchor="middle" fill="#fff" font-size="13" font-weight="700">'+p+'%</text></svg>'}
async function jobs(){try{const d=await (await fetch('/api/jobs')).json();$('jobs').innerHTML=d.jobs.length?d.jobs.map(j=>j.state==='running'?'<div class="job running dial">'+dial(j.pct,j.left==null)+'<div style="flex:1"><div>'+esc(j.label)+'</div><div class="t">Step '+j.step+' of '+j.total+' &middot; '+mins(j.left)+' &middot; running '+Math.max(1,Math.round((Date.now()/1000-(j.start||j.ts))/60))+' min</div></div></div>':'<div class="job '+j.state+'"><div style="display:flex;justify-content:space-between;gap:8px"><span>'+esc(j.label)+'</span><span class="muted">'+j.state+' &middot; '+ago(j.ts)+'</span></div><div class="bar"><i style="width:'+(j.state==='done'?100:Math.round(100*j.step/Math.max(1,j.total)))+'%"></i></div></div>').join(''):'No jobs yet.';
afterJobs(d);$('disk').textContent='Disk: '+d.disk.free_gb+' GB free of '+d.disk.total_gb+' GB';$('disk').style.borderColor=d.disk.free_gb<50?'#ef4444':'#2e2e32'}catch(e){}}
async function files(){try{const d=await (await fetch('/api/outputs')).json();$('files').innerHTML=d.files.length?d.files.map(f=>'<div><a href="/media?f='+encodeURIComponent(f.path)+'" target="_blank">'+esc(f.name)+'</a><span class="muted">'+f.mb+' MB &middot; '+ago(f.ts)+'</span></div>').join(''):'Nothing finished yet.'}catch(e){}}
async function fullrun(){const e=$('ep').value;if(!e)return;const h=$('hk').value.trim();if(!confirm('Run full production on '+e+'?\n\nAI trim, edited video + podcast MP3 + captions + content pack'+($('fs').checked?', then AI shorts ('+$('am').value+')':' (no shorts)')+'.'+(h?'\nCold open: '+h:'\nNo cold open.')+($('ao').checked?'\nWith outro.':'')))return;const b=$('frb');b.disabled=true;try{const d=await post('/api/fullrun',{ep:e,hook:h,outro:$('ao').checked,mode:$('am').value,clean:$('cf').checked,shorts:$('fs').checked});st(d.message)}finally{setTimeout(()=>b.disabled=false,4000)}}
async function purge(){const e=$('ep').value;if(!e)return st('Select an episode first.');const d=await (await fetch('/api/purge?ep='+encodeURIComponent(e))).json();if(!d.files||!d.files.length)return st('Nothing to purge for '+e+'.');
if(!confirm('PERMANENTLY delete '+d.files.length+' files ('+d.gb+' GB) for "'+e+'" from the Ubuntu box?\n\n'+d.files.slice(0,25).join('\n')+(d.files.length>25?'\n...and '+(d.files.length-25)+' more':'')+'\n\nThis cannot be undone. Make sure you have copied what you need to Windows first.'))return;
const r=await post('/api/purge',{ep:e,confirm:e});st(r.message);re();files();jobs()}
async function loadPlayer(){const e=$('ep').value;if(!e)return;let f='youtube_long/output/'+e+'_clean.mp4';if($('pvs').value==='edited'){const d=await (await fetch('/api/edited?ep='+encodeURIComponent(e))).json();if(!d.path){st('No edited video yet for this episode.');$('pvs').value='master'}else f=d.path}$('pv').src='/media?f='+encodeURIComponent(f)}
let RM=[null,null];
function mark(i){if($('pvs').value!=='edited'){$('pvs').value='edited';loadPlayer();return st('Switched the player to the edited video. Find the bad bit, then press Start / End.')}RM[i]=$('pv').currentTime;if(RM[0]!=null&&RM[1]!=null&&RM[1]>RM[0])$('rm').value=f2(RM[0])+' - '+c2(RM[1]);st((i?'End':'Start')+' set at '+f2(RM[i]))}
async function rmsec(){const e=$('ep').value,r=$('rm').value.trim();if(!e||!r)return st('Set the start and end first.');if(!confirm('Remove '+r+' from the edited video of '+e+' and rebuild it (video, podcast MP3, captions, chapters)?'))return;const d=await post('/api/remove',{ep:e,range:r,timeline:'edited'});st(d.message);if(d.ok){$('rm').value='';RM=[null,null]}}
let WD=[],DEL=[],ta=null;
async function loadWords(){const e=$('ep').value;if(!e)return;const d=await (await fetch('/api/words?ep='+encodeURIComponent(e))).json();WD=d.words||[];DEL=[];ta=null;const K=d.keeps||[];
const inK=(s,t)=>!K.length||K.some(k=>(s+t)/2>=k[0]&&(s+t)/2<k[1]);const Q=d.queued||[];const inQ=(s,t)=>Q.some(q=>(s+t)/2>=q[0]&&(s+t)/2<=q[1]);
$('tx').innerHTML=WD.length?WD.map((w,i)=>'<span class="tw'+(inQ(w[0],w[1])?' q':(inK(w[0],w[1])?'':' cut'))+'" data-i="'+i+'">'+esc(w[2])+'</span>').join(' '):'No word timings for this episode yet (episodes uploaded from v2.5 on have them).';cnt();loadAudio()}
function cnt(){$('teb').textContent='Apply '+DEL.length+' edit'+(DEL.length==1?'':'s')}
function paint(){document.querySelectorAll('#tx .tw').forEach(el=>{const i=+el.dataset.i;el.classList.toggle('del',DEL.some(r=>i>=r[0]&&i<=r[1]));el.classList.toggle('sel',ta===i)})}
$('tx').addEventListener('dblclick',ev=>{const el=ev.target.closest('.tw');if(!el)return;const i=+el.dataset.i;ta=null;DEL=DEL.filter(r=>!(i>=r[0]&&i<=r[1]));DEL.push([i,i]);paint();cnt();st('Marked "'+WD[i][2]+'" for deletion. Press Apply when you have marked everything.')});
$('tx').addEventListener('click',ev=>{if(ev.detail>1)return;const el=ev.target.closest('.tw');if(!el)return;const i=+el.dataset.i;if($('pvs').value!=='master'){$('pvs').value='master';loadPlayer()}$('pv').currentTime=WD[i][0];
const hit=DEL.findIndex(r=>i>=r[0]&&i<=r[1]);if(hit>=0){DEL.splice(hit,1);ta=null;paint();cnt();return}
if(ta===null){ta=i;paint();st('Now click the LAST word to delete.');return}const r=[Math.min(ta,i),Math.max(ta,i)];ta=null;DEL.push(r);paint();cnt();st('Marked: "'+WD.slice(r[0],r[1]+1).map(w=>w[2]).join(' ').slice(0,80)+'"')});
async function applyText(){const e=$('ep').value;if(!e||!DEL.length)return st('Mark some words first.');if(!confirm('Cut '+DEL.length+' marked passage(s) from the edited video and rebuild it?'))return;
const ranges=DEL.map(r=>[WD[r[0]][0],WD[r[1]][1]]);const d=await post('/api/textedit',{ep:e,ranges:ranges});st(d.message);if(d.ok){DEL=[];cnt();loadWords()}}
let AS=[],aa=null;
function mmss(t){t=Math.round(t);return Math.floor(t/60)+':'+String(t%60).padStart(2,'0')}
function drawAudio(){const box=$('ax');if(!WD.length){box.innerHTML=$('tx').innerHTML.includes('No word')?$('tx').innerHTML:'Select an episode.';return}
if(!box.dataset.ep||box.dataset.ep!==$('ep').value){box.innerHTML=WD.map((w,i)=>'<span class="tw" data-i="'+i+'">'+esc(w[2])+'</span>').join(' ');box.dataset.ep=$('ep').value}
box.querySelectorAll('.tw').forEach(el=>{const i=+el.dataset.i;el.classList.toggle('keep',AS.some(r=>i>=r[0]&&i<=r[1]));el.classList.toggle('asel',aa===i)});
const tot=AS.reduce((t,r)=>t+(WD[r[1]][1]-WD[r[0]][0]),0);$('atot').textContent='Selected: '+mmss(tot)+' of '+mmss(($('amin').value||10)*60)+' ('+AS.length+' passage'+(AS.length==1?'':'s')+')'}
function saveAudio(){const e=$('ep').value;if(e)post('/api/audiosel',{ep:e,ranges:AS.map(r=>[WD[r[0]][0],WD[r[1]][1]])})}
async function loadAudio(){const e=$('ep').value;AS=[];aa=null;$('ax').dataset.ep='';if(!e||!WD.length){drawAudio();return}const d=await (await fetch('/api/audiosel?ep='+encodeURIComponent(e))).json();setFromTimes(d.ranges||[]);drawAudio()}
function setFromTimes(rs){AS=[];rs.forEach(([s,t])=>{let a=WD.findIndex(w=>(w[0]+w[1])/2>=s),b=-1;for(let i=WD.length-1;i>=0;i--){if((WD[i][0]+WD[i][1])/2<=t){b=i;break}}if(a>=0&&b>=a)AS.push([a,b])})}
$('ax').addEventListener('click',ev=>{const el=ev.target.closest('.tw');if(!el)return;const i=+el.dataset.i;if($('pvs').value!=='master'){$('pvs').value='master';loadPlayer()}$('pv').currentTime=WD[i][0];
const hit=AS.findIndex(r=>i>=r[0]&&i<=r[1]);if(hit>=0){AS.splice(hit,1);aa=null;drawAudio();saveAudio();return}
if(aa===null){aa=i;drawAudio();st('Now click the LAST word of this passage.');return}const r=[Math.min(aa,i),Math.max(aa,i)];aa=null;AS=AS.filter(x=>x[1]<r[0]||x[0]>r[1]);AS.push(r);AS.sort((x,y)=>x[0]-y[0]);drawAudio();saveAudio()});
$('amin').addEventListener('input',drawAudio);
function clearAudio(){AS=[];aa=null;drawAudio();saveAudio()}
async function aiAudio(){const e=$('ep').value,t=$('atp').value.trim();if(!e)return;if(!t)return st('Type a topic first.');if(!WD.length)return st('This episode has no word timings yet.');const b=$('apb');b.disabled=true;b.textContent='AI reading...';st('The AI is reading the whole interview for passages about: '+t+' (a few minutes; other jobs keep running).');
try{const d=await post('/api/audiopick',{ep:e,topic:t,minutes:+$('amin').value||10});if(d.ranges&&d.ranges.length){setFromTimes(d.ranges);drawAudio();saveAudio();if(!$('atl').value)$('atl').value=e.replace(/_/g,' ')+' on '+t;st('AI picked '+d.ranges.length+' passage(s). Adjust in green, then Export MP3.')}else st(d.error||'The AI found nothing clearly about that topic. Try a broader topic.')}finally{b.disabled=false;b.textContent='AI Pick on Topic'}}
async function exportAudio(){const e=$('ep').value;if(!e||!AS.length)return st('Select some passages first.');const t=$('atl').value.trim()||(e+' audio');const d=await post('/api/audioexport',{ep:e,title:t,intro:$('ain').checked,ranges:AS.map(r=>[WD[r[0]][0],WD[r[1]][1]])});st(d.message)}
async function loadPromo(){try{const d=await (await fetch('/api/promo')).json();$('promo').innerHTML=d.slots.map(s=>'<div style="padding:8px 0;border-bottom:1px solid #222"><div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap"><span><b style="color:#f4f4f5">'+esc(s.title)+'</b> <span class="muted">'+esc(s.help)+'</span></span><span style="color:'+(s.file?'#22c55e':'#a1a1aa')+'">'+(s.file?'&#10003; '+esc(s.file)+' ('+s.secs+' s)':'not set')+'</span></div><div class="row" style="margin:6px 0 0"><input type="file" id="pf_'+s.slot+'" accept="'+s.accept+'" style="margin:0;flex:3;min-width:180px"><button class="btn-sec" onclick="upPromo(\''+s.slot+'\')">Upload</button>'+(s.file?'<button class="btn-sec" onclick="rmPromo(\''+s.slot+'\')">Remove</button>':'')+'</div></div>').join('')}catch(e){$('promo').textContent='Could not load promo clips.'}}
function upPromo(slot){const f=$('pf_'+slot).files[0];if(!f)return st('Choose a file first.');const x=new XMLHttpRequest();x.open('POST','/api/promo',true);x.setRequestHeader('X-Slot',slot);x.setRequestHeader('X-Filename',encodeURIComponent(f.name));x.upload.onprogress=e=>{if(e.lengthComputable)st('Uploading '+f.name+' '+Math.round(e.loaded/e.total*100)+'%')};x.onload=()=>{let d={};try{d=JSON.parse(x.responseText)}catch(e){d={message:'Upload error'}}st(d.message);loadPromo()};x.onerror=()=>st('Upload failed (connection lost)');x.send(f)}
async function rmPromo(slot){if(!confirm('Remove this promo clip? Future productions will run without it.'))return;const d=await post('/api/promo_remove',{slot:slot});st(d.message);loadPromo()}
async function clearJobs(){const d=await post('/api/clearjobs',{});st(d.message);jobs()}
let SH=null,SSEL=[],SANC=null,SLAST='';
async function shortsList(force){try{const d=await (await fetch('/api/shorts')).json();const s=$('sb'),cur=s.value;s.innerHTML=d.shorts.length?d.shorts.map(x=>'<option value="'+esc(x)+'">'+esc(x)+'</option>').join(''):'<option value="">No shorts yet</option>';if(cur&&d.shorts.includes(cur))s.value=cur;if(force||!SH||s.value!==SH.b)loadShort();else{const r=await (await fetch('/api/short?b='+encodeURIComponent(s.value))).json();if(!r.error&&!SH.dirty){SH=r;$('sv').src=r.out?'/media?f='+encodeURIComponent(r.out)+'&v='+r.ver:'';drawShort()}}}catch(e){}}
async function loadShort(){const b=$('sb').value;SSEL=[];SANC=null;if(!b){SH=null;$('sx').textContent='No shorts yet. Every short made from v2.9.4 on appears here.';$('sv').removeAttribute('src');return}
const d=await (await fetch('/api/short?b='+encodeURIComponent(b))).json();if(d.error){SH=null;$('sx').textContent=d.error;return}SH=d;$('sv').src=d.out?'/media?f='+encodeURIComponent(d.out)+'&v='+d.ver:'';drawShort()}
function drawShort(){if(!SH)return;$('sx').innerHTML=SH.words.map((w,i)=>{const r=SH.removed[i],f=SH.fix[i];let c='tw';if(r)c+=r==='manual'?' del':' q';if(SSEL.includes(i))c+=' sel';return '<span class="'+c+'" data-i="'+i+'" title="'+(r?'cut: '+r:(f?'fixed (was '+esc(w[2]).replace(/"/g,'')+')':''))+'"'+(f&&!r?' style="color:#86efac"':'')+'>'+esc(f||w[2])+'</span>'}).join(' ')}
$('sx').addEventListener('click',ev=>{const el=ev.target.closest('.tw');if(!el||!SH)return;const i=+el.dataset.i;if(ev.shiftKey&&SANC!==null){const a=Math.min(SANC,i),b=Math.max(SANC,i);SSEL=[];for(let k=a;k<=b;k++)SSEL.push(k)}else{SSEL=[i];SANC=i}const t=SH.words[i][3];if(t!=null)$('sv').currentTime=t;$('sfix').value=SSEL.length===1?(SH.fix[i]||SH.words[i][2]):'';drawShort()});
function toggleCut(){if(!SH||!SSEL.length)return st('Click a word first.');const all=SSEL.every(i=>SH.removed[i]);SSEL.forEach(i=>{if(all)delete SH.removed[i];else SH.removed[i]='manual'});SH.dirty=true;drawShort();st((all?'Restored ':'Marked to cut: ')+SSEL.length+' word(s). Press Apply & Rebuild when you have finished.')}
function fixWord(){if(!SH||SSEL.length!==1)return st('Click one word, type the correct spelling, then press Fix word.');const i=SSEL[0],v=$('sfix').value.trim();if(!v||v===SH.words[i][2])delete SH.fix[i];else SH.fix[i]=v;SH.dirty=true;drawShort();st('Caption word set to: '+(v||SH.words[i][2])+'. Press Apply & Rebuild when you have finished.')}
async function applyShort(){if(!SH)return st('Pick a short first.');const d=await post('/api/shortedit',{b:SH.b,removed:SH.removed,fix:SH.fix});st(d.message);if(d.ok)SH.dirty=false}
let EPS=[],SEEN=null;
function epOf(id){id=id||'';for(const p of ['yt_','cut_','full_','outro_','clips_']){if(id.startsWith(p)&&EPS.includes(id.slice(p.length)))return id.slice(p.length)}return ''}
function busy(){const a=document.activeElement;return DEL.length>0||pickA!==null||ta!==null||aa!==null||!$('pv').paused||['hk','cr','cl','rm'].some(i=>$(i).value.trim())||(a&&(a.tagName==='TEXTAREA'||(a.tagName==='INPUT'&&(a.type==='text'||a.type==='number'))))}
async function syncEps(){try{const d=await (await fetch('/api/episodes')).json();const now=d.episodes||[];if(now.join('|')===EPS.join('|'))return;EPS=now;const s=$('ep'),cur=s.value;s.innerHTML='';now.forEach(e=>{const o=document.createElement('option');o.value=e;o.textContent=e;s.appendChild(o)});if(cur&&now.includes(cur))s.value=cur;else lt()}catch(e){}}
function openEp(e,auto){if(!EPS.includes(e))return;if($('ep').value!==e){$('ep').value=e;lt()}else{loadPack();loadWords()}if(!auto)$('ready').style.display='none'}
function ready(e){const b=$('ready');b.dataset.ep=e;b.innerHTML='<span><b style="color:#22c55e">&#10003; '+esc(e)+' is ready</b> <span class="muted">edited video, podcast MP3, captions and content pack</span></span><span style="display:flex;gap:8px"><button class="btn-sec" onclick="openEp($(&quot;ready&quot;).dataset.ep)">Open</button><button class="btn-sec" onclick="$(&quot;ready&quot;).style.display=&quot;none&quot;">Dismiss</button></span>';b.style.display='flex';if(!busy())openEp(e,true)}
async function afterJobs(d){try{const box=$('jobs');if(d.jobs.length)[...box.children].forEach((el,i)=>{const e=epOf(d.jobs[i].id);if(e){el.dataset.ep=e;el.style.cursor='pointer';el.title='Click to open '+e}});
const sf=d.jobs.filter(j=>j.state==='done'&&/^(shorts|split)/.test(j.pipeline)).map(j=>j.id+':'+j.ts).join('|');if(SEEN!==null&&sf!==SLAST)shortsList(0);SLAST=sf;
const fin=d.jobs.filter(j=>j.state==='done'&&j.pipeline==='youtube');
if(SEEN===null){SEEN=new Set(fin.map(j=>j.id+':'+j.ts));return}
for(const j of fin){const k=j.id+':'+j.ts;if(SEEN.has(k))continue;SEEN.add(k);if(!epOf(j.id))await syncEps();const e=epOf(j.id);if(e)ready(e)}}catch(e){}}
$('jobs').addEventListener('click',ev=>{const el=ev.target.closest('[data-ep]');if(el)openEp(el.dataset.ep)});
re();jobs();files();loadPromo();setInterval(jobs,3000);setInterval(files,15000);setInterval(syncEps,20000);shortsList(1);
</script></body></html>"""


PROMO = [  # slot, folder, file base, kind, title, help
    ("book_intro", "brand", "audio_intro", "audio", "Book clip intro", "front of every book clip (Audio Export)"),
    ("podcast_intro", "youtube_long", "intro", "audio", "Podcast intro", "front of every podcast MP3"),
    ("midroll", "brand", "midroll", "any", "Mid-roll advert", "edited video + podcast, first pause after "
     + str(int(float(conf("MH_MIDROLL_AT", "360")) // 60)) + " min (audio only = shown over your logo card)"),
    ("outro", "youtube_long", "outro", "video", "Video outro", "end of the edited video when Append Outro is ticked"),
]
PROMO_EXT = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".mp4", ".mov", ".MP3", ".WAV", ".M4A", ".MP4", ".MOV")


def promo_files(folder, base):
    d = os.path.join(HUB, folder)
    return [os.path.join(d, base + x) for x in PROMO_EXT if os.path.isfile(os.path.join(d, base + x))]


def promo_status():
    out = []
    for slot, folder, base, kind, title, help_ in PROMO:
        fs = promo_files(folder, base)
        secs = 0
        if fs:
            try:
                secs = round(float(probe(fs[0], "format=duration", "a:0") or 0))
            except ValueError:
                secs = 0
        accept = {"audio": "audio/*,video/*", "video": "video/*", "any": "audio/*,video/*"}[kind]
        out.append({"slot": slot, "title": title, "help": help_, "accept": accept,
                    "file": os.path.join(folder, os.path.basename(fs[0])).replace("/", "\\") if fs else "", "secs": secs})
    return out


def promo_store(slot, src):
    """Convert an uploaded clip into the slot's file (audio -> MP3, video -> MP4) and replace the old one."""
    spec = next((p for p in PROMO if p[0] == slot), None)
    if not spec:
        return False, "Unknown promo slot."
    _, folder, base, kind, title, _ = spec
    d = os.path.join(HUB, folder)
    has_v = bool(probe(src, "stream=index", "v:0"))
    has_a = bool(probe(src, "stream=index", "a:0"))
    as_video = kind == "video" or (kind == "any" and has_v)
    if kind == "video" and not has_v:
        return False, f"{title} needs a video file."
    if not as_video and not has_a:
        return False, f"{title} needs a file with sound."
    tmp = os.path.join(d, f".{base}.new" + (".mp4" if as_video else ".mp3"))
    if as_video:
        r = subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", src, "-c", "copy", "-movflags", "+faststart", tmp])
        if r.returncode != 0:
            r = subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", src, "-c:v", "libx264", "-crf", "18",
                                "-preset", "fast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", tmp])
    else:
        r = subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", src, "-vn", "-c:a", "libmp3lame", "-b:a", "256k", tmp])
    if r.returncode != 0 or not os.path.isfile(tmp):
        return False, f"Could not read that file for the {title}."
    for f in promo_files(folder, base):
        os.remove(f)
    final = os.path.join(d, base + (".mp4" if as_video else ".mp3"))
    os.replace(tmp, final)
    secs = round(float(probe(final, "format=duration", "a:0") or 0))
    return True, f"{title} saved ({secs} s). Every production from now on uses it."


SHORTS_DIR = os.path.join(META, "shorts")


def shorts_list():
    try:
        fs = [f for f in os.listdir(SHORTS_DIR) if f.endswith(".json")]
    except OSError:
        return []
    fs.sort(key=lambda f: -os.path.getmtime(os.path.join(SHORTS_DIR, f)))
    return [f[:-5] for f in fs]


def short_view(base):
    d = json.load(open(os.path.join(SHORTS_DIR, base + ".json")))
    keeps = d.get("keeps") or []

    def m(t):
        o = 0.0
        for s, e in keeps:
            if s <= t < e:
                return round(o + t - s, 3)
            o += e - s
        return None
    out = d.get("out", "")
    rel = os.path.relpath(out, HUB) if out and os.path.isfile(out) else ""
    return {"b": base, "words": [[w[0], w[1], w[2], m((w[0] + w[1]) / 2)] for w in d.get("words", [])],
            "removed": d.get("removed", {}), "fix": d.get("fix", {}), "out": rel,
            "ver": int(os.path.getmtime(out)) if rel else 0}


def list_episodes():
    if not os.path.isdir(YT_OUT):
        return []
    def _mt(f):
        try:
            return os.path.getmtime(os.path.join(YT_OUT, f))
        except OSError:
            return 0
    eps = [f for f in os.listdir(YT_OUT) if f.endswith("_clean.mp4")]
    eps.sort(key=lambda f: -_mt(f))  # newest episode first
    return [f[:-10] for f in eps]


def gpu_run(args, timeout=1800):
    on_gpu = conf("MH_LLM_ON_GPU", "off").lower() == "on"
    cmd = (["flock", GPU_LOCK] if (on_gpu and shutil.which("flock")) else []) + ["python3"] + args
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def read_text(p):
    try:
        return open(p, encoding="utf-8", errors="ignore").read()
    except OSError:
        return ""


def hook_ok(text):
    r = parse_range(text)
    return bool(r) and 0 < r[1] - r[0] <= 25


def purge_list(ep):
    """Every file belonging to this episode (and not to another episode whose name starts the same way)."""
    eps = list_episodes()
    longer = [x for x in eps if x != ep and x.startswith(ep)]
    out = []
    for d in OUT_DIRS + [".meta"]:
        full = os.path.join(HUB, d)
        if not os.path.isdir(full):
            continue
        for f in os.listdir(full):
            if not (f.startswith(ep + "_") or f.startswith(ep + ".")):
                continue
            if any(f.startswith(x + "_") or f.startswith(x + ".") for x in longer):
                continue
            fp = os.path.join(full, f)
            if os.path.isfile(fp):
                out.append(fp)
    return sorted(out)


def write_trigger(fn, text):
    part = os.path.join(YT_IN, "." + fn + ".partial")
    open(part, "w").write(text)
    os.replace(part, os.path.join(YT_IN, fn))


def probe(path, entries, stream="v:0"):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", stream, "-show_entries", entries,
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    return r.stdout.strip()


def stitch_run(d, target, hook):
    """Join the uploaded clips (in the order chosen) into one video, then hand it to the shorts/split engine."""
    files = sorted(x for x in os.listdir(d) if not x.startswith("."))
    base = safe_name(os.path.splitext(files[0][3:])[0])[:60] + "_stitched"
    job = "stitch_" + base
    dst = SPLIT_IN if target == "stitch_split" else SHORTS_IN
    try:
        wh = probe(os.path.join(d, files[0]), "stream=width,height").split(",")
        portrait = len(wh) == 2 and int(wh[1]) > int(wh[0])
        W, H = (1080, 1920) if portrait else (1920, 1080)
        parts = []
        total = len(files) + 1
        media = 0.0
        for f in files:
            try:
                media += float(probe(os.path.join(d, f), "format=duration", "v:0") or 0)
            except ValueError:
                pass
        for i, f in enumerate(files):
            status(job, "stitch", i + 1, total, f"Stitching: preparing clip {i + 1}/{len(files)}", "running",
                   media if i == 0 else None)
            src, out = os.path.join(d, f), os.path.join(d, f".norm_{i:02d}.mp4")
            has_audio = bool(probe(src, "stream=index", "a:0"))
            cmd = ["ffmpeg", "-nostdin", "-y", "-i", src]
            if not has_audio:
                cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
            cmd += ["-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,"
                           "fps=30,setsar=1,format=yuv420p",
                    "-map", "0:v:0", "-map", "0:a:0" if has_audio else "1:a:0", "-shortest",
                    "-c:v", "libx264", "-crf", "16", "-preset", "veryfast", "-c:a", "aac", "-b:a", "192k",
                    "-ar", "48000", "-ac", "2", out, "-loglevel", "error"]
            if subprocess.run(cmd).returncode != 0:
                return status(job, "stitch", i + 1, total, f"Stitch failed on clip {i + 1} ({f[3:]})", "error")
            parts.append(out)
        status(job, "stitch", total, total, "Stitching: joining clips")
        lst = os.path.join(d, ".list.txt")
        open(lst, "w").write("".join(f"file '{p}'\n" for p in parts))
        set_hook_text(base, hook)
        final_part = os.path.join(dst, "." + base + ".mp4.partial")
        r = subprocess.run(["ffmpeg", "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy",
                            "-f", "mp4", final_part, "-loglevel", "error"])
        if r.returncode != 0:
            return status(job, "stitch", total, total, "Stitch failed while joining", "error")
        os.replace(final_part, os.path.join(dst, base + ".mp4"))
        status(job, "stitch", total, total, f"Stitched {len(files)} clips: {base}.mp4 is now being cut and captioned", "done")
    except Exception as ex:
        status(job, "stitch", 1, 2, f"Stitch error: {ex}", "error")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def pick_lines(picks, mode):
    auto = conf("MH_AUTO_HOOK_TEXT", "0") == "1"
    return "\n".join(f"{x['range']} | {mode}" + (f" | {x.get('title', '')}" if auto and x.get("title") else "")
                     for x in picks)


def last_outro(ep):
    try:
        return open(os.path.join(META, ep + ".last_outro")).read().strip() == "yes"
    except OSError:
        return False


def edited_path(ep):
    names = [f"{ep}_edited_with_outro.mp4", f"{ep}_edited.mp4"] if last_outro(ep) else [f"{ep}_edited.mp4", f"{ep}_edited_with_outro.mp4"]
    for n in names:
        if os.path.isfile(os.path.join(YT_OUT, n)):
            return os.path.join(YT_OUT, n)
    return ""


def remove_section(ep, r, master_time=False):
    """Cut range(s) out of the current edit by splitting its keep-ranges, then rebuild (frame-exact, fast).
    r: one (start, end) or a list of them; master_time=True means times on the full recording."""
    cuts = os.path.join(META, ep + ".last_cuts.txt")
    for pend in (os.path.join(YT_IN, f"{ep}.outro.cuts.txt"), os.path.join(YT_IN, f"{ep}.cuts.txt")):
        if os.path.isfile(pend):
            cuts = pend  # an edit is already waiting: add to it instead of replacing it
            break
    hook, keeps = read_cuts(cuts)
    if not keeps:
        return False, "Build the edited video first, then remove sections from it."
    clean = any(l.strip().upper().startswith("CLEAN:") and "on" in l.lower() for l in open(cuts, errors="ignore"))
    ranges = r if isinstance(r, list) else [r]
    drop, drop_hook = [], False
    if master_time:
        drop = list(ranges)
        if hook and any(a < hook[1] and b > hook[0] for a, b in ranges):
            drop_hook = True
    else:
        eh, ek = effective_cuts(os.path.join(META, ep))
        for a, b in ranges:
            for s0, e0, o, is_hook in timeline(eh, ek):
                lo, hi = max(a, o), min(b, o + (e0 - s0))
                if hi - lo <= 0.01:
                    continue
                if is_hook:
                    drop_hook = True
                else:
                    drop.append((s0 + lo - o, s0 + hi - o))
        if not drop and not drop_hook:
            return False, "That range is not inside the edited episode (the outro cannot be cut here)."
    new = []
    for s0, e0 in keeps:
        pieces = [(s0, e0)]
        for ds, de in drop:
            nxt = []
            for ps, pe in pieces:
                if de <= ps or ds >= pe:
                    nxt.append((ps, pe))
                    continue
                if ds > ps:
                    nxt.append((ps, ds))
                if de < pe:
                    nxt.append((de, pe))
            pieces = nxt
        new += [(ps, pe) for ps, pe in pieces if pe - ps >= 0.3]
    if not new:
        return False, "That would remove the whole episode. Nothing was changed."
    removed = sum(e - s for s, e in keeps) - sum(e - s for s, e in new) + ((hook[1] - hook[0]) if drop_hook and hook else 0)
    fmt = lambda t: f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{t % 60:06.3f}"
    lines = (["CLEAN: on"] if clean else []) + \
            ([] if (drop_hook or not hook) else [f"HOOK: {fmt(hook[0])} - {fmt(hook[1])}"]) + \
            [f"{fmt(s)} - {fmt(e)}" for s, e in new]
    fn = f"{ep}.outro.cuts.txt" if last_outro(ep) else f"{ep}.cuts.txt"
    write_trigger(fn, "\n".join(lines) + "\n")
    extra = " The cold open overlapped it, so the cold open was dropped." if drop_hook else ""
    return True, f"Removing {removed:.1f}s and rebuilding. Watch Live Jobs.{extra}"


def full_run(ep, hook, outro, mode, clean=True, shorts=False):
    job = re.sub(r"[^A-Za-z0-9._-]", "_", f"full_{ep}")
    srt = os.path.join(YT_OUT, f"{ep}_transcript.srt")
    segs = read_srt(srt)
    media = segs[-1][1] if segs else 0
    try:
        status(job, "full", 1, 3, f"Full production: AI trimming {ep}", "running", media)
        r = gpu_run([os.path.join(SCRIPTS, "ai_auto_trim.py"), srt])
        lines = r.stdout.strip().splitlines()
        rng = lines[0] if lines and " - " in lines[0] else (f"{s2ts(segs[0][0])} - {s2ts(segs[-1][1] + 1)}" if segs else "")
        if not rng:
            return status(job, "full", 1, 3, f"Full production failed: no transcript for {ep}", "error")
        open(os.path.join(META, ep + ".range"), "w").write(rng)
        spath = os.path.join(META, ep + ".shorts.json")
        if shorts:
            status(job, "full", 2, 3, f"Full production: AI picking {mode} shorts")
            gpu_run([os.path.join(SCRIPTS, "ai_pick_shorts.py"), srt, mode, "--json", spath,
                     "--count", conf("MH_SHORTS_COUNT", "3"), "--range", rng])
        status(job, "full", 3, 3, "Full production: queuing the edit build")
        fn = f"{ep}.outro.cuts.txt" if outro else f"{ep}.cuts.txt"
        write_trigger(fn, ("CLEAN: on\n" if clean else "") + (f"HOOK: {hook}\n" if hook else "") + rng + "\n")
        n = 0
        if shorts and os.path.isfile(spath):
            picks = json.load(open(spath))
            n = len(picks)
            threading.Thread(target=slice_text, args=(ep, pick_lines(picks, mode)), daemon=True).start()
        status(job, "full", 3, 3, f"Full production queued: edit ({rng})" + (f" + {n} shorts" if n else "") + " now building", "done")
    except Exception as ex:
        status(job, "full", 1, 3, f"Full production error: {ex}", "error")


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def j(self, o, code=200):
        body = json.dumps(o).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def media(self, rel, download=False):
        full = os.path.realpath(os.path.join(BASE_HUB, rel))
        if not full.startswith(BASE_HUB + os.sep) or not os.path.isfile(full):
            return self.send_error(404)
        size = os.path.getsize(full)
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if full.endswith((".srt", ".txt")):
            ctype = "text/plain; charset=utf-8"
        start, end, code = 0, size - 1, 200
        m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
            else:
                start = max(0, size - int(m.group(2)))
            end = min(end, size - 1)
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                return self.end_headers()
            code = 206
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(full)}"')
        self.end_headers()
        try:
            with open(full, "rb") as f:
                f.seek(start)
                rem = end - start + 1
                while rem > 0:
                    chunk = f.read(min(1 << 20, rem))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    rem -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        p = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(p.query)
        ep = q.get("ep", [""])[0]
        if p.path == "/":
            body = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        if p.path == "/media":
            return self.media(q.get("f", [""])[0], q.get("dl", ["0"])[0] == "1")
        if p.path == "/api/episodes":
            return self.j({"episodes": list_episodes()})
        if p.path == "/api/promo":
            return self.j({"slots": promo_status()})
        if p.path == "/api/jobs":
            jobs, now, timings = [], time.time(), load_timings()
            if os.path.isdir(JOBS):
                for f in os.listdir(JOBS):
                    if not f.endswith(".json"):
                        continue
                    fp = os.path.join(JOBS, f)
                    try:
                        d = json.load(open(fp))
                    except (OSError, ValueError):
                        continue
                    age = now - d.get("ts", 0)
                    if (d.get("state") != "running" and age > 86400) or age > 172800:
                        try:
                            os.remove(fp)
                        except OSError:
                            pass
                        continue
                    d["pct"], d["left"] = estimate(d, timings, now)
                    jobs.append(d)
            jobs.sort(key=lambda d: (d.get("state") != "running", -d.get("ts", 0)))
            du = shutil.disk_usage(BASE_HUB)
            jobs = [x for x in jobs if x.get("state") == "running"] + [x for x in jobs if x.get("state") != "running"][:4]
            return self.j({"jobs": jobs, "disk": {"free_gb": round(du.free / 1e9), "total_gb": round(du.total / 1e9)}})
        if p.path == "/api/outputs":
            files = []
            for d in OUT_DIRS:
                full = os.path.join(HUB, d)
                if not os.path.isdir(full):
                    continue
                for f in os.listdir(full):
                    if f.startswith(".") or not f.lower().endswith((".mp4", ".mp3", ".srt", ".txt")):
                        continue
                    if f.endswith(("_clean.mp4", "_nocaptions.mp4")):
                        continue
                    st = os.stat(os.path.join(full, f))
                    files.append({"name": f, "path": f"{d}/{f}", "mb": round(st.st_size / 1e6, 1), "ts": st.st_mtime})
            files.sort(key=lambda x: -x["ts"])
            return self.j({"files": files[:20]})
        if p.path == "/api/shorts":
            return self.j({"shorts": shorts_list()})
        if p.path == "/api/short":
            sb = q.get("b", [""])[0]
            if sb not in shorts_list():
                return self.j({"error": "Unknown short"})
            try:
                return self.j(short_view(sb))
            except (OSError, ValueError) as ex:
                return self.j({"error": f"Could not read this short: {ex}"})
        if ep and ep not in list_episodes():
            return self.j({"error": "Unknown episode"}, 404)
        srt = os.path.join(YT_OUT, f"{ep}_transcript.srt")
        if p.path == "/api/words":
            wp = os.path.join(YT_OUT, f"{ep}_words.srt")
            words = []
            for s0, e0, t in read_srt(wp, drop_noise=True):
                for w in t.split():
                    words.append([round(s0, 3), round(e0, 3), w])
            _, keeps = effective_cuts(os.path.join(META, ep))
            queued = []
            try:
                for a0, b0 in json.load(open(os.path.join(META, ep + ".textqueue.json"))):
                    mid = (a0 + b0) / 2
                    if any(k0 <= mid < k1 for k0, k1 in keeps):
                        queued.append([a0, b0])  # still in the current edit, so the rebuild has not happened yet
            except (OSError, ValueError):
                pass
            return self.j({"words": words, "keeps": keeps, "queued": queued})
        if p.path == "/api/audiosel":
            try:
                return self.j({"ranges": json.load(open(os.path.join(META, ep + ".audiosel.json")))})
            except (OSError, ValueError):
                return self.j({"ranges": []})
        if p.path == "/api/edited":
            path = edited_path(ep)
            return self.j({"path": os.path.relpath(path, HUB) if path else ""})
        if p.path == "/api/purge":
            fl = purge_list(ep)
            return self.j({"files": [os.path.relpath(f, HUB) for f in fl],
                           "gb": round(sum(os.path.getsize(f) for f in fl) / 1e9, 2)})
        if p.path == "/api/transcript":
            return self.j({"segs": [[round(s, 2), round(e, 2), t] for s, e, t in read_srt(srt)]})
        if p.path == "/api/pack":
            hook = ""
            try:
                hook = json.load(open(os.path.join(META, ep + ".pack.json"))).get("hook", "")
            except (OSError, ValueError):
                pass
            return self.j({"text": read_text(os.path.join(YT_OUT, f"{ep}_content_pack.txt")), "hook": hook})
        if p.path == "/api/autotrim":
            try:
                r = gpu_run([os.path.join(SCRIPTS, "ai_auto_trim.py"), srt])
                lines = r.stdout.strip().splitlines()
                if lines and " - " in lines[0]:
                    return self.j({"range": lines[0], "reason": lines[1] if len(lines) > 1 else ""})
                return self.j({"error": "AI returned nothing. " + r.stderr[-300:]})
            except Exception as ex:
                return self.j({"error": str(ex)})
        if p.path == "/api/autoshorts":
            mode = q.get("mode", ["split"])[0]
            mode = mode if mode in ("split", "solo") else "split"
            spath = os.path.join(META, ep + ".shorts.json")
            try:
                if q.get("fresh", ["0"])[0] == "1" or not os.path.isfile(spath):
                    args = [os.path.join(SCRIPTS, "ai_pick_shorts.py"), srt, mode, "--json", spath,
                            "--count", conf("MH_SHORTS_COUNT", "3")]
                    rng = read_text(os.path.join(META, ep + ".range")).strip()
                    if rng:
                        args += ["--range", rng]
                    r = gpu_run(args)
                    if not r.stdout.strip():
                        return self.j({"error": "AI returned no clips. " + r.stderr[-300:]})
                picks = json.load(open(spath))
                clips = pick_lines(picks, mode)
                threading.Thread(target=slice_text, args=(ep, clips), daemon=True).start()
                return self.j({"clips": clips, "picks": picks})
            except Exception as ex:
                return self.j({"error": str(ex)})
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path == "/api/clearjobs":
            n = 0
            if os.path.isdir(JOBS):
                for f in os.listdir(JOBS):
                    fp = os.path.join(JOBS, f)
                    try:
                        if f.endswith(".json") and json.load(open(fp)).get("state") != "running":
                            os.remove(fp)
                            n += 1
                    except (OSError, ValueError):
                        pass
            return self.j({"message": f"Cleared {n} finished job(s)."})
        if self.path == "/api/promo":
            slot = self.headers.get("X-Slot", "")
            fn = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(urllib.parse.unquote(self.headers.get("X-Filename", "clip"))))
            os.makedirs(os.path.join(HUB, ".stitch"), exist_ok=True)
            part = os.path.join(HUB, ".stitch", ".promo_" + fn)
            rem = int(self.headers.get("Content-Length", 0))
            with open(part, "wb") as f:
                while rem > 0:
                    c = self.rfile.read(min(1048576, rem))
                    if not c:
                        break
                    f.write(c)
                    rem -= len(c)
            try:
                if rem > 0:
                    return self.j({"message": "Upload was interrupted. Please try again."})
                ok, msg = promo_store(slot, part)
                return self.j({"message": msg, "ok": ok})
            finally:
                try:
                    os.remove(part)
                except OSError:
                    pass
        if self.path == "/api/promo_remove":
            try:
                b = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            except ValueError:
                b = {}
            spec = next((x for x in PROMO if x[0] == b.get("slot")), None)
            if not spec:
                return self.j({"message": "Unknown promo slot."})
            for f in promo_files(spec[1], spec[2]):
                os.remove(f)
            return self.j({"message": f"{spec[4]} removed."})
        if self.path == "/api/upload":
            fn = os.path.basename(urllib.parse.unquote(self.headers.get("X-Filename", "upload.mp4")))
            fn = re.sub(r"[^A-Za-z0-9._-]", "_", fn).lstrip(".") or "upload.mp4"
            target = self.headers.get("X-Target", "youtube")
            hook = urllib.parse.unquote(self.headers.get("X-Hook", "")).strip()
            sid = re.sub(r"[^A-Za-z0-9]", "", self.headers.get("X-Stitch-Id", ""))[:20]
            if target.startswith("stitch") and sid:
                return self.stitch_upload(fn, target, hook, sid)
            dst = TARGETS.get(target, YT_IN)
            if dst in (SHORTS_IN, SPLIT_IN):
                set_hook_text(os.path.splitext(fn)[0], hook)
            rem = int(self.headers.get("Content-Length", 0))
            part = os.path.join(dst, "." + fn + ".partial")  # same disk, hidden from the watchers
            with open(part, "wb") as f:
                while rem > 0:
                    c = self.rfile.read(min(1048576, rem))
                    if not c:
                        break
                    f.write(c)
                    rem -= len(c)
            if rem > 0:
                os.remove(part)
                return self.j({"message": f"Upload of {fn} was interrupted. Please try again."})
            os.replace(part, os.path.join(dst, fn))
            return self.j({"message": f"Uploaded {fn}. Processing has started; watch Live Jobs."})
        try:
            b = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        except ValueError:
            return self.j({"message": "Bad request"}, 400)
        if self.path == "/api/shortedit":
            return self.short_edit(b)
        ep = b.get("ep", "")
        if ep not in list_episodes():
            return self.j({"message": "Unknown episode"}, 404)
        if self.path == "/api/purge":
            if b.get("confirm") != ep:
                return self.j({"message": "Purge not confirmed."})
            n = 0
            for f in purge_list(ep):
                try:
                    os.remove(f)
                    n += 1
                except OSError:
                    pass
            return self.j({"message": f"Purged {n} files for {ep}."})
        if self.path == "/api/audiosel":
            rs = [[float(a0), float(b0)] for a0, b0 in (b.get("ranges") or []) if float(b0) > float(a0)]
            json.dump(rs, open(os.path.join(META, ep + ".audiosel.json"), "w"))
            return self.j({"ok": True})
        if self.path == "/api/audiopick":
            topic = " ".join(str(b.get("topic", "")).split())[:200]
            if not topic:
                return self.j({"error": "Type a topic first."})
            try:
                minutes = max(1.0, min(120.0, float(b.get("minutes") or 10)))
            except (TypeError, ValueError):
                minutes = 10.0
            args = [os.path.join(SCRIPTS, "ai_pick_audio.py"), os.path.join(YT_OUT, f"{ep}_transcript.srt"), topic, str(minutes)]
            rng = read_text(os.path.join(META, ep + ".range")).strip()
            if rng:
                args += ["--range", rng]
            try:
                r = gpu_run(args)
                picks = json.loads(r.stdout.strip() or "[]")
                return self.j({"ranges": [[p_["start"], p_["end"]] for p_ in picks], "picks": picks})
            except Exception as ex:
                return self.j({"error": f"AI pick failed: {ex}"})
        if self.path == "/api/audioexport":
            rs = [[float(a0), float(b0)] for a0, b0 in (b.get("ranges") or []) if float(b0) > float(a0)]
            if not rs:
                return self.j({"message": "Select some passages first."})
            title = " ".join(str(b.get("title", "")).split())[:120] or f"{ep} audio"
            cmd = ["python3", os.path.join(SCRIPTS, "audio_export.py"), ep, title, json.dumps(rs),
                   "--intro", "on" if b.get("intro", True) else "off"]
            threading.Thread(target=subprocess.run, args=(cmd,), kwargs={"capture_output": True}, daemon=True).start()
            mins = sum(e_ - s_ for s_, e_ in rs) / 60
            return self.j({"message": f"Exporting '{title}' ({mins:.1f} min). It will be in Z:\\podcast_audio\\output when the dial finishes."})
        if self.path == "/api/textedit":
            rs = []
            for r in b.get("ranges") or []:
                try:
                    a0, b0 = float(r[0]), float(r[1])
                    if b0 > a0:
                        rs.append((max(0.0, a0 - 0.02), b0 + 0.02))
                except (TypeError, ValueError, IndexError):
                    pass
            if not rs:
                return self.j({"message": "Nothing marked."})
            ok, msg = remove_section(ep, rs, True)
            if ok:
                qp = os.path.join(META, ep + ".textqueue.json")
                try:
                    q = json.load(open(qp))
                except (OSError, ValueError):
                    q = []
                json.dump(q + [list(r_) for r_ in rs], open(qp, "w"))
            return self.j({"message": msg, "ok": ok})
        if self.path == "/api/remove":
            r = parse_range(b.get("range", ""))
            if not r:
                return self.j({"message": "Type the section as HH:MM:SS - HH:MM:SS."})
            ok, msg = remove_section(ep, r, b.get("timeline") == "master")
            return self.j({"message": msg, "ok": ok})
        if self.path == "/api/fullrun":
            hook = (b.get("hook") or "").strip()
            if hook and not hook_ok(hook):
                return self.j({"message": "Cold open must be a valid range of 25 seconds or less. Nothing was started."})
            mode = b.get("mode") if b.get("mode") in ("split", "solo") else "split"
            threading.Thread(target=full_run, args=(ep, hook, bool(b.get("outro")), mode, bool(b.get("clean", True)),
                                                    bool(b.get("shorts", False))), daemon=True).start()
            return self.j({"message": f"Full production started for {ep}. Watch the dial in Live Jobs."})
        if self.path == "/api/cut":
            ls = (["CLEAN: on"] if b.get("clean") else []) + ([f"HOOK: {b['hook']}"] if b.get("hook") else []) + \
                 ([b["cuts"]] if b.get("cuts") else [])
            if b.get("hook") and not hook_ok(b["hook"]):
                return self.j({"message": "Cold open must be a valid range of 25 seconds or less. Nothing was dispatched."})
            if not b.get("cuts"):
                return self.j({"message": "Add at least one keep-range first."})
            fn = f"{ep}.outro.cuts.txt" if b.get("outro") else f"{ep}.cuts.txt"
            self.drop(fn, "\n".join(ls) + "\n")
            return self.j({"message": f"Dispatched {fn}. Building edited video, podcast MP3, captions and chapters now."})
        if self.path == "/api/outro":
            self.drop(f"{ep}.outro.txt", "outro\n")
            return self.j({"message": f"Dispatched {ep}.outro.txt. Attaching outro.mp4 now."})
        if self.path == "/api/clips":
            threading.Thread(target=slice_text, args=(ep, b.get("clips", "")), daemon=True).start()
            return self.j({"message": "Slicing clips now. Watch Live Jobs."})
        self.send_response(404)
        self.end_headers()

    def stitch_upload(self, fn, target, hook, sid):
        try:
            idx = int(self.headers.get("X-Stitch-Index", "0"))
            count = int(self.headers.get("X-Stitch-Count", "1"))
        except ValueError:
            return self.j({"message": "Bad stitch request", "error": 1}, 400)
        d = os.path.join(HUB, ".stitch", sid)
        os.makedirs(d, exist_ok=True)
        rem = int(self.headers.get("Content-Length", 0))
        part = os.path.join(d, f".{idx:02d}.partial")
        with open(part, "wb") as f:
            while rem > 0:
                c = self.rfile.read(min(1048576, rem))
                if not c:
                    break
                f.write(c)
                rem -= len(c)
        if rem > 0:
            os.remove(part)
            return self.j({"message": f"Upload of {fn} was interrupted. Please try again.", "error": 1})
        os.replace(part, os.path.join(d, f"{idx:02d}_{fn}"))
        have = [x for x in os.listdir(d) if not x.startswith(".")]
        if len(have) < count:
            return self.j({"message": f"Received clip {idx + 1} of {count}."})
        threading.Thread(target=stitch_run, args=(d, target, hook), daemon=True).start()
        return self.j({"message": f"All {count} clips received. Stitching them into one short now; watch Live Jobs."})

    def short_edit(self, b):
        base = b.get("b", "")
        if base not in shorts_list():
            return self.j({"message": "Unknown short."})
        p = os.path.join(SHORTS_DIR, base + ".json")
        d = json.load(open(p))
        n = len(d.get("words", []))
        rem, fix = {}, {}
        for k, v in (b.get("removed") or {}).items():
            try:
                i = int(k)
            except ValueError:
                continue
            if 0 <= i < n:
                rem[str(i)] = re.sub(r"[^a-z]", "", str(v).lower())[:12] or "manual"
        for k, v in (b.get("fix") or {}).items():
            try:
                i = int(k)
            except ValueError:
                continue
            v = " ".join(str(v).split())[:40]
            if 0 <= i < n and v:
                fix[str(i)] = v
        if n and len(rem) >= n:
            return self.j({"message": "That would cut every word. Nothing was changed."})
        d["removed"], d["fix"] = rem, fix
        with open(p + ".tmp", "w") as f:
            json.dump(d, f)
        os.replace(p + ".tmp", p)
        lay = d.get("layout", "solo")
        cmd = ["python3", os.path.join(SCRIPTS, "shorts_cut.py"), base, "--layout", lay, "--out", d["out"],
               "--pipe", "shorts" if lay == "solo" else "split"] + (["--srt-out", d["srt_out"]] if d.get("srt_out") else [])
        threading.Thread(target=subprocess.run, args=(cmd,), kwargs={"capture_output": True}, daemon=True).start()
        return self.j({"ok": True, "message": f"Rebuilding {base} with your changes. Watch Live Jobs; the player reloads when it is done."})

    def drop(self, fn, text):
        write_trigger(fn, text)


class S(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with S(("0.0.0.0", PORT), H) as httpd:
        httpd.serve_forever()
