from __future__ import annotations
import json
import os
import tempfile
import threading
import urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer

state = tempfile.TemporaryDirectory(prefix="searchorders-source-api-")
os.environ["SEARCHORDERS_STATE"] = state.name
from realtime_service import app

Path(state.name, "extra_sources.json").write_text(json.dumps([
    "https://t.me/s/vakansii_smm",
    "https://t.me/s/vakansii_reelsmaker",
    "https://t.me/s/vakansii_copywriters",
]), encoding="utf-8")

srv=ThreadingHTTPServer(("127.0.0.1",0),app.Handler)
thread=threading.Thread(target=srv.serve_forever,daemon=True)
thread.start()
base=f"http://127.0.0.1:{srv.server_port}"

def request(path,payload=None,origin=None):
    body = None if payload is None else json.dumps(payload).encode()
    headers={"Accept":"application/json"}
    if body is not None: headers["Content-Type"]="application/json"
    if origin is not None: headers["Origin"]=origin
    req=urllib.request.Request(base+path,data=body,headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=10) as r:
            return r.status,json.load(r)
    except urllib.error.HTTPError as err:
        return err.code,json.load(err)

try:
    before=request("/api/sources")[1]["telegram_sources"]
    assert len(before)==44, len(before)
    for name in ["vakansii_smm","vakansii_reelsmaker","vakansii_copywriters"]:
        code,result=request("/api/source/remove",{"url":"https://t.me/s/"+name})
        assert code==200 and result["removed"],(code,result)
    after=request("/api/sources")[1]["telegram_sources"]
    assert len(after)==41,len(after)
    assert all("vakansii_"+x not in ",".join(after) for x in ("smm","reelsmaker","copywriters"))
    code,result=request("/api/source/remove",{"url":"https://t.me/s/vakansii_smm"})
    assert code==200 and result["removed"] is False
    code,result=request("/api/source/remove",{"url":"https://evil.example/abc"})
    assert code==400
    code,result=request("/api/source/remove",{"url":"https://t.me/s/designs_squad"},origin="http://evil.example")
    assert code==403
    assert len(request("/api/sources")[1]["telegram_sources"])==41
    print("SOURCE_API_SMOKE_PASSED start=44 end=41 removed=3 server=http://127.0.0.1:"+str(srv.server_port))
finally:
    srv.shutdown()
    srv.server_close()
    state.cleanup()
