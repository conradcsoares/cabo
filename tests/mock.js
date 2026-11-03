// Mock of the platform's claude.use('room'/'user') using BroadcastChannel between tabs
(function(){
  const myPeer = 'p' + Math.random().toString(36).slice(2,10);
  const myUid = 'u' + Math.random().toString(36).slice(2,10);
  function makeRoom(name){
    const ch = new BroadcastChannel('mock-'+name);
    const peers = new Map(); peers.set(myPeer,{peer:myPeer,by:myUid,isMe:true,sameTab:true,kind:'viewer',guest:false,presence:{},updatedAt:Date.now()});
    const handlers = {}; const ph = [];
    const snap = () => Object.freeze([...peers.values()]);
    const fire = (joined,left) => { const s=snap(); ph.forEach(h=>setTimeout(()=>h({peers:s,joined,left,updated:[]}),0)); };
    ch.onmessage = e => { const m=e.data;
      if(m.k==='hello'){ if(!peers.has(m.peer)){const p={peer:m.peer,by:m.by,isMe:false,sameTab:false,kind:'viewer',guest:false,presence:{},updatedAt:Date.now()};peers.set(m.peer,p);fire([p],[]);} ch.postMessage({k:'here',peer:myPeer,by:myUid}); }
      if(m.k==='here'){ if(!peers.has(m.peer)){const p={peer:m.peer,by:m.by,isMe:false,sameTab:false,kind:'viewer',guest:false,presence:{},updatedAt:Date.now()};peers.set(m.peer,p);fire([p],[]);} }
      if(m.k==='bye'){ const p=peers.get(m.peer); if(p){peers.delete(m.peer);fire([],[p]);} }
      if(m.k==='msg'){ (handlers[m.topic]||[]).forEach(h=>h({topic:m.topic,data:m.data,peer:m.peer,by:m.by,isMe:false,sameTab:false,kind:'viewer',guest:false})); }
    };
    ch.postMessage({k:'hello',peer:myPeer,by:myUid});
    window.addEventListener('beforeunload',()=>ch.postMessage({k:'bye',peer:myPeer}));
    window.__mockBye = () => ch.postMessage({k:'bye',peer:myPeer});
    return {
      name,
      emit(topic,data){ const d=JSON.parse(JSON.stringify(data)); if(JSON.stringify(d).length>4096) return Promise.reject({code:'invalid_argument'});
        ch.postMessage({k:'msg',topic,data:d,peer:myPeer,by:myUid});
        (handlers[topic]||[]).forEach(h=>setTimeout(()=>h({topic,data:d,peer:myPeer,by:myUid,isMe:true,sameTab:true,kind:'viewer',guest:false}),0));
        return Promise.resolve(); },
      on(topic,h){ (handlers[topic]=handlers[topic]||[]).push(h); return ()=>{} },
      presence(){ return Promise.resolve() },
      peers: snap,
      onPeers(h){ ph.push(h); setTimeout(()=>h({peers:snap(),joined:snap(),left:[],updated:[]}),0); return ()=>{const i=ph.indexOf(h);if(i>=0)ph.splice(i,1)} },
      connected(){return true}, onConnection(h){setTimeout(()=>h(true),0);return()=>{}},
      leave(){ ch.postMessage({k:'bye',peer:myPeer}); ch.close(); return Promise.resolve() }
    };
  }
  const room = { join: async (name)=>makeRoom(name), peers:()=>[], onPeers(){return()=>{}} };
  const user = { id: async ()=>myUid, isOwner(){return false} };
  window.claude = { use: async (n) => n==='room'?room : n==='user'?user : null };
})();
