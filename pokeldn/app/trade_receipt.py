"""Durable confirmed-trade receipt, independent of GUI/web dependencies."""
import base64
import hashlib
import json
import os
from pathlib import Path


def write_receipt(path,received,offered):
    target=Path(path);target.parent.mkdir(parents=True,exist_ok=True)
    content={'version':1,'game':'swsh','trade':1,'received':base64.b64encode(received).decode(),
             'received_sha256':hashlib.sha256(received).hexdigest(),'offered_sha256':hashlib.sha256(offered).hexdigest()}
    tmp=target.with_suffix('.tmp')
    with tmp.open('w') as out:
        json.dump(content,out);out.flush();os.fsync(out.fileno())
    os.replace(tmp,target)
    if os.name=='posix':
        fd=os.open(target.parent,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)


def write_candidate(path,data):
    target=Path(path);target.parent.mkdir(parents=True,exist_ok=True)
    tmp=target.with_suffix('.tmp')
    with tmp.open('wb') as out:
        out.write(data);out.flush();os.fsync(out.fileno())
    os.replace(tmp,target)
    if os.name=='posix':
        fd=os.open(target.parent,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
