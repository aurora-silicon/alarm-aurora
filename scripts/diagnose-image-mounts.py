#!/usr/bin/env python3
"""Report only processes and descriptors retaining this disposable image mount."""
from pathlib import Path
import json,os,sys
root=sys.argv[1].rstrip('/')
mounts={}
for line in Path('/proc/self/mountinfo').read_text().splitlines():
 fields=line.split();target=fields[4]
 if target==root or target.startswith(root+'/'):
  mounts[fields[0]]=target
print('Image mount identities:',json.dumps(mounts,sort_keys=True),flush=True)
for process in Path('/proc').iterdir():
 if not process.name.isdigit():continue
 try:
  processroot=os.readlink(process/'root')
  cwd=os.readlink(process/'cwd')
  held=[]
  for info in (process/'fdinfo').iterdir():
   data=dict(line.split(':',1) for line in info.read_text().splitlines() if ':' in line)
   identity=data.get('mnt_id','').strip()
   if identity in mounts:held.append({'fd':info.name,'mount':mounts[identity],'target':os.readlink(process/'fd'/info.name)})
  if processroot.startswith(root) or cwd.startswith(root) or held:
   print(json.dumps({'pid':process.name,'comm':(process/'comm').read_text().strip(),'root':processroot,'cwd':cwd,'descriptors':held},sort_keys=True),flush=True)
 except (OSError,PermissionError):continue
