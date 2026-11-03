# Cabo with Friends

An online version of the Cabo card game, played with house rules, so friends can play together from a link.

**Play:** open the site, then one person taps **Create a game** and shares the 4-letter code. Everyone else enters it and taps **Join**.

- `index.html` is the live site (built, single file)
- `src/game.html` is the game itself; `src/peer-shim.js` connects players over WebRTC (PeerJS)
- `python3 src/build.py` rebuilds `index.html`
- `tests/` holds browser tests (Playwright)
