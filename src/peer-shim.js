// Standalone networking: implements the small slice of claude.use('room'/'user') the game needs.
// Every message goes out over two independent paths and is de-duplicated on arrival:
//  1. an encrypted relay through free public MQTT brokers, which works between any two networks
//     (home Wi-Fi, mobile data, office) because both sides only make an outgoing secure WebSocket;
//  2. WebRTC via PeerJS, direct when the two networks allow it. The first browser to claim a game
//     code becomes the hub and forwards for the others; if it leaves, the others race to replace it.
// Presence comes from heartbeats on either path, so a player stays in the room while any path reaches them.
(function(){
  if (window.claude) return;
  window.__caboStandalone = true;
  const PRE = 'cabo-with-friends-v2-';
  // tests can point these elsewhere or switch a path off
  const BROKERS = window.__caboBrokers || ['wss://broker.emqx.io:8084/mqtt', 'wss://broker.hivemq.com:8884/mqtt'];
  const USE_PEERJS = window.__caboPeerJS !== false;
  // PeerJS's built-in TURN hosts no longer resolve, so only STUN here; the MQTT relay covers networks STUN can't
  const ICE = {iceServers:[{urls:['stun:stun.l.google.com:19302','stun:stun.cloudflare.com:3478']}]};
  const HB_MS = 3000, GONE_MS = 12000;
  // a timer in a worker keeps heartbeats going in background tabs, where page timers get throttled
  function ticker(ms, f){
    try { const w = new Worker(URL.createObjectURL(new Blob(['setInterval(()=>postMessage(0),'+ms+')'], {type:'text/javascript'}))); w.onmessage = f; return () => w.terminate(); }
    catch(e) { const t = setInterval(f, ms); return () => clearInterval(t); }
  }
  const rid = n => { let s=''; const a='abcdefghijkmnpqrstuvwxyz23456789'; for(let i=0;i<n;i++) s+=a[Math.floor(Math.random()*a.length)]; return s; };
  // per-tab id (survives a refresh of the same tab, so a player can rejoin their seat)
  let uid = null; try { uid = sessionStorage.getItem('cabo-uid'); if(!uid){ uid='u'+rid(12); sessionStorage.setItem('cabo-uid',uid); } } catch(e) { uid='u'+rid(12); }
  const myPeer = 'p' + rid(10);
  const BYE = {p:myPeer, b:uid, i:0, k:'bye'};
  const waitPeerLib = () => new Promise(res => { let k=0; const t=()=>{ if(window.Peer) return res(true); if(++k>60) return res(false); setTimeout(t,100); }; t(); });
  const subtle = window.crypto && crypto.subtle;
  const te = new TextEncoder(), td = new TextDecoder();

  // ---- relay path: a minimal MQTT 3.1.1 client (QoS 0 publish/subscribe) over WebSocket ----
  // The topic and key both come from the game code, so the broker only ever sees ciphertext.
  async function roomSecrets(name){
    const hex = b => [...new Uint8Array(b)].map(x=>x.toString(16).padStart(2,'0')).join('');
    const topic = 'cabo-with-friends/v2/' + hex(await subtle.digest('SHA-256', te.encode('cabo-topic|'+name))).slice(0,32);
    const base = await subtle.importKey('raw', te.encode(name), 'PBKDF2', false, ['deriveKey']);
    const key = await subtle.deriveKey({name:'PBKDF2', salt:te.encode('cabo-with-friends-v2'), iterations:100000, hash:'SHA-256'},
      base, {name:'AES-GCM', length:256}, false, ['encrypt','decrypt']);
    return {topic, key};
  }
  const varint = n => { const o=[]; do { let b=n%128; n=Math.floor(n/128); if(n>0) b|=128; o.push(b); } while(n>0); return o; };
  const mstr = s => { const b=te.encode(s); return [b.length>>8, b.length&255, ...b]; };
  const pkt = (h, body) => { const v=varint(body.length), out=new Uint8Array(1+v.length+body.length); out[0]=h; out.set(v,1); out.set(body,1+v.length); return out; };

  function mqttTransport(url, sec, onEnv, onUp){
    let ws = null, up = false, closed = false, tries = 0, ping = null, buf = new Uint8Array(0);
    let inQ = Promise.resolve(), outQ = Promise.resolve(), byePkt = null;
    const cid = 'cabo' + rid(16);
    const seal = async env => {
      const iv = crypto.getRandomValues(new Uint8Array(12));
      const ct = new Uint8Array(await subtle.encrypt({name:'AES-GCM', iv}, sec.key, te.encode(JSON.stringify(env))));
      const body = new Uint8Array(mstr(sec.topic).length + 12 + ct.length);
      body.set(mstr(sec.topic)); body.set(iv, body.length-ct.length-12); body.set(ct, body.length-ct.length);
      return pkt(0x30, body);
    };
    const unseal = async b => JSON.parse(td.decode(await subtle.decrypt({name:'AES-GCM', iv:b.subarray(0,12)}, sec.key, b.subarray(12))));
    seal(BYE).then(p => { byePkt = p; }).catch(()=>{}); // ready ahead of time so pagehide can send it synchronously
    const raw = p => { try { if (ws && ws.readyState === 1) ws.send(p); } catch(e){} };

    function open(){
      if (closed) return;
      try { ws = new WebSocket(url, 'mqtt'); } catch(e) { return retry(); }
      ws.binaryType = 'arraybuffer'; buf = new Uint8Array(0);
      ws.onopen = () => raw(pkt(0x10, [...mstr('MQTT'), 4, 2, 0, 60, ...mstr(cid)])); // CONNECT, clean session, 60 s keepalive
      ws.onmessage = e => { if (e.data instanceof ArrayBuffer) feed(new Uint8Array(e.data)); };
      ws.onclose = () => { up = false; clearInterval(ping); if (!closed) retry(); };
    }
    function retry(){ tries++; setTimeout(open, Math.min(15000, 1000*tries) + Math.random()*500); }
    function feed(chunk){
      const b = new Uint8Array(buf.length + chunk.length); b.set(buf); b.set(chunk, buf.length); buf = b;
      for (;;) {
        let len = 0, mul = 1, i = 1, byte;
        do { if (i >= buf.length) return; byte = buf[i++]; len += (byte & 127) * mul; mul *= 128; } while ((byte & 128) && i < 5);
        if (buf.length < i + len) return;
        const h = buf[0], body = buf.slice(i, i + len); buf = buf.slice(i + len);
        const type = h >> 4;
        if (type === 2) { if (body[1] === 0) raw(pkt(0x82, [0, 1, ...mstr(sec.topic), 0])); else ws.close(); } // CONNACK -> SUBSCRIBE
        else if (type === 9) { up = true; tries = 0; clearInterval(ping); ping = setInterval(() => raw(new Uint8Array([0xC0, 0])), 25000); onUp(); } // SUBACK
        else if (type === 3) { // PUBLISH
          const off = 2 + ((body[0] << 8) | body[1]) + (((h >> 1) & 3) ? 2 : 0);
          const payload = body.subarray(off);
          inQ = inQ.then(() => unseal(payload)).then(onEnv).catch(() => {}); // keeps arrival order; drops anything we can't decrypt
        }
      }
    }
    open();
    return {
      up: () => up,
      send(env){
        if (env === BYE) { if (byePkt) raw(byePkt); return; }
        if (!up) return;
        outQ = outQ.then(() => seal(env)).then(raw).catch(() => {});
      },
      close(){ closed = true; up = false; clearInterval(ping); raw(new Uint8Array([0xE0, 0])); try { ws && ws.close(); } catch(e){} }
    };
  }

  // ---- direct path: WebRTC via PeerJS, star around whoever holds the game code's peer id ----
  // onGone(peer) reports a direct link that just dropped, so the room can stop waiting for its heartbeats
  function peerTransport(name, onEnv, onUp, onGone){
    const hubId = PRE + name, conns = new Set(), connPeer = new Map();
    let peerObj = null, upConn = null, hubPeer = null, closed = false, isHub = false, connected = false, fails = 0;
    const bcast = (d, except) => conns.forEach(c => { if (c !== except) { try { c.send(d); } catch(e){} } });
    const later = f => setTimeout(f, Math.min(15000, 300 * Math.pow(2, fails++)) + Math.random()*1000);

    function tryHub(){
      if (closed) return;
      const p = new Peer(hubId, {config:ICE}); peerObj = p;
      p.on('open', () => { isHub = true; connected = true; fails = 0; onUp(); });
      p.on('connection', conn => {
        conn.on('open', () => { conns.add(conn); try { conn.send({k:'hub', p:myPeer}); } catch(e){} });
        conn.on('data', d => { if (d && d.k === 'bus' && d.e) { conns.add(conn); if (!connPeer.has(conn)) connPeer.set(conn, d.e.p); onEnv(d.e); bcast(d, conn); } });
        const gone = () => { if (conns.delete(conn) && connPeer.has(conn)) onGone(connPeer.get(conn)); connPeer.delete(conn); };
        conn.on('close', gone); conn.on('error', gone);
      });
      p.on('disconnected', () => { if (!closed) { try { p.reconnect(); } catch(e){} } });
      p.on('error', e => {
        if (e && e.type === 'unavailable-id') { try{ p.destroy(); }catch(_){} joinHub(); }
        else if (!isHub) { try{ p.destroy(); }catch(_){} later(tryHub); }
      });
    }

    function joinHub(){
      if (closed) return;
      const p = new Peer(undefined, {config:ICE}); peerObj = p; isHub = false;
      p.on('open', () => {
        const c = p.connect(hubId, {reliable:true}); upConn = c;
        c.on('open', () => { connected = true; fails = 0; onUp(); });
        c.on('data', d => { if (d && d.k === 'bus' && d.e) onEnv(d.e); else if (d && d.k === 'hub') hubPeer = d.p; });
        const lost = () => { if (upConn !== c) return; upConn = null; connected = false; if (hubPeer) onGone(hubPeer); hubPeer = null; try{ p.destroy(); }catch(_){} if (!closed) later(tryHub); };
        c.on('close', lost); c.on('error', lost);
        // when the two networks can't reach each other directly, ICE can stall without an error
        setTimeout(() => { if (upConn === c && !connected) lost(); }, 12000);
      });
      p.on('error', e => {
        if (e && e.type === 'peer-unavailable') { try{ p.destroy(); }catch(_){} setTimeout(tryHub, 200 + Math.random()*400); }
        else if (!connected) { try{ p.destroy(); }catch(_){} later(tryHub); }
      });
    }

    tryHub();
    return {
      up: () => connected,
      send(env){
        const d = {k:'bus', e:env};
        if (isHub) bcast(d); else if (upConn && connected) { try { upConn.send(d); } catch(e){} }
      },
      close(){ closed = true; connected = false; try { conns.forEach(c => c.close()); } catch(e){} try { peerObj && peerObj.destroy(); } catch(e){} }
    };
  }

  // ---- the room: presence, de-duplication and topics on top of whichever paths are up ----
  function makeRoom(name){
    const handlers = {}, ph = [], peers = new Map(), heard = new Map(), seen = new Map(), transports = [];
    const mk = (peer,by,me) => ({peer, by: by||null, isMe: !!me, sameTab: !!me, kind:'viewer', guest:false, presence:{}, updatedAt:Date.now()});
    peers.set(myPeer, mk(myPeer, uid, true));
    let seq = 0, lastHb = 0, closed = false;
    const snap = () => Object.freeze([...peers.values()]);
    const fire = (joined,left) => { const s=snap(); ph.forEach(h=>setTimeout(()=>h({peers:s,joined,left,updated:[]}),0)); };
    const deliver = m => (handlers[m.topic]||[]).forEach(h => { try { h({topic:m.topic, data:m.data, peer:m.peer, by:m.by||null, isMe:m.peer===myPeer, sameTab:m.peer===myPeer, kind:'viewer', guest:false}); } catch(e){ console.error(e); } });
    const send = env => transports.forEach(t => t.send(env));
    const out = (k, extra) => send(Object.assign({p:myPeer, b:uid, i:++seq, k}, extra));
    const hb = () => { lastHb = Date.now(); out('hb'); };

    function onEnv(e){
      if (closed || !e || typeof e !== 'object' || typeof e.p !== 'string' || e.p === myPeer || typeof e.i !== 'number') return;
      const p = e.p.slice(0,40);
      let s = seen.get(p); if (!s) seen.set(p, s = new Set());
      if (s.has(e.i)) return; // already arrived by the other path
      s.add(e.i); if (s.size > 600) seen.set(p, new Set([...s].slice(-300)));
      if (e.k === 'bye') { heard.delete(p); const x = peers.get(p); if (x) { peers.delete(p); fire([],[x]); } return; }
      heard.set(p, Date.now());
      const isNew = !peers.has(p);
      if (isNew) { const np = mk(p, typeof e.b === 'string' ? e.b.slice(0,40) : null); peers.set(p, np); fire([np],[]); }
      if ((isNew || e.k === 'hello') && Date.now() - lastHb > 250) hb(); // let newcomers see us right away
      if (e.k === 'msg') deliver({topic:String(e.t), data:e.d, peer:p, by:peers.get(p).by});
    }

    let readyRes; const ready = new Promise(r=>readyRes=r);
    const onUp = () => { readyRes(); if (!closed) out('hello'); };
    // a dropped direct link only shortens the wait: the peer stays if the relay still hears from it
    const onGone = p => { if (heard.has(p)) heard.set(p, Math.min(heard.get(p), Date.now() - GONE_MS + HB_MS * 1.5)); };
    if (USE_PEERJS && window.Peer) transports.push(peerTransport(name, onEnv, onUp, onGone));
    if (subtle) roomSecrets(name).then(sec => { if (!closed) BROKERS.forEach(u => transports.push(mqttTransport(u, sec, onEnv, onUp))); }).catch(e => console.error(e));

    let ticks = 0;
    const stopTick = ticker(1000, () => {
      if (closed) return;
      if (++ticks % (HB_MS / 1000) === 0) hb();
      const now = Date.now(), gone = [];
      heard.forEach((t,p) => { if (now - t > GONE_MS) { heard.delete(p); const x = peers.get(p); if (x) { peers.delete(p); gone.push(x); } } });
      if (gone.length) fire([],gone);
    });
    const onVis = () => { if (document.visibilityState === 'visible' && !closed) hb(); }; // a phone may have frozen the page
    const onHide = () => { if (!closed) send(BYE); };
    document.addEventListener('visibilitychange', onVis);
    window.addEventListener('pagehide', onHide);

    const api = {
      name,
      emit(topic, data){
        let d; try { d = JSON.parse(JSON.stringify(data)); } catch(e){ return Promise.reject({code:'invalid_argument'}); }
        setTimeout(()=>deliver({topic, data:d, peer:myPeer, by:uid}),0);
        out('msg', {t:topic, d});
        return Promise.resolve();
      },
      on(topic, h){ (handlers[topic]=handlers[topic]||[]).push(h); return ()=>{ const a=handlers[topic]; const i=a.indexOf(h); if(i>=0) a.splice(i,1); }; },
      presence(){ return Promise.resolve(); },
      peers: snap,
      onPeers(h){ ph.push(h); setTimeout(()=>h({peers:snap(), joined:snap(), left:[], updated:[]}),0); return ()=>{ const i=ph.indexOf(h); if(i>=0) ph.splice(i,1); }; },
      connected(){ return transports.some(t => t.up()); },
      onConnection(h){ setTimeout(()=>h(api.connected()),0); return ()=>{}; },
      leave(){
        if (closed) return Promise.resolve();
        send(BYE); closed = true; stopTick();
        document.removeEventListener('visibilitychange', onVis); window.removeEventListener('pagehide', onHide);
        setTimeout(() => transports.forEach(t => t.close()), 300); // let the goodbye go out first
        return Promise.resolve();
      }
    };
    return Promise.race([ready, new Promise(r=>setTimeout(r,8000))]).then(()=>api);
  }

  const room = { join: async name => makeRoom(name), peers: () => [], onPeers(){ return ()=>{}; } };
  const user = { id: async () => uid, isOwner(){ return false; } };
  window.claude = { use: async n => {
    if (n === 'room') { if (USE_PEERJS) await waitPeerLib(); return (window.Peer || subtle) ? room : null; }
    if (n === 'user') return user;
    return null;
  } };
})();
