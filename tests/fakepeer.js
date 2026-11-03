// Fake PeerJS (same API surface the shim uses) over BroadcastChannel, for offline testing.
(function(){
  window.__caboBrokers = window.__caboBrokers || []; // PeerJS-only unless a test also sets up a broker
  const bc = new BroadcastChannel('fakepeer');
  const local = new Map(); // id -> Peer in this tab
  function rid(){ return 'x'+Math.random().toString(36).slice(2,10); }
  class Emitter { constructor(){ this._h={}; } on(e,f){ (this._h[e]=this._h[e]||[]).push(f); return this; } _emit(e,...a){ (this._h[e]||[]).forEach(f=>{ try{f(...a)}catch(err){console.error(err)} }); } }
  class Conn extends Emitter {
    constructor(peer, remote, cid){ super(); this.peer=remote; this._p=peer; this._cid=cid; this.open=false; }
    send(d){ if(!this.open) return; bc.postMessage({t:'data', to:this.peer, from:this._p.id, cid:this._cid, d:JSON.parse(JSON.stringify(d))}); }
    close(){ if(!this.open) return; this.open=false; bc.postMessage({t:'close', to:this.peer, from:this._p.id, cid:this._cid}); this._emit('close'); }
  }
  class Peer extends Emitter {
    constructor(id){ super(); this.id = id || rid(); this._conns = new Map(); this.destroyed=false;
      bc.postMessage({t:'claim', id:this.id}); this._taken=false;
      setTimeout(()=>{ if(this.destroyed) return; if(this._taken){ this._emit('error',{type:'unavailable-id'}); } else { local.set(this.id,this); this._emit('open',this.id); } }, 150);
    }
    connect(remote){ const cid=rid(); const c=new Conn(this,remote,cid); this._conns.set(cid,c);
      bc.postMessage({t:'conn', to:remote, from:this.id, cid});
      c._timer=setTimeout(()=>{ if(!c.open){ this._conns.delete(cid); this._emit('error',{type:'peer-unavailable'}); } },400);
      return c; }
    destroy(){ if(this.destroyed) return; this._conns.forEach(c=>c.close()); this.destroyed=true; local.delete(this.id); }
    reconnect(){}
  }
  bc.onmessage = e => { const m=e.data;
    if(m.t==='claim'){ if(local.has(m.id)) bc.postMessage({t:'taken', id:m.id}); return; }
    if(m.t==='taken'){ /* mark any pending peer with this id */ pending.forEach(p=>{ if(p.id===m.id) p._taken=true; }); return; }
    const p = local.get(m.to); if(!p||p.destroyed) return;
    if(m.t==='conn'){ const c=new Conn(p,m.from,m.cid); c.open=true; p._conns.set(m.cid,c); bc.postMessage({t:'ack', to:m.from, from:p.id, cid:m.cid}); p._emit('connection',c); setTimeout(()=>c._emit('open'),0); }
    if(m.t==='ack'){ const c=p._conns.get(m.cid); if(c){ clearTimeout(c._timer); c.open=true; c._emit('open'); } }
    if(m.t==='data'){ const c=p._conns.get(m.cid); if(c&&c.open) c._emit('data',m.d); }
    if(m.t==='close'){ const c=p._conns.get(m.cid); if(c&&c.open){ c.open=false; c._emit('close'); } }
  };
  const pending = new Set();
  window.Peer = function(id){ const p=new Peer(id); pending.add(p); setTimeout(()=>pending.delete(p),300); return p; };
  window.__killPeers = () => local.forEach(p=>p.destroy());
})();
