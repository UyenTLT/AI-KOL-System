#!/usr/bin/env python3
"""Headless end-to-end check: text -> cloned voice -> lip-synced video.

LiveTalking's `/human` endpoint needs a `sessionid`, which only exists after a WebRTC
handshake -- so a browser is normally required to test anything. This does the
handshake with aiortc instead, drives one utterance, records the returned A/V to an
mp4, and reports what actually arrived.

Proves three things at once:
  * the WebRTC session negotiates and media flows,
  * text reaches TTS (watch the api_v2 log for a matching /tts request),
  * video frames are produced in step with the audio (lip-sync path is alive).

Run with the LiveTalking venv (it owns aiortc + av):

    LiveTalking\\.venv\\Scripts\\python.exe tools\\livetalking\\verify_lipsync.py \\
        --text "大家好，我是 Lena。" --seconds 12 --out out.mp4
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.request


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="http://127.0.0.1:8010")
    ap.add_argument("--text", default="大家好，我是 Lena。今天分享一個好物。")
    ap.add_argument("--seconds", type=float, default=12.0, help="how long to record")
    ap.add_argument("--out", default="lipsync_check.mp4")
    ap.add_argument("--mode", default="echo", choices=["echo", "chat"],
                    help="echo repeats --text verbatim; chat sends it to the persona LLM "
                         "and the avatar speaks the generated reply")
    args = ap.parse_args()

    from aiortc import RTCPeerConnection, RTCSessionDescription
    from aiortc.contrib.media import MediaRecorder

    pc = RTCPeerConnection()
    # recvonly: we only consume the avatar's A/V.
    pc.addTransceiver("video", direction="recvonly")
    pc.addTransceiver("audio", direction="recvonly")

    recorder = MediaRecorder(args.out)
    counts = {"video": 0, "audio": 0}

    @pc.on("track")
    def on_track(track):
        print(f"  track received: {track.kind}", flush=True)
        recorder.addTrack(track)

        # Count frames without consuming them away from the recorder.
        original = track.recv

        async def counting_recv():
            frame = await original()
            counts[track.kind] += 1
            return frame

        track.recv = counting_recv

    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)

    payload = json.dumps({"sdp": pc.localDescription.sdp,
                          "type": pc.localDescription.type}).encode()
    req = urllib.request.Request(f"{args.host}/offer", data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        answer = json.loads(resp.read())
    sessionid = answer.get("sessionid")
    print(f"  session negotiated: sessionid={sessionid}", flush=True)

    await pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"],
                                                        type=answer["type"]))
    await recorder.start()
    await asyncio.sleep(1.5)  # let media start flowing before speaking

    body = json.dumps({"sessionid": sessionid, "text": args.text,
                       "type": args.mode}).encode()
    print(f"  mode={args.mode}  text={args.text!r}", flush=True)
    req = urllib.request.Request(f"{args.host}/human", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        print(f"  /human -> {resp.read().decode()}", flush=True)

    print(f"  recording {args.seconds}s ...", flush=True)
    await asyncio.sleep(args.seconds)

    await recorder.stop()
    await pc.close()

    print(f"\nframes: video={counts['video']}  audio={counts['audio']}")
    print(f"wrote : {args.out}")
    if counts["video"] == 0:
        print("FAIL: no video frames -- avatar/lip-sync pipeline did not produce output")
        return 1
    if counts["audio"] == 0:
        print("FAIL: no audio frames -- TTS did not reach the stream")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
