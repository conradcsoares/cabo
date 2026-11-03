"""Players on separate "devices" (separate browser profiles that share nothing) join and play.

    python3 tests/online_test.py          # offline: relay path through tests/fakebroker.py, plus both paths at once
    python3 tests/online_test.py --live   # also through the real public MQTT brokers on the internet

Exits non-zero if any check fails.
"""
import asyncio, subprocess, sys, os, json
from playwright.async_api import async_playwright
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import fakebroker

PORT, BROKER_PORT = 8768, 8884
URL = f"http://localhost:{PORT}/index.html"
FAKE = open(os.path.join(HERE, "fakepeer.js")).read()
LOCAL = [f"ws://localhost:{BROKER_PORT}/mqtt"]
failures, errors = [], []

def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not ok: failures.append(name)

async def device(browser, label, brokers, peerjs):
    """A fresh browser profile: no shared storage or BroadcastChannel with any other device."""
    ctx = await browser.new_context()
    p = await ctx.new_page()
    p.on("pageerror", lambda e: errors.append(f"{label}: {e}"))
    init = f"window.__caboBrokers = {json.dumps(brokers)};"
    if not peerjs: init += "window.__caboPeerJS = false;"
    await p.add_init_script(init)
    if peerjs: await p.add_init_script(FAKE)
    await p.route("**/peerjs*", lambda r: r.fulfill(body="", content_type="application/javascript"))
    return p

async def until(p, js, timeout=15):
    for _ in range(int(timeout * 10)):
        try:
            if await p.evaluate(js): return True
        except Exception: pass
        await asyncio.sleep(0.1)
    return False

async def scenario(b, tag, brokers, peerjs, same_device=False):
    print(f"--- {tag}")
    if same_device:  # fake PeerJS only works inside one profile, so these "devices" share one
        ctx = await b.new_context()
        await ctx.add_init_script(f"window.__caboBrokers = {json.dumps(brokers)};")
        await ctx.add_init_script(FAKE)
        await ctx.route("**/peerjs*", lambda r: r.fulfill(body="", content_type="application/javascript"))
        async def mk(label):
            p = await ctx.new_page(); p.on("pageerror", lambda e: errors.append(f"{label}: {e}")); return p
    else:
        async def mk(label): return await device(b, label, brokers, peerjs)

    A = await mk("A"); await A.goto(URL); await A.fill("#name", "Ana")
    await A.wait_for_selector("#create:not([disabled])"); await A.click("#create")
    await A.wait_for_selector(".code"); code = (await A.inner_text(".code")).strip()
    link = await A.input_value("#invite")
    check(f"{tag}: invite link carries the code", link.endswith("?join=" + code), link)

    B = await mk("B"); await B.goto(URL)                       # joins by typing the code
    await B.wait_for_selector("#joincode:not([disabled])"); await B.fill("#name", "Ben")
    await B.fill("#code", code.lower()); await B.click("#joincode")
    C = await mk("C"); await C.goto(URL + "?join=" + code)       # joins by opening the invite link

    names = "JSON.stringify(S&&S.players.map(p=>p.name).sort())"
    ok = await until(A, "S&&S.players.length===3", 20)
    check(f"{tag}: host sees code-joiner and link-joiner", ok, await A.evaluate(names))
    ok = all([await until(P, "S&&S.players.length===3&&myIndex()>=0", 10) for P in (B, C)])
    check(f"{tag}: both joiners see the full lobby and their own seat", ok)
    logs = await A.evaluate("S.log.filter(l=>/joined/.test(l)).length")
    check(f"{tag}: each join is counted once", logs == 2, f"{logs} join lines")

    await A.click("#start")
    ok = all([await until(P, "S&&S.phase==='peek'", 10) for P in (A, B, C)])
    check(f"{tag}: game start reaches every player", ok)
    for P in (A, B, C): await P.click("[data-a=peek]")
    ok = all([await until(P, "S&&S.phase==='turn'", 10) for P in (A, B, C)])
    check(f"{tag}: everyone's peeks sync and the first turn begins", ok)

    # whoever's turn it is draws and discards from their own device
    pages = {await P.evaluate("myIndex()"): P for P in (A, B, C)}
    turn = await A.evaluate("S.turn"); T = pages[turn]
    await T.click("[data-a=draw]"); await until(T, "!!document.querySelector('[data-a=discard]')", 5)
    await T.click("[data-a=discard]")
    ok = all([await until(P, f"S.turn!=={turn}", 10) for P in (A, B, C)])
    vers = [await P.evaluate("S.ver") for P in (A, B, C)]
    piles = {await P.evaluate("JSON.stringify(S.discard)") for P in (A, B, C)}
    check(f"{tag}: a move made on one device shows up on all of them", ok and len(piles) == 1, f"vers {vers}")

    await B.close(run_before_unload=True)  # Ben closes the tab
    ok = await until(A, "peersHere.size===2", 20)
    check(f"{tag}: host notices a player who closed the tab", ok)
    await A.close(run_before_unload=True)  # the host leaves; Cara's device should take over hosting
    ok = await until(C, "isHost", 25)
    check(f"{tag}: when the host leaves, a remaining player takes over", ok)
    await C.close()

async def main():
    live = "--live" in sys.argv
    srv = subprocess.Popen([sys.executable, "-m", "http.server", str(PORT), "-d", ROOT], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    broker = await fakebroker.serve(BROKER_PORT)
    await asyncio.sleep(0.8)
    try:
        async with async_playwright() as pw:
            b = await pw.chromium.launch(channel=os.environ.get("PW_CHANNEL"))  # PW_CHANNEL=chrome uses installed Chrome
            await scenario(b, "relay only, separate devices", LOCAL, peerjs=False)
            check("relay carried the traffic", fakebroker.stats["publish"] > 20, f"{fakebroker.stats['publish']} publishes")
            check("relay only ever sees ciphertext", fakebroker.stats["plaintext"] == 0)
            await scenario(b, "one relay down, the other up", ["ws://localhost:9/mqtt"] + LOCAL, peerjs=False)
            await scenario(b, "relay + direct together", LOCAL, peerjs=True, same_device=True)
            await scenario(b, "direct only (no relay reachable)", [], peerjs=True, same_device=True)
            if live:
                await scenario(b, "LIVE public brokers, separate devices", ["wss://broker.emqx.io:8084/mqtt", "wss://broker.hivemq.com:8884/mqtt"], peerjs=False)
            await b.close()
    finally:
        broker.close(); srv.terminate()
    if errors: check("no page errors", False, "; ".join(errors[:5]))
    print("\nALL PASSED" if not failures else f"\n{len(failures)} FAILED")
    sys.exit(1 if failures else 0)

asyncio.run(main())
