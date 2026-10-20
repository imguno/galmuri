"""Admin presentation uses only public service data and commands."""

import html
import json

from galmuri.exposure.http.tables import status_tables


def render_admin(capabilities: dict, status: dict) -> str:
    options = "".join(
        f'<option value="{html.escape(name, quote=True)}">{html.escape(name)}</option>'
        for name in capabilities
    )
    snapshot = html.escape(json.dumps(status, indent=2, ensure_ascii=False))
    writable_options = "".join(
        f'<option value="{html.escape(name, quote=True)}">{html.escape(name)}</option>'
        for name, descriptor in capabilities.items()
        if "write" in descriptor.get("operations", [])
    )
    write_panel = ""
    if writable_options:
        write_panel = (
            """<section><h2>Write original source</h2>
<p class="subtitle">Replaces source content only when current document permissions allow it.
Read the document first to obtain its version. Successful writes queue processing.</p>
<label>Writable app <select id="write-app">"""
            + writable_options
            + """</select></label>
<label>Document key <input id="write-key"></label>
<label>Expected version <input id="write-version"></label>
<label class="block">Replacement content <textarea id="write-content" rows="5"></textarea></label>
<button data-op="write">Write source</button></section>"""
        )
    return (
        """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Source administration</title><style>
:root{font-family:system-ui,sans-serif;color:#18253b;background:#f3f5f8}
body{max-width:1120px;margin:40px auto;padding:0 24px}h1{margin-bottom:6px}
.subtitle{color:#536279}section{background:white;padding:24px;border-radius:12px;
margin:20px 0;border:1px solid #dfe5ed}button,input,select{font:inherit;padding:10px;
margin:5px;border-radius:6px;border:1px solid #b9c6d8}button{cursor:pointer;
background:#174b89;color:white}pre{white-space:pre-wrap;overflow-wrap:anywhere;
background:#edf2f7;padding:18px;border-radius:6px}label{display:inline-block}
.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}
th,td{padding:12px;text-align:left;border-bottom:1px solid #e3e9f1;max-width:280px;
overflow-wrap:anywhere}th{color:#536279;font-weight:600}h2{font-size:18px;margin-top:0}
textarea{display:block;box-sizing:border-box;width:100%;font:inherit;padding:12px;
border:1px solid #b9c6d8;border-radius:6px;margin:8px 0}.block{display:block}
</style><h1>Source administration</h1>
<p class="subtitle">App policies, processing status and permission-aware document access.</p>
<section><h2>Sources and actions</h2><label>App <select id="app">"""
        + options
        + """</select>
</label><div><button data-op="describe">Describe</button>
<button data-op="collect">Collect now</button><button data-op="sync">Sync</button>
<button data-op="pause">Pause</button><button data-op="resume">Resume</button>
<button data-op="status">Refresh status</button></div>
<label>Job identifier <input id="job" placeholder="Job ID"></label>
<button data-op="retry">Retry job</button><button data-op="cancel">Cancel job</button>
<div><label>Reconciliation outcome <select id="job-outcome">
<option value="retry_safe">Safe to retry</option><option value="failed">Failed</option>
<option value="cancelled">Cancelled</option></select></label>
<button data-op="reconcile">Reconcile job</button></div>
<p class="subtitle">Reconcile uncertain effects only after checking the original system.</p>
</section><section><h2>Source write reconciliation</h2>
<label>Operation identifier <input id="write-operation"></label>
<label>Outcome <select id="write-outcome"><option value="not_applied">Not applied</option>
<option value="failed">Failed</option><option value="applied">Applied</option></select></label>
<label>Receipt source key <input id="receipt-key"></label>
<label>Receipt version <input id="receipt-version"></label>
<button data-op="reconcile_write">Reconcile write</button>
<p class="subtitle">An applied write requires the exact source key and resulting version.</p>
</section><section><h2>Document search and read</h2>
<input id="query" placeholder="Search text"><button data-op="search">Search</button>
<input id="document" placeholder="Document key"><button data-op="read">Read</button>
<p class="subtitle">Management access does not bypass document permissions.</p></section>
"""
        + write_panel
        + status_tables(status)
        + """
<section><h2>Operation result</h2><pre id="result" aria-live="polite">"""
        + snapshot
        + """</pre>
</section><script>
document.querySelectorAll('[data-op]').forEach(button=>button.onclick=async()=>{
const operation=button.dataset.op;const params={app:document.querySelector('#app').value};
if(operation==='search')params.query=document.querySelector('#query').value;
if(operation==='read')params.document_key=document.querySelector('#document').value;
if(operation==='write'){
params.app=document.querySelector('#write-app').value;
params.document_key=document.querySelector('#write-key').value;
params.expected_version=document.querySelector('#write-version').value;
params.content=document.querySelector('#write-content').value;}
if(operation==='retry'||operation==='cancel'||operation==='reconcile'){
delete params.app;params.job_id=document.querySelector('#job').value;}
if(operation==='reconcile')params.outcome=document.querySelector('#job-outcome').value;
if(operation==='reconcile_write'){
delete params.app;params.operation_id=document.querySelector('#write-operation').value;
params.outcome=document.querySelector('#write-outcome').value;
if(params.outcome==='applied')params.ref={key:document.querySelector('#receipt-key').value,
version:document.querySelector('#receipt-version').value};}
button.disabled=true;try{const response=await fetch('/api/call',{method:'POST',
headers:{'Content-Type':'application/json'},body:JSON.stringify({operation,params})});
const data=await response.json();
document.querySelector('#result').textContent=JSON.stringify(data,null,2);
if(data.ok&&operation==='read'&&document.querySelector('#write-key')){
document.querySelector('#write-key').value=data.result.key;
document.querySelector('#write-version').value=data.result.version;
document.querySelector('#write-content').value=data.result.text;}
document.querySelector('#result').scrollIntoView({behavior:'smooth',block:'nearest'});
}catch(error){document.querySelector('#result').textContent='Request failed';}
finally{button.disabled=false;}});
</script></html>"""
    )
