# Cabo with Friends

An online version of the Cabo card game, played with house rules, so friends can play together from a link.

**Play:** open the site, then one person taps **Create a game** and shares the 4-letter code or the invite link. Everyone else enters the code and taps **Join**, or just opens the link. Players can be on different devices and different networks (home Wi‑Fi, mobile data, work).

- `index.html` is the live site (built, single file)
- `src/game.html` is the game itself; `src/peer-shim.js` connects players over the internet
- `python3 src/build.py` rebuilds `index.html`
- `tests/` holds browser tests (Playwright)
- `GOALS.md` lists what the game is meant to do

## How players connect

Every message goes out over two paths at once and is de-duplicated on arrival, so a game keeps working when either one is blocked:

1. **Relay:** free public MQTT brokers (`broker.emqx.io`, `broker.hivemq.com`). Both players only make an outgoing secure WebSocket, so this works between any two networks. Messages are encrypted (AES-GCM) with a key derived from the game code, and the topic is a hash of it, so the brokers only see ciphertext. No account or API key is needed.
2. **Direct:** WebRTC via PeerJS, used when the two networks allow a direct connection.

## Tests

```bash
pip install playwright websockets && playwright install chromium
python3 tests/online_test.py          # separate browser profiles join by code and link and play, over a local relay
python3 tests/online_test.py --live   # also over the real public brokers
```

On macOS 13, where Playwright ships no Chromium build, set `PW_CHANNEL=chrome` to use the installed Google Chrome.
