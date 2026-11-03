import asyncio, subprocess, sys
from playwright.async_api import async_playwright
async def main():
    srv = subprocess.Popen([sys.executable,"-m","http.server","8766","-d","/home/claude/cabo"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    await asyncio.sleep(1)
    async with async_playwright() as pw:
        b=await pw.chromium.launch(); p=await b.new_page()
        errs=[]; p.on("pageerror",lambda e: errs.append(str(e)))
        await p.goto("http://localhost:8766/index.html")
        await p.fill("#name","Me"); await p.click("#practice"); await p.click("#start"); await asyncio.sleep(0.5)
        await p.click("[data-a=peek]"); await asyncio.sleep(0.5)
        # record turn changes
        await p.evaluate("""() => { window.__t=[]; let last=null; setInterval(()=>{ const k=S.phase+':'+S.turn+':'+S.tc; if(k!==last){ __t.push([Date.now(),S.turn,S.phase]); last=k } },50) }""")
        # turn on match mode and keep it on while bots play
        sticky=[]
        armed=False
        for _ in range(120):
            st=await p.evaluate("({ph:S.phase,turn:S.turn,pd:S.pending,snap:snapMode})")
            if st["ph"]!="turn": break
            if st["turn"]==0:
                if st["snap"]: await p.click("[data-a=snap]")  # cancel to take my turn
                if st["pd"] is None: await p.click("[data-a=draw]")
                elif await p.locator("[data-a=discard]").count(): await p.click("[data-a=discard]")
                elif await p.locator("[data-a=skip]").count(): await p.click("[data-a=skip]")
                elif await p.locator("[data-a=kleave]").count(): await p.click("[data-a=kleave]")
                armed=False
            else:
                if not armed and not st["snap"]:
                    await p.click("[data-a=snap]"); armed=True
                elif armed: sticky.append(st["snap"])
            await asyncio.sleep(0.4)
            if len(sticky)>40: break
        t=await p.evaluate("__t")
        d=[(t[i+1][0]-t[i][0])/1000 for i in range(len(t)-1) if t[i][1]!=0 and t[i][2]=='turn']
        print("bot turn seconds:", [round(x,1) for x in d])
        print("min bot turn:", min(d) if d else None)
        print("match mode stayed on while bots played:", all(sticky), len(sticky), "samples")
        print("errors:", errs)
        await b.close()
    srv.terminate()
asyncio.run(main())
