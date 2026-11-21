import os, datetime, sqlite3, subprocess, shutil, uuid, json, re, ipaddress, socket, threading, time, math, wave, tempfile, zipfile
from pathlib import Path
from urllib.parse import urlparse
import requests
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data'; MEDIA=DATA/'media'; CLIPS=DATA/'clips'
CONFIG=DATA/'settings.json'
def settings():
 try:return json.loads(CONFIG.read_text(encoding='utf-8'))
 except (OSError,ValueError):return {}
def media_folder():
 target=settings().get('media_folder')
 return Path(target).expanduser().resolve() if target else MEDIA
for p in (DATA,MEDIA,CLIPS): p.mkdir(parents=True,exist_ok=True)
DB=DATA/'library.sqlite3'
JOBS={}
JOB_LOCK=threading.Lock()
app=FastAPI(title='ClipForge Local')
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')

def db():
 c=sqlite3.connect(DB);c.row_factory=sqlite3.Row;return c
with db() as c:
 c.execute('CREATE TABLE IF NOT EXISTS sources (id TEXT PRIMARY KEY,title TEXT,path TEXT,url TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP,transcript TEXT DEFAULT "")')
 c.execute('CREATE TABLE IF NOT EXISTS clips (id TEXT PRIMARY KEY,source_id TEXT,title TEXT,path TEXT,start REAL,end REAL,tags TEXT DEFAULT "",created TEXT DEFAULT CURRENT_TIMESTAMP)')

# Backup the existing database before any v1.6 schema migration or path update.
# SQLite online backup is safe even if the source DB uses WAL mode.
BACKUP_DIR=DATA/'backups'
BACKUP_DIR.mkdir(parents=True,exist_ok=True)
def backup_database(reason='startup'):
 stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
 dest=BACKUP_DIR/f'library_{reason}_{stamp}.sqlite3'
 with sqlite3.connect(DB) as src, sqlite3.connect(dest) as target:
  src.backup(target)
 return dest

def repair_library_paths():
 fixed=0; unresolved=[]
 with db() as c:
  changes=[]
  for table,folder in [('sources','media'),('clips','clips')]:
   for record in c.execute(f'SELECT id,path FROM {table}').fetchall():
    old=record['path'] or ''
    if old and Path(old).is_file():continue
    filename=old.replace('\\','/').rsplit('/',1)[-1]
    candidates=[DATA/folder/filename]
    if table=='sources':candidates.append(media_folder()/filename)
    replacement=next((str(f.resolve()) for f in candidates if filename and f.is_file()),None)
    if replacement:changes.append((table,record['id'],old,replacement))
    else:unresolved.append({'table':table,'id':record['id'],'filename':filename})
  if changes:
   backup_database('before_repair')
   for table,uid,old,new in changes:
    c.execute(f'UPDATE {table} SET path=? WHERE id=? AND path=?',(new,uid,old))
   fixed=len(changes)
 return {'repaired':fixed,'unresolved':unresolved}

# This runs once per process. Startup failure must not silently modify a library.
backup_database('before_v16')
with db() as c:
 c.execute('CREATE TABLE IF NOT EXISTS soundboard_profiles (name TEXT PRIMARY KEY, clip_ids TEXT NOT NULL DEFAULT "[]")')
 c.execute('CREATE TABLE IF NOT EXISTS soundboard_pro (name TEXT PRIMARY KEY, configuration TEXT NOT NULL)')
REPAIR_REPORT=repair_library_paths()

@app.get('/api/library/health')
def library_health():
 report={'repaired_on_startup':REPAIR_REPORT['repaired'],'sources':{'total':0,'missing':[]},'clips':{'total':0,'missing':[]},'backup_count':len(list(BACKUP_DIR.glob('library_*.sqlite3')))}
 with db() as c:
  for table in ('sources','clips'):
   records=c.execute(f'SELECT id,title,path FROM {table}').fetchall()
   report[table]['total']=len(records)
   report[table]['missing']=[{'id':r['id'],'title':r['title'],'filename':(r['path'] or '').replace('\\','/').rsplit('/',1)[-1]} for r in records if not r['path'] or not Path(r['path']).is_file()]
 return report

@app.post('/api/library/health/repair')
def health_repair():
 global REPAIR_REPORT
 REPAIR_REPORT=repair_library_paths()
 return {'repair':REPAIR_REPORT,'health':library_health()}


@app.get('/api/soundboard-pro')
def soundboard_pro_list():
 with db() as c:return {'profiles':[{'name':r['name'],**json.loads(r['configuration'])} for r in c.execute('SELECT name,configuration FROM soundboard_pro ORDER BY name')]}

@app.put('/api/soundboard-pro/{name}')
def soundboard_pro_save(name:str,payload:dict):
 name=name.strip()[:80]
 if not name:raise HTTPException(400,'Profile name required')
 pages=payload.get('pages')
 if not isinstance(pages,list) or not 1<=len(pages)<=12:raise HTTPException(400,'Profiles need 1–12 pages')
 known={r['id'] for r in get_library_clips()}
 clean=[]
 for page in pages:
  if not isinstance(page,dict):raise HTTPException(400,'Invalid page')
  slots=page.get('slots',[])
  if not isinstance(slots,list) or len(slots)!=24:raise HTTPException(400,'Each page needs 24 pads')
  validated=[]
  for slot in slots:
   if not isinstance(slot,dict):raise HTTPException(400,'Invalid pad')
   uid=slot.get('clip_id') or None
   if uid is not None and uid not in known:raise HTTPException(400,'A pad references a missing clip')
   try:volume=float(slot.get('volume',1))
   except (TypeError,ValueError):raise HTTPException(400,'Invalid pad volume')
   if not 0<=volume<=1:raise HTTPException(400,'Pad volume must be 0–1')
   color=str(slot.get('color','#2b3e66'))
   if not re.fullmatch(r'#[0-9a-fA-F]{6}',color):raise HTTPException(400,'Invalid pad color')
   hotkey=str(slot.get('hotkey',''))[:60]
   if hotkey and not re.fullmatch(r'(Ctrl\+|Alt\+|Shift\+){0,3}(Key[A-Z]|Digit[0-9]|F(?:[1-9]|1[0-2]))',hotkey):raise HTTPException(400,'Invalid hotkey')
   mode=str(slot.get('mode','toggle'))
   if mode not in ('toggle','oneshot','loop'):raise HTTPException(400,'Invalid playback mode')
   validated.append({'clip_id':uid,'label':str(slot.get('label',''))[:70], 'volume':volume,'color':color,'hotkey':hotkey,'mode':mode})
  clean.append({'name':str(page.get('name','Page'))[:60],'slots':validated})
 with db() as c:c.execute('INSERT INTO soundboard_pro(name,configuration) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET configuration=excluded.configuration',(name,json.dumps({'pages':clean})))
 return {'ok':True}

@app.delete('/api/soundboard-pro/{name}')
def soundboard_pro_delete(name:str):
 with db() as c:c.execute('DELETE FROM soundboard_pro WHERE name=?',(name,))
 return {'ok':True}

def ff(*args):
 if not shutil.which('ffmpeg'): raise HTTPException(503,'FFmpeg not installed or not in PATH')
 p=subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y',*map(str,args)],capture_output=True,text=True)
 if p.returncode: raise HTTPException(400,p.stderr[-1200:])

def row(table,id):
 with db() as c: r=c.execute(f'SELECT * FROM {table} WHERE id=?',(id,)).fetchone()
 if not r:raise HTTPException(404,'Not found')
 return dict(r)

@app.get('/')
def home():return FileResponse(ROOT/'static'/'index.html')
@app.get('/api/library')
def library():
 with db() as c:return {'sources':[dict(x) for x in c.execute('SELECT id,title,url,created,transcript FROM sources ORDER BY created DESC')], 'clips':[dict(x) for x in c.execute('SELECT id,source_id,title,start,end,tags,created FROM clips ORDER BY created DESC')]}

@app.get('/api/source/{source_id}/waveform')
def waveform(source_id: str):
 import array, math
 source = row('sources', source_id)
 if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
  raise HTTPException(503, 'Both ffmpeg.exe and ffprobe.exe must be on PATH; restart ClipForge after installation')
 probe = subprocess.run(['ffprobe','-v','error','-show_entries','format=duration',
  '-of','default=noprint_wrappers=1:nokey=1',source['path']],capture_output=True,text=True)
 try: duration = float(probe.stdout.strip())
 except (ValueError, TypeError): raise HTTPException(400, 'Could not read audio duration: '+probe.stderr[-300:])
 if not math.isfinite(duration) or duration<=0: raise HTTPException(400,'Invalid audio duration')
 # Real decoded audio, not a generated/synthetic waveform. Fixed time windows.
 rate=4000; bins=1200
 window=max(1,math.ceil(duration*rate/bins))
 cmd=['ffmpeg','-hide_banner','-v','error','-i',source['path'],'-map','0:a:0',
      '-vn','-ac','1','-ar',str(rate),'-f','s16le','-acodec','pcm_s16le','pipe:1']
 p=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 peaks=[]; carry=b''; failed=False
 try:
  while True:
   chunk=p.stdout.read(window*2)
   if not chunk: break
   carry+=chunk
   take=(len(carry)//(window*2))*(window*2)
   for offset in range(0,take,window*2):
    samples=array.array('h');samples.frombytes(carry[offset:offset+window*2]);
    peaks.append(round(max(abs(v) for v in samples)/32768,5))
   carry=carry[take:]
  if len(carry)>=2:
   samples=array.array('h');samples.frombytes(carry[:len(carry)//2*2]);
   peaks.append(round(max(abs(v) for v in samples)/32768,5))
 finally:
  p.stdout.close()
  stderr=p.stderr.read().decode('utf-8','replace')[-700:]
  p.stderr.close()
  rc=p.wait()
 if rc!=0:raise HTTPException(400,'Audio decoding failed: '+stderr)
 if not peaks:raise HTTPException(400,'No decoded audio samples found')
 return {'duration':duration,'peaks':peaks,'source':'decoded PCM audio','sample_rate':rate}

@app.post('/api/upload')
async def upload(file:UploadFile=File(...),title:str=Form('')):
 id=uuid.uuid4().hex; folder=media_folder();folder.mkdir(parents=True,exist_ok=True);raw=folder/(id+'_input'+Path(file.filename or '').suffix.lower()[:10]);size=0
 with raw.open('wb') as out:
  while chunk:=await file.read(1024*1024):
   size+=len(chunk)
   if size>500*1024*1024:raw.unlink(missing_ok=True);raise HTTPException(413,'Maximum upload is 500 MB')
   out.write(chunk)
 path=folder/(id+'.mp3')
 try:ff('-i',raw,'-vn','-ac','2','-codec:a','libmp3lame','-q:a','3',path)
 finally:raw.unlink(missing_ok=True)
 with db() as c:c.execute('INSERT INTO sources(id,title,path,url) VALUES(?,?,?,?)',(id,(title or file.filename or 'Uploaded audio')[:200],str(path),''))
 return {'id':id}

def safe_url(url):
 p=urlparse(url)
 if p.scheme!='https' or not p.hostname or p.username or p.password:raise HTTPException(400,'Only public HTTPS direct media URLs are supported')
 host=p.hostname.lower()
 if host in ('localhost',) or host.endswith(('.local','.internal')):raise HTTPException(400,'Private host blocked')
 try:
  addresses=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
  if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):raise HTTPException(400,'Non-public address blocked')
 except socket.gaierror:raise HTTPException(400,'Host not found')
 return url

@app.post('/api/import-url')
def import_url(payload:dict):
 url=safe_url(str(payload.get('url','')))
 if not re.search(r'\.(mp3|wav|ogg|m4a|flac|mp4|webm)(\?|$)',url,re.I):raise HTTPException(400,'Use a direct media file URL, not a video/watch page')
 id=uuid.uuid4().hex;folder=media_folder();folder.mkdir(parents=True,exist_ok=True);raw=folder/(id+'_download');dest=folder/(id+'.mp3')
 try:
  with requests.get(url,stream=True,timeout=(8,30),allow_redirects=False) as r:
   if 300<=r.status_code<400:raise HTTPException(400,'Redirects not supported for safety; use the final direct file URL')
   r.raise_for_status();total=0
   with raw.open('wb') as out:
    for chunk in r.iter_content(65536):
     total+=len(chunk)
     if total>500*1024*1024:raise HTTPException(413,'Maximum download is 500 MB')
     out.write(chunk)
  ff('-i',raw,'-vn','-ac','2','-codec:a','libmp3lame','-q:a','3',dest)
 finally:raw.unlink(missing_ok=True)
 with db() as c:c.execute('INSERT INTO sources(id,title,path,url) VALUES(?,?,?,?)',(id,str(payload.get('title') or url.split('/')[-1])[:200],str(dest),url))
 return {'id':id}

def youtube_video_id(raw):
 p=urlparse(raw.strip())
 if p.scheme!='https' or p.username or p.password or p.port not in (None,443):
  raise HTTPException(400,'Use an HTTPS YouTube video URL')
 host=(p.hostname or '').lower()
 from urllib.parse import parse_qs
 if host in ('youtu.be','www.youtu.be'):
  candidate=p.path.strip('/').split('/')[0]
 elif host in ('youtube.com','www.youtube.com','m.youtube.com','music.youtube.com'):
  if p.path=='/watch':candidate=parse_qs(p.query).get('v',[''])[0]
  else:
   m=re.fullmatch(r'/(?:shorts|live|embed)/([A-Za-z0-9_-]{11})/?',p.path)
   candidate=m.group(1) if m else ''
 else:raise HTTPException(400,'This importer accepts YouTube video links only')
 if not re.fullmatch(r'[A-Za-z0-9_-]{11}',candidate):raise HTTPException(400,'Invalid YouTube video ID')
 return candidate

@app.post('/api/import-youtube')
def import_youtube(payload:dict):
 if payload.get('authorized') is not True:
  raise HTTPException(400,'Confirm you own or are authorized to download and process this video')
 video_id=youtube_video_id(str(payload.get('url','')))
 if not shutil.which('ffmpeg'):
  raise HTTPException(503,'FFmpeg must be installed and in PATH')
 try:import yt_dlp
 except ImportError:raise HTTPException(503,'yt-dlp is missing: run .venv\\Scripts\\python -m pip install yt-dlp')
 uid=uuid.uuid4().hex
 folder=media_folder();folder.mkdir(parents=True,exist_ok=True)
 template=str(folder/(uid+'_yt.%(ext)s'))
 canonical='https://www.youtube.com/watch?v='+video_id
 opts={'format':'bestaudio/best','outtmpl':template,'noplaylist':True,'quiet':True,
       'no_warnings':True,'socket_timeout':20,'retries':2,'fragment_retries':2,
       'max_filesize':500*1024*1024,'ignoreerrors':False,'restrictfilenames':True,
       'cachedir':False,'windowsfilenames':True}
 try:
  with yt_dlp.YoutubeDL(opts) as ydl:
   info=ydl.extract_info(canonical,download=False)
   if not info or info.get('is_live') or info.get('live_status') in ('is_live','is_upcoming'):
    raise HTTPException(400,'Live streams are not supported')
   if info.get('duration') and info['duration']>4*3600:
    raise HTTPException(400,'Maximum supported duration is four hours')
  # Separate process enforces a hard timeout for the download.
  import sys
  cmd=[sys.executable,'-m','yt_dlp','--no-playlist','--no-progress',
       '--no-cache-dir','--no-warnings','--socket-timeout','20',
       '--retries','2','--fragment-retries','2','--max-filesize','500M',
       '-f','bestaudio/best','-o',template,canonical]
  try:r=subprocess.run(cmd,capture_output=True,text=True,timeout=240)
  except subprocess.TimeoutExpired:raise HTTPException(408,'YouTube download timed out after four minutes')
  if r.returncode:
   raise HTTPException(400,'YouTube download failed. The video may be restricted, unavailable, or YouTube may have changed its delivery method. Update yt-dlp and try again. Details: '+(r.stderr or r.stdout)[-450:])
  candidates=list(folder.glob(uid+'_yt.*'))
  if len(candidates)!=1:raise HTTPException(400,'Downloaded audio file was not found')
  raw=candidates[0]
  if raw.stat().st_size>500*1024*1024:raise HTTPException(413,'Media exceeds 500 MB')
  dest=folder/(uid+'.mp3')
  ff('-i',raw,'-vn','-ac','2','-codec:a','libmp3lame','-q:a','3',dest)
  title=str(payload.get('title') or info.get('title') or 'YouTube recording')[:200]
  with db() as c:c.execute('INSERT INTO sources(id,title,path,url) VALUES(?,?,?,?)',(uid,title,str(dest),canonical))
  return {'id':uid,'title':title}
 finally:
  for f in folder.glob(uid+'_yt.*'):f.unlink(missing_ok=True)

@app.get('/api/source/{id}/audio')
def source_audio(id:str):return FileResponse(row('sources',id)['path'],media_type='audio/mpeg')
@app.delete('/api/source/{id}')
def delete_source(id:str, delete_audio:bool=True):
 # Source audio deletion is deliberately limited to ClipForge-managed MP3s.
 # Independently exported clips and soundboard assignments are never deleted here.
 source=row('sources',id)
 path=Path(source['path'])
 staged=None
 with db() as c:
  if delete_audio and path.exists():
   resolved=path.resolve()
   allowed_roots=[MEDIA.resolve(),media_folder().resolve()]
   if not any(resolved.is_relative_to(root) for root in allowed_roots):
    raise HTTPException(400,'Audio is outside ClipForge-managed media folders; file not deleted. Change the media location or remove the library entry only.')
   if resolved.suffix.lower()!='.mp3' or resolved.stem!=id:
    raise HTTPException(400,'Audio is not a standard ClipForge-managed source; file not deleted.')
   if not resolved.is_file():
    raise HTTPException(400,'Audio path is not a regular file.')
   other=c.execute('SELECT COUNT(*) FROM sources WHERE id<>? AND path=?',(id,str(path))).fetchone()[0]
   if other:raise HTTPException(409,'Another source uses this audio file; file not deleted.')
  backup_database('before_source_delete')
  # Rename before database mutation so a locked/unwritable file cannot orphan the row.
  if delete_audio and path.exists():
   staged=path.with_name(path.name+'.deleting_'+uuid.uuid4().hex)
   try:path.rename(staged)
   except OSError as exc:raise HTTPException(500,'Could not remove audio file; source remains in library: '+str(exc))
  try:
   c.execute('DELETE FROM sources WHERE id=?',(id,))
   c.commit()
  except Exception:
   if staged and staged.exists():staged.rename(path)
   raise
 if staged:
  try:staged.unlink()
  except OSError as exc:
   # The original path is gone, but the staged file remains for manual recovery.
   raise HTTPException(500,'Library entry removed, but disk cleanup failed. Remaining file: '+str(staged)+'; '+str(exc))
 return {'ok':True,'removed_from_library':True,'audio_deleted':bool(staged),'audio_already_missing':bool(delete_audio and not staged),'saved_clips_preserved':True}

@app.get('/api/clip/{id}/audio')
def clip_audio(id:str):
 clip=row('clips',id);path=Path(clip['path']);return FileResponse(path,media_type='audio/wav' if path.suffix=='.wav' else 'audio/mpeg',content_disposition_type='inline')

@app.post('/api/clips/batch')
def batch(payload:dict):
 src=row('sources',str(payload.get('source_id','')));items=payload.get('clips',[])
 if not isinstance(items,list) or not 1<=len(items)<=50:raise HTTPException(400,'Submit 1–50 clips')
 created=[]
 preset=str(payload.get('preset','mp3')).lower()
 if preset not in ('mp3','wav','mp3_voice'):raise HTTPException(400,'Unknown export preset')
 for item in items:
  try:start=float(item['start']);end=float(item['end'])
  except (KeyError,TypeError,ValueError):raise HTTPException(400,'Invalid timestamps')
  if start<0 or end<=start or end-start>3600:raise HTTPException(400,'Invalid clip range (maximum 1 hour)')
  try:fade_in=float(item.get('fade_in',0));fade_out=float(item.get('fade_out',0))
  except (TypeError,ValueError):raise HTTPException(400,'Invalid fade duration')
  if not all(math.isfinite(v) for v in (start,end,fade_in,fade_out)) or fade_in<0 or fade_out<0 or fade_in+fade_out>end-start:raise HTTPException(400,'Fade lengths exceed clip duration')
  filters=[]
  if fade_in:filters.append(f'afade=t=in:st=0:d={fade_in:.3f}')
  if fade_out:filters.append(f'afade=t=out:st={end-start-fade_out:.3f}:d={fade_out:.3f}')
  af=['-af',','.join(filters)] if filters else []
  id=uuid.uuid4().hex;path=CLIPS/(id+('.wav' if preset=='wav' else '.mp3'));title=str(item.get('title') or 'Untitled clip')[:150];tags=str(item.get('tags',''))[:500]
  
  if preset=='wav':ff('-ss',start,'-i',src['path'],'-t',end-start,'-ac','2','-ar','44100',*af,'-codec:a','pcm_s16le',path)
  elif preset=='mp3_voice':ff('-ss',start,'-i',src['path'],'-t',end-start,'-ac','1','-ar','44100',*af,'-codec:a','libmp3lame','-b:a','96k',path)
  else:ff('-ss',start,'-i',src['path'],'-t',end-start,*af,'-codec:a','libmp3lame','-q:a','2',path)
  with db() as c:c.execute('INSERT INTO clips(id,source_id,title,path,start,end,tags) VALUES(?,?,?,?,?,?,?)',(id,src['id'],title,str(path),start,end,tags))
  created.append({'id':id,'title':title})
 return {'clips':created}

def _job_update(job_id, **values):
 with JOB_LOCK:JOBS[job_id].update(values)

def _transcribe_worker(job_id, source_id):
 try:
  src=row('sources',source_id)
  import numpy as np
  from faster_whisper import WhisperModel
  if not shutil.which('ffmpeg'):raise RuntimeError('FFmpeg is not on PATH')
  _job_update(job_id,progress=5,message='Decoding audio with FFmpeg')
  cmd=['ffmpeg','-hide_banner','-v','error','-i',str(src['path']),'-map','0:a:0','-vn','-ac','1','-ar','16000','-f','f32le','-acodec','pcm_f32le','pipe:1']
  decoded=subprocess.run(cmd,capture_output=True,timeout=1800)
  if decoded.returncode:raise RuntimeError(decoded.stderr.decode('utf-8','replace')[-800:])
  if not decoded.stdout:raise RuntimeError('No decoded audio samples')
  audio=np.frombuffer(decoded.stdout,dtype=np.float32)
  _job_update(job_id,progress=20,message='Loading local Whisper model')
  model=WhisperModel(os.environ.get('WHISPER_MODEL','base'),device='cpu',compute_type='int8')
  _job_update(job_id,progress=30,message='Recognizing speech')
  segments,_=model.transcribe(audio,vad_filter=True)
  result=[];duration=max(1,len(audio)/16000)
  for segment in segments:
   result.append({'start':round(segment.start,2),'end':round(segment.end,2),'text':segment.text.strip()})
   _job_update(job_id,progress=min(95,30+int(65*segment.end/duration)),message=f'Transcribing: {segment.end:.0f}/{duration:.0f}s')
  with db() as c:c.execute('UPDATE sources SET transcript=? WHERE id=?',(json.dumps(result),source_id))
  _job_update(job_id,state='complete',progress=100,message=f'Completed {len(result)} segments')
 except Exception as exc:
  _job_update(job_id,state='error',message=f'{type(exc).__name__}: {exc}')

@app.post('/api/source/{id}/transcribe')
def transcribe(id:str):
 row('sources',id)
 job_id=uuid.uuid4().hex
 with JOB_LOCK:JOBS[job_id]={'id':job_id,'source_id':id,'state':'running','progress':0,'message':'Queued','created':time.time()}
 threading.Thread(target=_transcribe_worker,args=(job_id,id),daemon=True).start()
 return {'job_id':job_id}

@app.get('/api/jobs/{job_id}')
def job_status(job_id:str):
 with JOB_LOCK:job=JOBS.get(job_id)
 if not job:raise HTTPException(404,'Job not found (jobs reset when server restarts)')
 return dict(job)

@app.delete('/api/clip/{id}')
def delete_clip(id:str):
 clip=row('clips',id)
 with db() as c:c.execute('DELETE FROM clips WHERE id=?',(id,))
 Path(clip['path']).unlink(missing_ok=True)
 return {'ok':True}

# ClipForge Studio API — library storage, audio analysis, soundboard and episode assembly
with db() as c:
 c.execute('CREATE TABLE IF NOT EXISTS soundboard_profiles (name TEXT PRIMARY KEY, clip_ids TEXT NOT NULL DEFAULT "[]")')
 c.execute('CREATE TABLE IF NOT EXISTS episodes (id TEXT PRIMARY KEY, title TEXT, tracks TEXT, path TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP)')

@app.get('/api/settings')
def get_settings():return {'media_folder':str(media_folder()),'default_media_folder':str(MEDIA),'existing_files_unchanged':True}

@app.post('/api/settings')
def set_settings(payload:dict):
 path=str(payload.get('media_folder','')).strip()
 if not path:target=MEDIA
 else:
  target=Path(path).expanduser()
  if not target.is_absolute():raise HTTPException(400,'Enter a full absolute folder path')
  target=target.resolve()
 try:
  target.mkdir(parents=True,exist_ok=True)
  with tempfile.NamedTemporaryFile(dir=target,delete=True) as f:f.write(b'ok')
 except OSError as exc:raise HTTPException(400,'Folder not writable: '+str(exc))
 CONFIG.write_text(json.dumps({'media_folder':str(target)},indent=2),encoding='utf-8')
 return get_settings()

@app.get('/api/soundboards')
def get_soundboards():
 with db() as c:return [{'name':r['name'],'clip_ids':json.loads(r['clip_ids'])} for r in c.execute('SELECT * FROM soundboard_profiles ORDER BY name')]

@app.post('/api/soundboards')
def put_soundboard(payload:dict):
 name=str(payload.get('name','')).strip()[:80]
 ids=payload.get('clip_ids',[])
 if not name or not isinstance(ids,list) or len(ids)>48:raise HTTPException(400,'Invalid profile')
 known={r['id'] for r in get_library_clips()}
 if any(i not in known for i in ids):raise HTTPException(400,'Profile contains missing clips')
 with db() as c:c.execute('INSERT INTO soundboard_profiles(name,clip_ids) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET clip_ids=excluded.clip_ids',(name,json.dumps(ids)))
 return {'ok':True}

def get_library_clips():
 with db() as c:return [dict(r) for r in c.execute('SELECT * FROM clips')]

@app.get('/api/source/{id}/silences')
def silences(id:str,threshold:float=-35,min_duration:float=0.55):
 src=row('sources',id)
 if not -80<=threshold<=-10 or not .1<=min_duration<=10:raise HTTPException(400,'Invalid silence settings')
 p=subprocess.run(['ffmpeg','-hide_banner','-i',src['path'],'-af',f'silencedetect=noise={threshold}dB:d={min_duration}','-f','null','-'],capture_output=True,text=True,timeout=900)
 if p.returncode:raise HTTPException(400,p.stderr[-600:])
 starts=[];results=[]
 for line in p.stderr.splitlines():
  m=re.search(r'silence_start: ([0-9.]+)',line)
  if m:starts.append(float(m.group(1)))
  m=re.search(r'silence_end: ([0-9.]+)',line)
  if m and starts:results.append({'start':round(starts.pop(0),2),'end':round(float(m.group(1)),2)})
 return {'silences':results}

@app.post('/api/source/{id}/cleanup')
def cleanup(id:str,payload:dict):
 src=row('sources',id);mode=str(payload.get('mode','voice'))
 if mode not in ('voice','gentle'):raise HTTPException(400,'Invalid cleanup preset')
 uid=uuid.uuid4().hex;dest=media_folder()/(uid+'.mp3');dest.parent.mkdir(parents=True,exist_ok=True)
 filters='highpass=f=90,lowpass=f=9500,afftdn=nf=-28,loudnorm=I=-16:TP=-1.5:LRA=11' if mode=='voice' else 'afftdn=nf=-35,loudnorm=I=-16:TP=-1.5:LRA=11'
 try:ff('-i',src['path'],'-vn','-af',filters,'-codec:a','libmp3lame','-q:a','3',dest)
 except Exception:dest.unlink(missing_ok=True);raise
 with db() as c:c.execute('INSERT INTO sources(id,title,path,url) VALUES(?,?,?,?)',(uid,src['title']+' [cleaned]',str(dest),''))
 return {'id':uid}

@app.get('/api/search/semantic')
def semantic_search(q:str):
 q=q.strip()
 if not q:return {'results':[],'method':'local lexical relevance'}
 # Local TF-IDF-style ranking; no external model/download or network access.
 tokens=set(re.findall(r'[a-z0-9]{3,}',q.lower()))
 results=[]
 with db() as c:rows=c.execute('SELECT id,title,transcript FROM sources').fetchall()
 for source in rows:
  try:segments=json.loads(source['transcript'] or '[]')
  except ValueError:continue
  for seg in segments:
   words=set(re.findall(r'[a-z0-9]{3,}',seg.get('text','').lower()))
   score=len(tokens&words)/max(1,len(tokens))
   if score:results.append({'source_id':source['id'],'title':source['title'],'start':seg['start'],'text':seg['text'],'score':round(score,3)})
 return {'results':sorted(results,key=lambda x:x['score'],reverse=True)[:30],'method':'local keyword overlap (not embedding-based semantic search)'}

@app.get('/api/source/{id}/suggestions')
def suggestions(id:str):
 src=row('sources',id)
 try:segments=json.loads(src['transcript'] or '[]')
 except ValueError:segments=[]
 cues=('important','remember','surprising','actually','because','however','never','always','first','finally','discovered','breaking','secret','why','how')
 candidates=[]
 for seg in segments:
  txt=seg.get('text','').strip();length=len(txt.split())
  score=min(3,length/12)+sum(1 for cue in cues if cue in txt.lower())+int('?' in txt)+int('!' in txt)
  if 6<=length<=110:candidates.append({'start':seg['start'],'end':seg['end'],'text':txt,'score':round(score,2)})
 return {'suggestions':sorted(candidates,key=lambda x:x['score'],reverse=True)[:12],'method':'heuristic highlights, not generative AI'}

@app.post('/api/episodes')
def create_episode(payload:dict):
 title=str(payload.get('title','Episode')).strip()[:150] or 'Episode'
 items=payload.get('items',[])
 if not isinstance(items,list) or not 1<=len(items)<=50:raise HTTPException(400,'Add 1-50 timeline clips')
 fmt=payload.get('format','mp3')
 if fmt not in ('mp3','wav'):raise HTTPException(400,'Invalid export format')
 normalize=payload.get('normalize',False)
 if not isinstance(normalize,bool):raise HTTPException(400,'Invalid normalization option')
 clips={x['id']:x for x in get_library_clips()}
 uid=uuid.uuid4().hex;out=CLIPS/(uid+'_episode.'+fmt);tmp=[]
 try:
  for item in items:
   if not isinstance(item,dict):raise HTTPException(400,'Invalid timeline item')
   clip=clips.get(item.get('clip_id'))
   if not clip:raise HTTPException(400,'Unknown clip in episode')
   offset=float(item.get('offset',0));gain=float(item.get('gain',1));track=int(item.get('track',0))
   # Existing episode-builder items omit trim and fade fields.
   original_duration=max(0.01,float(clip.get('end',0))-float(clip.get('start',0)))
   start=float(item.get('start',0));end=float(item.get('end',original_duration))
   fi=float(item.get('fade_in',0));fo=float(item.get('fade_out',0))
   values=(offset,gain,start,end,fi,fo)
   if not all(math.isfinite(v) for v in values):raise HTTPException(400,'Timeline contains non-finite values')
   if not (0<=offset<=14400 and 0<=gain<=3 and 0<=track<=7 and 0<=start<end<=original_duration+0.02 and end-start>=0.05 and 0<=fi and 0<=fo and fi+fo<=end-start+0.001):
    raise HTTPException(400,'Invalid trim, fade, gain, track or offset')
   if not Path(clip['path']).is_file():raise HTTPException(400,'Missing clip audio on disk')
   tmp.append((clip,offset,gain,track,start,end,fi,fo))
  if max(x[1]+x[5]-x[4] for x in tmp)>14400:raise HTTPException(400,'Episode exceeds 4 hours')
  cmd=['ffmpeg','-hide_banner','-loglevel','error','-y']
  for clip,*_ in tmp:cmd.extend(['-i',clip['path']])
  filters=[];labels=[]
  for i,(_,offset,gain,track,start,end,fi,fo) in enumerate(tmp):
   duration=end-start;label=f'a{i}';labels.append(f'[{label}]')
   chain=f'[{i}:a]atrim=start={start:.5f}:end={end:.5f},asetpts=PTS-STARTPTS,aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,volume={gain:.5f}'
   if fi>0:chain+=f',afade=t=in:st=0:d={fi:.5f}'
   if fo>0:chain+=f',afade=t=out:st={max(0,duration-fo):.5f}:d={fo:.5f}'
   chain+=f',adelay={int(offset*1000)}|{int(offset*1000)}[{label}]'
   filters.append(chain)
  filters.append(''.join(labels)+f'amix=inputs={len(tmp)}:duration=longest:normalize=0,alimiter=limit=0.95[mixed]')
  if normalize:
   filters.append('[mixed]loudnorm=I=-16:TP=-1.5:LRA=11[out]')
  else:filters.append('[mixed]anull[out]')
  cmd.extend(['-filter_complex',';'.join(filters),'-map','[out]'])
  if fmt=='wav':cmd.extend(['-codec:a','pcm_s16le'])
  else:cmd.extend(['-codec:a','libmp3lame','-q:a','2'])
  cmd.append(str(out))
  p=subprocess.run(cmd,capture_output=True,text=True,timeout=1800)
  if p.returncode:raise HTTPException(400,'Episode render failed: '+p.stderr[-1000:])
  with db() as c:c.execute('INSERT INTO episodes(id,title,tracks,path) VALUES(?,?,?,?)',(uid,title,json.dumps(items),str(out)))
  return {'id':uid,'title':title,'format':fmt}
 except Exception:
  out.unlink(missing_ok=True);raise

@app.get('/api/episodes')
def list_episodes():
 with db() as c:return {'episodes':[dict(x) for x in c.execute('SELECT id,title,tracks,created FROM episodes ORDER BY created DESC')]}

@app.get('/api/episodes/{id}/audio')
def episode_audio(id:str):
 with db() as c:r=c.execute('SELECT * FROM episodes WHERE id=?',(id,)).fetchone()
 if not r:raise HTTPException(404,'Episode not found')
 return FileResponse(r['path'],media_type=('audio/wav' if str(r['path']).lower().endswith('.wav') else 'audio/mpeg'),filename=r['title']+('.wav' if str(r['path']).lower().endswith('.wav') else '.mp3'))

@app.get('/api/library/backup')
def library_backup():
 # Snapshot SQLite using backup API; includes metadata only, not media files.
 output=DATA/'library_backup.sqlite3'
 with sqlite3.connect(DB) as src,sqlite3.connect(output) as dst:src.backup(dst)
 return FileResponse(output,filename='ClipForge_library_backup.sqlite3',media_type='application/octet-stream')

@app.post('/api/source/{id}/speakers')
def label_speakers(id:str,payload:dict):
 src=row('sources',id)
 try:segments=json.loads(src['transcript'] or '[]')
 except ValueError:segments=[]
 labels=payload.get('labels',{})
 if not isinstance(labels,dict):raise HTTPException(400,'Invalid speaker labels')
 for i,segment in enumerate(segments):
  if str(i) in labels:segment['speaker']=str(labels[str(i)])[:60]
 with db() as c:c.execute('UPDATE sources SET transcript=? WHERE id=?',(json.dumps(segments),id))
 return {'segments':segments,'method':'manual speaker labels; automatic diarization not installed'}


@app.get('/api/recording/health')
def recording_health():
 usage=shutil.disk_usage(media_folder())
 free_gb=round(usage.free/1073741824,2)
 return {'free_gb':free_gb,'warning':usage.free<2*1073741824,'total_gb':round(usage.total/1073741824,2)}
