"""Tiny MQTT 3.1.1-over-WebSocket broker (QoS 0 only) so the relay path can be tested offline.

    python3 fakebroker.py 8883   ->  ws://localhost:8883/mqtt
Also importable: `await serve(port)` returns the running server; `stats` counts traffic.
"""
import asyncio, sys
import websockets

subs = {}            # topic -> set of websockets
stats = {"publish": 0, "clients": 0, "plaintext": 0}

def varint(n):
    out = bytearray()
    while True:
        b, n = n % 128, n // 128
        out.append(b | (128 if n else 0))
        if not n: return bytes(out)

def packets(buf):
    """Yield (header, body) for each complete packet in buf; return leftover via StopIteration value."""
    while len(buf) >= 2:
        length, mul, i = 0, 1, 1
        while True:
            if i >= len(buf): return buf
            b = buf[i]; i += 1; length += (b & 127) * mul; mul *= 128
            if not b & 128: break
        if len(buf) < i + length: return buf
        yield buf[0], buf[i:i + length]
        buf = buf[i + length:]
    return buf

async def handle(ws):
    stats["clients"] += 1
    mine = set(); buf = b""
    try:
        async for msg in ws:
            buf += msg if isinstance(msg, bytes) else msg.encode()
            gen = packets(buf)
            while True:
                try: h, body = next(gen)
                except StopIteration as stop: buf = stop.value if stop.value is not None else b""; break
                kind = h >> 4
                if kind == 1: await ws.send(bytes([0x20, 2, 0, 0]))                       # CONNECT -> CONNACK
                elif kind == 8:                                                          # SUBSCRIBE -> SUBACK
                    pid, rest, granted = body[:2], body[2:], bytearray()
                    while rest:
                        n = (rest[0] << 8) | rest[1]; topic = rest[2:2 + n].decode(); rest = rest[3 + n:]
                        subs.setdefault(topic, set()).add(ws); mine.add(topic); granted.append(0)
                    await ws.send(bytes([0x90]) + varint(2 + len(granted)) + pid + bytes(granted))
                elif kind == 3:                                                          # PUBLISH -> fan out
                    n = (body[0] << 8) | body[1]; topic = body[2:2 + n].decode(); stats["publish"] += 1
                    if b"Ana" in body or b"\"k\"" in body: stats["plaintext"] += 1             # the relay must only see ciphertext
                    out = bytes([0x30]) + varint(len(body)) + body
                    for s in list(subs.get(topic, ())):
                        try: await s.send(out)
                        except Exception: pass
                elif kind == 12: await ws.send(bytes([0xD0, 0]))                         # PINGREQ -> PINGRESP
                elif kind == 14: await ws.close(); return                                # DISCONNECT
    except websockets.ConnectionClosed:
        pass
    finally:
        for t in mine: subs.get(t, set()).discard(ws)

async def serve(port):
    return await websockets.serve(handle, "localhost", port, subprotocols=["mqtt"])

if __name__ == "__main__":
    async def main():
        await serve(int(sys.argv[1]) if len(sys.argv) > 1 else 8883)
        await asyncio.Future()
    asyncio.run(main())
