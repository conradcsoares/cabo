"""Table rules: up to 7 players; the discard pile is reshuffled only when someone needs a card;
one match per discarded card (a later one costs a penalty card); every action is shown to everyone.

    python3 tests/deck_test.py      (exits non-zero on failure)
"""
import asyncio, os, pathlib, sys, json
from playwright.async_api import async_playwright
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)

JS = r"""() => {
  const out = {};
  const game = n => { const T = newLobby('x','T'); for (let k=0;k<n;k++) T.players.push({name:'P'+k}); startGame(T); T.phase='turn'; return T; };

  // 7 players: everyone gets 4 cards, one face up, the rest is the deck
  let G = game(7);
  out.sevenDeal = [G.players.every(p=>p.hand.length===4), G.deck.length, G.discard.length];
  out.sevenStateBytes = JSON.stringify(G).length;

  // deck runs out: ending a turn does NOT reshuffle
  G = game(3);
  G.discard.push(...G.deck.splice(0)); const pile = G.discard.length, t0 = G.turn;
  endTurn(G);
  out.endTurnNoShuffle = [G.deck.length, G.discard.length === pile, G.turn !== t0, G.phase];

  // ...the next draw does: everything but the top discard goes back in, shuffled
  const top = G.discard[G.discard.length-1];
  const err = apply(G, G.turn, {t:'draw'});
  out.drawShuffles = [err, G.discard.length, G.discard[0] === top, G.deck.length === pile - 2, !!G.pending, G.log.slice(0,2)];

  // nothing to draw anywhere (deck empty, only the top discard): the round ends
  G = game(2); G.deck = []; G.discard = G.discard.slice(-1);
  endTurn(G);
  out.nothingLeftEndsRound = G.phase;

  // one match per discarded card
  const idOf=(T,rk,skip=[])=>T.vals.findIndex((v,id)=>T.rk[id]===rk&&!skip.includes(id));
  G = game(3); G.turn=0;
  const t7=idOf(G,7), a7=idOf(G,7,[t7]), b7=idOf(G,7,[t7,a7]), bOther=idOf(G,5);
  G.discard.push(t7); G.up[t7]=1; G.matched=false;
  G.players[1].hand[0]=a7; G.players[2].hand[0]=b7; G.players[2].hand[1]=bOther;
  const e1=apply(G,1,{t:'snap',target:1,slot:0});
  out.firstMatch=[e1, G.discard[G.discard.length-1]===a7, G.matched, G.last.tag, JSON.stringify(G.last.cards)];
  const before=G.players[2].hand.length;
  const e2=apply(G,2,{t:'snap',target:2,slot:0});
  out.tooSlow=[e2, G.players[2].hand.length-before, G.players[2].hand[0]===b7, !G.up[b7]&&!(G.kn[b7]||[]).includes(0), G.last.tag, G.last.text];
  // a fresh discard opens matching again
  G.turn=0; apply(G,0,{t:'draw'}); apply(G,0,{t:'discard'});
  out.reopened=G.matched;

  // every action names the player, the card owner and position, and highlights it for everyone
  const acts={};
  const withPower=(ab,a)=>{ const T=game(3); T.turn=0; T.pending={src:'deck',id:T.deck.pop(),step:'ability',ab}; const e=apply(T,0,a); return [e,T.last.tag,T.last.text,JSON.stringify(T.last.cards)]; };
  acts.spy=withPower('spy',{t:'ability',target:2,slot:1});
  acts.peek=withPower('peek',{t:'ability',slot:2});
  acts.swap=withPower('swap',{t:'ability',slot:0,target:1,tslot:3});
  acts.king=withPower('king',{t:'ability',picks:[[0,1],[2,0]]});
  out.acts=acts;

  // the host seats at most 7 people
  S = newLobby('host','ABCD'); isHost = true; myPeer = 'host'; S.players.push({pid:'h', peer:'host', name:'Host'});
  for (let k=1;k<=9;k++) onRemoteAct({data:{t:'join', name:'P'+k}, peer:'p'+k, by:'u'+k});
  out.seated = S.players.length;
  return out;
}"""

async def main():
    fails = []
    def check(name, ok, got):
        print(("PASS " if ok else "FAIL ") + name + "  " + json.dumps(got, ensure_ascii=False))
        if not ok: fails.append(name)
    async with async_playwright() as pw:
        b = await pw.chromium.launch(channel=os.environ.get("PW_CHANNEL"))
        p = await b.new_page(); await p.goto(pathlib.Path(ROOT, "index.html").as_uri())
        r = await p.evaluate(JS); await b.close()
    check("7 players are dealt 4 each, 25 left to draw", r["sevenDeal"] == [True, 25, 1], r["sevenDeal"])
    check("7-player state fits a 3900-byte message", r["sevenStateBytes"] < 3900, r["sevenStateBytes"])
    check("an empty deck is not reshuffled at the end of a turn", r["endTurnNoShuffle"][:3] == [0, True, True] and r["endTurnNoShuffle"][3] == "turn", r["endTurnNoShuffle"])
    d = r["drawShuffles"]
    check("drawing from an empty deck reshuffles all but the top discard", d[0] is None and d[1] == 1 and d[2] and d[3] and d[4] and d[5][0].endswith("drew a card") and d[5][1] == "Deck reshuffled", d)
    check("with nothing left to draw, the round ends", r["nothingLeftEndsRound"] in ("roundEnd", "gameEnd"), r["nothingLeftEndsRound"])
    check("the lobby seats at most 7", r["seated"] == 7, r["seated"])
    f = r["firstMatch"]
    check("first match on a card works and is shown to all", f[0] is None and f[1] and f[2] and f[3] == "MATCHED" and f[4] == "[[1,0]]", f)
    t = r["tooSlow"]
    check("a second match on the same card costs one penalty card, card stays hidden", t[0] is None and t[1] == 1 and t[2] and t[3] and t[4] == "PENALTY" and "too slow" in t[5], t)
    check("a new discard opens matching again", r["reopened"] is False, r["reopened"])
    a = r["acts"]
    check("SPY is shown: who, whose card, which one", a["spy"][1] == "SPIED" and "used SPY on P2's top-right card" in a["spy"][2] and a["spy"][3] == "[[2,1]]", a["spy"])
    check("PEEK is shown with the card position", a["peek"][1] == "PEEKED" and "bottom-left" in a["peek"][2] and a["peek"][3] == "[[0,2]]", a["peek"])
    check("SWAP is shown with both cards", a["swap"][1] == "SWAPPED" and "P1's bottom-right" in a["swap"][2] and a["swap"][3] == "[[0,0],[1,3]]", a["swap"])
    check("KING look is shown with both cards", a["king"][1] == "LOOKED" and "P2's top-left" in a["king"][2] and a["king"][3] == "[[0,1],[2,0]]", a["king"])
    print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED"); sys.exit(1 if fails else 0)

asyncio.run(main())
