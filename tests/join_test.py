import asyncio, subprocess, sys
from playwright.async_api import async_playwright
URL="http://localhost:8767/dist/index.html"; FAKE=open("fakepeer.js").read()
async def page(ctx):
    p=await ctx.new_page(); await p.add_init_script(FAKE)
    await p.route("**/peerjs*", lambda r: r.fulfill(body="", content_type="application/javascript")); return p
async def main():
    srv=subprocess.Popen([sys.executable,"-m","http.server","8767","-d","/home/claude/cabo"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); await asyncio.sleep(1)
    async with async_playwright() as pw:
        b=await pw.chromium.launch(); ctx=await b.new_context()
        A=await page(ctx); await A.goto(URL); await A.fill("#name","Conrad"); await A.wait_for_selector("#create:not([disabled])"); await A.click("#create")
        await A.wait_for_selector(".code"); code=await A.inner_text(".code")
        B=await page(ctx); await B.goto(URL); await B.wait_for_selector("#joincode:not([disabled])"); await B.fill("#name","Maya"); await B.fill("#code",code.lower()); await B.click("#joincode")
        C=await page(ctx); await C.goto(URL+"#join-"+code.lower()); 
        await asyncio.sleep(4)
        print("players:", await A.evaluate("S.players.map(p=>p.name)"))
        await A.click("#start"); await asyncio.sleep(1)
        print("invite button in game:", await A.locator("#invbtn").count())
        await b.close()
    srv.terminate()
asyncio.run(main())
