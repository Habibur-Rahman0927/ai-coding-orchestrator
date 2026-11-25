"""One owned loopback service per database; no PID-based kill or OS service install."""
import contextlib
import hashlib
import hmac
import http.client
import json
import os
from pathlib import Path
import signal
import stat
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from urllib.parse import urlsplit
import ccx_platform as native


def paths(store):
    key = hashlib.sha256(str(store.path).encode()).hexdigest()[:16]
    return (store.path.parent / ('service-'+key+'.json'), store.path.parent / ('service-'+key+'.lock'))


def private_read(path):
    native.validate_permissions(path,mask=0o077)
    info=path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 16384:
        raise PermissionError('Unsafe service metadata')
    flags = os.O_RDONLY | getattr(os,'O_NOFOLLOW',0)
    with os.fdopen(os.open(str(path),flags),'r') as stream:
        opened=os.fstat(stream.fileno())
        if opened.st_ino!=info.st_ino or opened.st_dev!=info.st_dev or not stat.S_ISREG(opened.st_mode):
            raise PermissionError('Service metadata changed while opening')
        value=stream.read(16385)
        if len(value)>16384:raise ValueError('Service metadata exceeds limit')
        return json.loads(value)


def write_state(path, value):
    if path.exists():
        private_read(path)
    elif native.is_link(path):
        raise PermissionError('Unsafe service metadata link')
    fd, temp = tempfile.mkstemp(prefix='.service-', dir=str(path.parent))
    try:
        with os.fdopen(fd,'w') as stream:
            json.dump(value,stream)
            stream.flush()
            os.fsync(stream.fileno())
        native.secure_mode(Path(temp),0o600)
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)


def rotate_token(server):
    """Rotate fallback/control bearer as well as browser sessions."""
    state_path,_=paths(server.application.store)
    token=__import__('secrets').token_urlsafe(32)
    if state_path.exists():
        state=private_read(state_path)
        if state.get('instance')!=getattr(server,'instance',None):
            raise PermissionError('Cannot rotate another service instance')
        state['token']=token
        token_path=state_path.with_suffix('.token')
        if token_path.exists():
            native.validate_permissions(token_path,mask=0o077)
            if token_path.stat().st_nlink!=1:raise PermissionError('Unsafe fallback token')
        fd=os.open(str(token_path),os.O_WRONLY|os.O_CREAT|os.O_TRUNC|getattr(os,'O_NOFOLLOW',0),0o600)
        with os.fdopen(fd,'w') as stream:stream.write(token)
        native.secure_mode(token_path,0o600)
        write_state(state_path,state)
    server.token=token
    server.auth.rotate()


def request(store, endpoint, body=None):
    state = private_read(paths(store)[0])
    port = state.get('port')
    if type(port) != int or not 1 <= port <= 65535:
        raise ValueError('Invalid local service port')
    connection = http.client.HTTPConnection('127.0.0.1',port,timeout=3)
    try:
        # Prove possession before sending the private control bearer to a port
        # that might have been reused by an unrelated application after a crash.
        nonce=secrets.token_hex(32)
        connection.request('POST','/api/service/challenge',body=json.dumps({'nonce':nonce}),headers={'Content-Type':'application/json'})
        challenge=connection.getresponse()
        proof=json.loads(challenge.read(4096))
        expected=hmac.new(state['token'].encode(),(state['instance']+nonce).encode(),'sha256').hexdigest()
        if challenge.status!=200 or not hmac.compare_digest(str(proof.get('proof','')),expected):
            raise PermissionError('Port belongs to a different application; service credentials were not sent')
        headers = {'Authorization':'Bearer '+state['token'], 'X-Workspace-Instance':state['instance']}
        payload = None
        if body is not None:
            payload = json.dumps(body)
            headers['Content-Type']='application/json'
        connection.request('POST' if body is not None else 'GET', endpoint, body=payload, headers=headers)
        response = connection.getresponse()
        data = json.loads(response.read(65536))
        if response.status != 200:
            raise RuntimeError('Local service rejected request; inspect status before retrying')
        return data
    finally:
        connection.close()


def status(store):
    try:
        return request(store,'/api/service/health')
    except FileNotFoundError:
        return {'running':False,'reason':'Not started'}
    except (OSError,ValueError,RuntimeError,KeyError):
        return {'running':False,'reason':'Stored service is unavailable; run start to recover'}


def open_browser(store):
    state=private_read(paths(store)[0])
    value = request(store,'/api/service/browser',{})
    # Short-lived single-use fragment is never printed, sent as an HTTP URL,
    # or included in referrers; frontend replaces history before rendering.
    parsed=urlsplit(value['url'])
    import re
    if parsed.scheme!='http' or parsed.netloc!='127.0.0.1:'+str(state['port']) or parsed.path!='/' or parsed.query or not re.fullmatch(r'bootstrap=[A-Za-z0-9_-]{32,128}',parsed.fragment):
        raise ValueError('Service returned an unsafe browser URL')
    opened = webbrowser.open(value['url'],new=2)
    return {'opened':bool(opened),'url':value['url'].split('#',1)[0],
            'message':'Browser sign-in link created' if opened else 'Browser unavailable; use dashboard token fallback'}


def stop(store):
    current = status(store)
    if not current.get('running'):return current
    result = request(store,'/api/service/stop',{})
    deadline = time.monotonic()+15
    while time.monotonic()<deadline:
        if not status(store).get('running'):
            return {'running':False,'message':'Service stopped; workflows paused for recovery'}
        time.sleep(.1)
    return dict(result, message='Graceful shutdown requested; inspect status before restart')


def start(store, port=8765, background=False, browser=True):
    existing = status(store)
    if existing.get('running'):
        if browser:open_browser(store)
        return dict(existing,existing=True)
    if not background:
        return run(store,port,browser)
    controller = Path(__file__).resolve().parents[2]/'orchestrator.py'
    argv=[sys.executable,'-B',str(controller),'workspace','--database',str(store.path),'_serve','--port',str(port)]
    options={'stdin':subprocess.DEVNULL,'stdout':subprocess.DEVNULL,'stderr':subprocess.DEVNULL,'close_fds':True}
    if os.name=='nt':options['creationflags']=subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.DETACHED_PROCESS
    else:options['start_new_session']=True
    process = subprocess.Popen(argv,**options)
    threading.Thread(target=process.wait,daemon=True).start()
    for unused in range(100):
        current = status(store)
        if current.get('running'):
            if browser:open_browser(store)
            return dict(current,background=True)
        if process.poll() is not None:
            raise RuntimeError('Background startup failed; use workspace start --no-browser for diagnostic errors')
        time.sleep(.1)
    raise RuntimeError('Startup timed out; inspect workspace status before retrying')


def run(store, port=8765, browser=True):
    from ccx_install import workspace_runtime
    with workspace_runtime():
        return _run(store,port,browser)


def _run(store, port=8765, browser=True):
    from .server import create_server
    state_path,lock_path=paths(store)
    if lock_path.exists():
        native.validate_permissions(lock_path)
        info=lock_path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise PermissionError('Unsafe service lock')
    fd=os.open(str(lock_path),os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
    native.secure_mode(lock_path,0o600)
    with os.fdopen(fd,'a+') as lock:
        try:native.flock(lock,native.LOCK_EX|native.LOCK_NB)
        except OSError:
            current=status(store)
            if current.get('running'):
                if browser:open_browser(store)
                return dict(current,existing=True)
            raise RuntimeError('Workspace is starting or shutting down; retry status shortly')
        try:
            try:server=create_server(store,port=port)
            except OSError as error:
                import errno
                if error.errno not in (errno.EADDRINUSE,10048):raise
                server=create_server(store,port=0)
            server.instance=__import__('secrets').token_urlsafe(24)
            server.application.engine.reconcile_ownership()
            server.application.chat.reconcile_startup()
            actual=server.server_address[1]
            state={'port':actual,'token':server.token,'instance':server.instance,'pid':os.getpid()}
            write_state(state_path,state)
            token_file=state_path.with_suffix('.token')
            # Atomic private fallback file belongs to this port and current service.
            if token_file.exists():
                native.validate_permissions(token_file,mask=0o077)
                if token_file.stat().st_nlink!=1:raise PermissionError('Unsafe token file')
            token_fd=os.open(str(token_file),os.O_WRONLY|os.O_CREAT|os.O_TRUNC|getattr(os,'O_NOFOLLOW',0),0o600)
            with os.fdopen(token_fd,'w') as stream:stream.write(server.token)
            native.secure_mode(token_file,0o600)
            def shutdown(*unused):
                threading.Thread(target=server.shutdown,daemon=True).start()
            previous={}
            if threading.current_thread() is threading.main_thread():
                for signum in (signal.SIGINT,signal.SIGTERM):
                    previous[signum]=signal.signal(signum,shutdown)
            print('Dashboard: http://127.0.0.1:'+str(actual),flush=True)
            print('Manual fallback token file: '+str(token_file),flush=True)
            if browser:
                credential=server.auth.issue()
                webbrowser.open('http://127.0.0.1:%d/#bootstrap=%s'%(actual,credential),new=2)
            try:server.serve_forever(poll_interval=.2)
            finally:
                server.application.close()
                server.server_close()
                server.auth.rotate()
                for signum,handler in previous.items():signal.signal(signum,handler)
                if state_path.exists() and private_read(state_path).get('instance')==server.instance:state_path.unlink()
                if token_file.exists() and not native.is_link(token_file):
                    if token_file.read_text()==server.token:token_file.unlink()
            return {'running':False,'message':'Workspace stopped'}
        finally:
            if 'server' in locals():
                server.application.close()
                server.server_close()
                if state_path.exists() and private_read(state_path).get('instance')==getattr(server,'instance',None):state_path.unlink()
                if 'token_file' in locals() and token_file.exists() and not native.is_link(token_file):
                    if token_file.read_text()==server.token:token_file.unlink()
            native.flock(lock,native.LOCK_UN)
