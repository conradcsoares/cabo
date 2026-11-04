"""Calling CABO takes two deliberate taps.

    python3 tests/cabo_confirm_test.py      (exits non-zero on failure)
"""
import asyncio, os, pathlib, sys
from playwright.async_api import async_playwright
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)

async def main():
    fails = []
    def check(name, ok, got=""):
        print(("PASS " if ok else "FAIL ") + name + (f"  ({got})" if got != "" else ""))
        if not ok: fails.append(name)
    async with async_playwright() as pw:
        b = await pw.chromium.launch(channel=os.environ.get("PW_CHANNEL"))
        p = await b.new_page(); errs = []; p.on("pageerror", lambda e: errs.append(str(e)))
        await p.goto(pathlib.Path(ROOT, "index.html").as_uri())
        await p.fill("#name", "Me"); await p.click("#practice"); await p.click("#start")
        await p.wait_for_timeout(200); await p.click("[data-a=peek]")
        await p.wait_for_function("S.phase==='turn'")
        # make it my turn with nothing drawn, and keep the bots still
        await p.evaluate("clearTimeout(botTimer); clearTimeout(snapTimer); S.turn=0; S.pending=null; render()")

        await p.click("[data-a=cabo]")
        check("first tap only asks", await p.evaluate("S.caboBy") is None and await p.locator("[data-a=caboyes]").count() == 1)
        check("Draw and Match are hidden while asking", await p.locator("[data-a=draw]").count() == 0 and await p.locator("[data-a=snap]").count() == 0)
        await p.click("[data-a=caboyes]")  # immediately: a double-tap
        check("a double-tap doesn't call CABO", await p.evaluate("S.caboBy") is None)
        await p.click("[data-a=cabono]")
        check("Cancel goes back to Draw / CABO", await p.evaluate("S.caboBy") is None and await p.locator("[data-a=draw]").count() == 1)

        await p.click("[data-a=cabo]"); await p.wait_for_timeout(5400)
        check("the question lapses after 5 s", await p.locator("[data-a=caboyes]").count() == 0 and await p.locator("[data-a=cabo]").count() == 1)

        await p.click("[data-a=cabo]"); await p.wait_for_timeout(600); await p.click("[data-a=caboyes]")
        check("a deliberate second tap calls CABO", await p.evaluate("S.caboBy") == 0, await p.evaluate("S.log[0]"))
        check("no page errors", not errs, errs)
        await b.close()
    print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED"); sys.exit(1 if fails else 0)

asyncio.run(main())
