import asyncio, subprocess, sys, random
from playwright.async_api import async_playwright
import os, pathlib
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
os.makedirs(os.path.join(HERE, "out"), exist_ok=True)

import os
STANDALONE = os.environ.get("STANDALONE")
URL = "http://localhost:8765/" + ("index.html" if STANDALONE else "index.html")
MOCK = open(os.path.join(HERE, "fakepeer.js" if STANDALONE else "mock.js")).read()
errors = []

async def newpage(ctx, name):
    p = await ctx.new_page()
    p.on("pageerror", lambda e: errors.append(f"{name}: {e}"))
    p.on("console", lambda m: m.type == "error" and errors.append(f"{name} console: {m.text}"))
    await p.add_init_script(MOCK)
    await p.route("**/peerjs*", lambda r: r.fulfill(body="", content_type="application/javascript"))
    await p.goto(URL)
    if await p.locator("#name").count(): await p.fill("#name", name)
    return p

async def step(p):
    """Take one human action if it's this page's turn. Returns True if acted."""
    st = await p.evaluate("""() => { if(!S||!S.players) return null; const me=myIndex();
        return {phase:S.phase, me, give:!!(S.give&&S.give.from===me), turn:S.turn, pd:S.pending, peeked: me>=0?S.players[me].peeked:true}}""")
    if not st: return False
    if st["phase"] == "peek" and not st["peeked"]:
        await p.click("[data-a=peek]"); return True
    if st.get("give"):
        await p.locator(".me .card.click").first.click(); return True
    if st["phase"] != "turn" or st["turn"] != st["me"]: return False
    pd = st["pd"]
    btn = lambda a: p.locator(f"[data-a={a}]")
    if pd is None:
        r = random.random()
        if r < 0.08 and await btn("snap").count():
            await btn("snap").click(); await p.locator(".card.click").nth(random.randrange(4)).click()
        elif r < 0.15 and await btn("take").count() and await btn("take").is_enabled(): await btn("take").click()
        elif r < 0.2 and await btn("cabo").count(): await btn("cabo").click()
        else: await btn("draw").click()
        return True
    if pd["step"] == "decide":
        if pd["src"] == "discard" or random.random() < 0.4:
            n = random.choice([1,1,1,2])
            mine = p.locator(".me .card.click")
            cnt = await mine.count()
            for k in random.sample(range(cnt), min(n, cnt)): await mine.nth(k).click()
            await btn("exchange").click()
        elif await btn("use").count(): await btn("use").click()
        else: await btn("discard").click()
        return True
    if pd["step"] == "choose":
        await p.locator("[data-a^=as-]").nth(random.randrange(4)).click(); return True
    if pd["step"] == "king2":
        await btn(random.choice(["kswap","kleave"])).click(); return True
    if pd["step"] == "ability":
        ab = pd["ab"]
        if ab == "king":
            await p.locator(".me .card.click").first.click(); await p.locator(".opps .card.click").first.click()
            await btn("kinglook").click(); return True
        if ab == "peek": await p.locator(".me .card.click").first.click()
        elif ab == "spy": await p.locator(".opps .card.click").first.click()
        elif ab == "swap":
            await p.locator(".me .card.click").first.click()
            await p.locator(".opps .card.click").last.click()
        return True
    return False

async def phase(p): return await p.evaluate("S&&S.phase")

async def play_round(pages, limit=400):
    for _ in range(limit):
        ph = await phase(pages[0])
        if ph in ("roundEnd", "gameEnd"): return ph
        for p in pages:
            try:
                if await step(p): await asyncio.sleep(0.15)
            except Exception as e:
                pass
        await asyncio.sleep(0.25)
    return await phase(pages[0])

async def main():
    srv = subprocess.Popen([sys.executable, "-m", "http.server", "8765", "-d", ROOT], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    await asyncio.sleep(1)
    try:
        async with async_playwright() as pw:
            b = await pw.chromium.launch(channel=os.environ.get("PW_CHANNEL"))
            ctx = await b.new_context(viewport={"width": 1100, "height": 900})
            A = await newpage(ctx, "Conrad"); await A.wait_for_selector("#create:not([disabled])")
            await A.click("#create"); await A.wait_for_selector("#invite")
            link = await A.input_value("#invite"); print("invite", link)
            tail = ("?join=" + link.split("?join=",1)[1]) if "?join=" in link else ("#" + link.split("#",1)[1])
            Bp = await newpage(ctx, "Maya"); Cp = await newpage(ctx, "Jon")
            for P,nm in ((Bp,"Maya"),(Cp,"Jon")):
                await P.goto(URL + tail)          # opening the link joins automatically
                await P.wait_for_selector("#myname", timeout=15000)
                await P.fill("#myname", nm); await P.click("#rename")
            await asyncio.sleep(2.5)
            print("lobby on B:", await Bp.evaluate("S.players.map(p=>p.name)"), "B index", await Bp.evaluate("myIndex()"))
            await A.click("#addbot"); await asyncio.sleep(0.3)
            await A.screenshot(path=os.path.join(HERE, "out", "lobby.png"))
            await A.click("#start"); await asyncio.sleep(0.8)
            await asyncio.sleep(0.5); await Bp.click("[data-a=peek]"); await asyncio.sleep(0.3); await Bp.screenshot(path=os.path.join(HERE, "out", "peek.png"))
            pages = [A, Bp, Cp]
            # play a few steps then screenshot mid-game
            for _ in range(6):
                for p in pages: await step(p); await asyncio.sleep(0.2)
                await asyncio.sleep(0.4)
            await Bp.screenshot(path=os.path.join(HERE, "out", "mid.png"), full_page=True)
            ph = await play_round(pages); print("round1 ->", ph)
            vers = [await p.evaluate("S.ver") for p in pages]; print("vers", vers)
            same = await A.evaluate("JSON.stringify(S.players.map(p=>p.total))") == await Cp.evaluate("JSON.stringify(S.players.map(p=>p.total))")
            print("totals synced", same, await A.evaluate("S.players.map(p=>p.name+':'+p.total)"))
            await Cp.screenshot(path=os.path.join(HERE, "out", "results.png"), full_page=True)
            # host leaves -> takeover
            await A.evaluate("window.__mockBye ? window.__mockBye() : window.__killPeers()"); await A.close()
            await asyncio.sleep(6)
            print("hosts@6s:", await Bp.evaluate("isHost"), await Cp.evaluate("isHost"), await Bp.evaluate("[...peersHere].length"), await Cp.evaluate("[...peersHere].length"))
            await asyncio.sleep(6)
            print("hosts@12s:", await Bp.evaluate("isHost"), await Cp.evaluate("isHost"), await Bp.evaluate("S.ver"), await Cp.evaluate("S.ver"))
            newhost = Bp if await Bp.evaluate("isHost") else Cp
            await newhost.click("#again"); await asyncio.sleep(0.8)
            # Conrad is away now; let bot play for him
            await newhost.locator("[data-botify]").first.click(); await asyncio.sleep(0.3)
            ph = await play_round([Bp, Cp]); print("round2 ->", ph, await Bp.evaluate("S.players.map(p=>p.name+':'+p.total)"))
            # solo practice to game end
            D = await newpage(ctx, "Solo"); await D.click("#practice"); await D.click("#start")
            for r in range(30):
                ph = await play_round([D])
                if ph == "gameEnd": break
                await D.click("#again")
            print("solo:", ph, await D.evaluate("S.round"), await D.evaluate("S.players.map(p=>p.name+':'+p.total)"))
            await D.screenshot(path=os.path.join(HERE, "out", "gameend.png"), full_page=True)
            await b.close()
    finally:
        srv.terminate()
    print("ERRORS:", errors[:10])

asyncio.run(main())
