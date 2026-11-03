import asyncio
from playwright.async_api import async_playwright
JS = r"""() => {
 const out={};
 const mk=()=>{const T=newLobby('x','T');T.players=[{name:'A'},{name:'B'},{name:'C'}];startGame(T);return T};
 // card values
 const T=mk(); out.deck=[T.vals.length, T.vals.filter(v=>v===-2).length, T.vals.filter(v=>v===-1).length, T.vals.filter(v=>v===13).length];
 // force hands for tie-breaks: A: [5,-1+...]
 const set=(T,pi,ids)=>{T.players[pi].hand=ids};
 const idOf=(T,rk,su)=>T.vals.findIndex((v,id)=>T.rk[id]===rk&&(!su||T.su[id]===su));
 let G=mk(); G.caboBy=1;
 set(G,0,[idOf(G,3,'♠'),idOf(G,2,'♠')]);           // 5 pts, 2 cards
 set(G,1,[idOf(G,1,'♠'),idOf(G,1,'♥'),idOf(G,3,'♥')]); // 5 pts, 3 cards
 set(G,2,[idOf(G,10,'♠')]);
 endRound(G); out.mostCards=[G.winners, G.tb];
 G=mk(); G.caboBy=1;
 set(G,0,[idOf(G,3,'♠'),idOf(G,2,'♠')]); set(G,1,[idOf(G,4,'♥'),idOf(G,1,'♥')]); set(G,2,[idOf(G,10,'♠')]);
 endRound(G); out.caller=[G.winners,G.tb];
 G=mk(); G.caboBy=2;
 set(G,0,[idOf(G,3,'♠'),idOf(G,2,'♠')]); set(G,1,[idOf(G,4,'♥'),idOf(G,1,'♥')]); set(G,2,[idOf(G,10,'♠')]);
 endRound(G); out.tie=[G.winners,G.tb];
 // red king -1 + joker -2
 G=mk(); set(G,0,[idOf(G,13,'♥'),idOf(G,0)]); set(G,1,[idOf(G,13,'♠')]); set(G,2,[idOf(G,5,'♠')]); endRound(G); out.neg=G.res.map(r=>r.sum);
 // snap own correct / other correct + give / wrong + penalty / joker wild
 G=mk(); G.players.forEach(p=>p.peeked=true); G.phase='turn'; G.turn=0;
 G.discard=[idOf(G,6,'♣')];
 set(G,0,[idOf(G,6,'♠'),idOf(G,9,'♠')]); set(G,1,[idOf(G,6,'♥'),idOf(G,0)]); set(G,2,[idOf(G,4,'♠'),idOf(G,5,'♠')]);
 out.snapOwn=[apply(G,2,{t:'snap',target:0,slot:0}), G.players[0].hand[0], G.give];
 out.give=[apply(G,2,{t:'give',slot:1}), G.players[0].hand[0]===idOf(G,5,'♠'), G.players[2].hand[1], G.give];
 out.snapSelf=[apply(G,1,{t:'snap',target:1,slot:0}), G.players[1].hand[0]];
 const before=G.players[0].hand.length;
 out.wrong=[apply(G,0,{t:'snap',target:2,slot:0}), G.players[0].hand.length-before, knows(G,1,G.players[2].hand[0])];
 out.jokerSteal=[apply(G,0,{t:'snap',target:1,slot:1}), G.players[1].hand[1], !!G.give];
 out.takeGone=apply(G,0,{t:'take'});
 out.multiSwap=(()=>{G.give=null;G.pending={src:'deck',id:G.deck.pop(),step:'decide'};return apply(G,0,{t:'exchange',slots:[0,1]})})();
 return out;
}"""
async def main():
    async with async_playwright() as pw:
        b=await pw.chromium.launch(); p=await b.new_page()
        await p.goto("file:///home/claude/cabo/index.html")
        r=await p.evaluate(JS)
        for k,v in r.items(): print(k, v)
        await b.close()
asyncio.run(main())
