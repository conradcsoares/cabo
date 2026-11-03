// Standalone networking: implements the small slice of claude.use('room'/'user') the game needs,
// over WebRTC via PeerJS. The first browser to claim a game code becomes the relay hub; if it
// leaves, the others race to become the new hub and reconnect automatically.
(function(){
  if (window.claude) return;
  window.__caboStandalone = true;
  const PRE = 'cabo-with-friends-v1-';
  const rid = n => { let s=''; const a='abcdefghijkmnpqrstuvwxyz23456789'; for(let i=0;i<n;i++) s+=a[Math.floor(Math.random()*a.length)]; return s; };
  // per-tab id (survives a refresh of the same tab, so a player can rejoin their seat)
  let uid = null; try { uid = sessionStorage.getItem('cabo-uid'); if(!uid){ uid='u'+rid(12); sessionStorage.setItem('cabo-uid',uid); } } catch(e) { uid='u'+rid(12); }
  const myPeer = 'p' + rid(10);
  const waitPeerLib = () => new Promise(res => { let k=0; const t=()=>{ if(window.Peer) return res(true); if(++k>60) return res(false); setTimeout(t,100); }; t(); });

  function makeRoom(name){
    const handlers = {}, ph = [], peers = new Map(), conns = new Map();
    const mk = (peer,by,me) => ({peer, by: by||null, isMe: !!me, sameTab: !!me, kind:'viewer', guest:false, presence:{}, updatedAt:Date.now()});
    peers.set(myPeer, mk(myPeer, uid, true));
    let peerObj = null, up = null, closed = false, isHub = false, connected = false;
    const hubId = PRE + name;
    const snap = () => Object.freeze([...peers.values()]);
    const fire = (joined,left) => { const s=snap(); ph.forEach(h=>setTimeout(()=>h({peers:s,joined,left,updated:[]}),0)); };
    const deliver = m => (handlers[m.topic]||[]).forEach(h => { try { h({topic:m.topic, data:m.data, peer:m.peer, by:m.by||null, isMe:m.peer===myPeer, sameTab:m.peer===myPeer, kind:'viewer', guest:false}); } catch(e){ console.error(e); } });
    const dropOthers = () => { const o=[...peers.values()].filter(x=>x.peer!==myPeer); o.forEach(x=>peers.delete(x.peer)); if(o.length) fire([],o); };
    const bcast = (d, except) => conns.forEach((c,label)=>{ if(label!==except){ try{ c.send(d); }catch(e){} } });

    let readyRes; const ready = new Promise(r=>readyRes=r);

    function tryHub(){
      if (closed) return;
      const p = new Peer(hubId); peerObj = p;
      p.on('open', () => { isHub = true; connected = true; dropOthers(); readyRes(); });
      p.on('connection', conn => {
        let label = null;
        conn.on('data', d => {
          if (!d || typeof d !== 'object') return;
          if (d.k === 'hello') {
            label = String(d.peer).slice(0,40); conns.set(label, conn);
            const np = mk(label, d.by); peers.set(label, np);
            conn.send({k:'roster', list:[...peers.values()].map(x=>({peer:x.peer, by:x.by}))});
            bcast({k:'join', peer:label, by:np.by}, label); fire([np],[]);
          } else if (d.k === 'msg' && label) {
            const m = {topic:String(d.topic), data:d.data, peer:label, by:(peers.get(label)||{}).by||null};
            deliver(m); bcast({k:'msg', ...m}, label);
          }
        });
        const gone = () => { if (label && conns.get(label) === conn) { conns.delete(label); const x = peers.get(label); peers.delete(label); bcast({k:'leave', peer:label}); if (x) fire([],[x]); } };
        conn.on('close', gone); conn.on('error', gone);
      });
      p.on('disconnected', () => { if (!closed) { try { p.reconnect(); } catch(e){} } });
      p.on('error', e => {
        if (e && e.type === 'unavailable-id') { try{ p.destroy(); }catch(_){} joinHub(); }
        else if (!isHub) { try{ p.destroy(); }catch(_){} setTimeout(tryHub, 1500); }
      });
    }

    function joinHub(){
      if (closed) return;
      const p = new Peer(); peerObj = p; isHub = false;
      p.on('open', () => {
        const c = p.connect(hubId, {reliable:true}); up = c;
        c.on('open', () => { connected = true; c.send({k:'hello', peer:myPeer, by:uid}); readyRes(); });
        c.on('data', d => {
          if (!d || typeof d !== 'object') return;
          if (d.k === 'roster') { const joined=[]; (d.list||[]).forEach(x=>{ if(x.peer!==myPeer && !peers.has(x.peer)){ const np=mk(x.peer,x.by); peers.set(x.peer,np); joined.push(np); } }); if(joined.length) fire(joined,[]); }
          else if (d.k === 'join') { if (d.peer!==myPeer && !peers.has(d.peer)) { const np=mk(d.peer,d.by); peers.set(d.peer,np); fire([np],[]); } }
          else if (d.k === 'leave') { const x=peers.get(d.peer); if(x){ peers.delete(d.peer); fire([],[x]); } }
          else if (d.k === 'msg') { if (d.peer !== myPeer) deliver(d); }
        });
        const lost = () => { if (up !== c) return; up = null; connected = false; dropOthers(); try{ p.destroy(); }catch(_){} if(!closed) setTimeout(tryHub, 300 + Math.random()*1500); };
        c.on('close', lost); c.on('error', lost);
      });
      p.on('error', e => {
        if (e && e.type === 'peer-unavailable') { try{ p.destroy(); }catch(_){} setTimeout(tryHub, 200 + Math.random()*400); }
        else if (!connected) { try{ p.destroy(); }catch(_){} setTimeout(tryHub, 1500); }
      });
    }

    tryHub();
    const api = {
      name,
      emit(topic, data){
        let d; try { d = JSON.parse(JSON.stringify(data)); } catch(e){ return Promise.reject({code:'invalid_argument'}); }
        const m = {topic, data:d, peer:myPeer, by:uid};
        setTimeout(()=>deliver(m),0);
        if (isHub) bcast({k:'msg', ...m}); else if (up) { try{ up.send({k:'msg', topic, data:d}); }catch(e){} }
        return Promise.resolve();
      },
      on(topic, h){ (handlers[topic]=handlers[topic]||[]).push(h); return ()=>{ const a=handlers[topic]; const i=a.indexOf(h); if(i>=0) a.splice(i,1); }; },
      presence(){ return Promise.resolve(); },
      peers: snap,
      onPeers(h){ ph.push(h); setTimeout(()=>h({peers:snap(), joined:snap(), left:[], updated:[]}),0); return ()=>{ const i=ph.indexOf(h); if(i>=0) ph.splice(i,1); }; },
      connected(){ return connected; },
      onConnection(h){ setTimeout(()=>h(connected),0); return ()=>{}; },
      leave(){ closed = true; try{ conns.forEach(c=>c.close()); }catch(e){} try{ peerObj && peerObj.destroy(); }catch(e){} return Promise.resolve(); }
    };
    window.addEventListener('pagehide', () => { try{ peerObj && peerObj.destroy(); }catch(e){} });
    return Promise.race([ready, new Promise(r=>setTimeout(r,8000))]).then(()=>api);
  }

  const room = { join: async name => makeRoom(name), peers: () => [], onPeers(){ return ()=>{}; } };
  const user = { id: async () => uid, isOwner(){ return false; } };
  window.claude = { use: async n => {
    if (n === 'room') return (await waitPeerLib()) ? room : null;
    if (n === 'user') return user;
    return null;
  } };
})();
