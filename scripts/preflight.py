#!/usr/bin/env python3
"""
preflight.py  -  is everything ready for Yotie to run?

Checks, in a few seconds, the things that have stopped a run before: the API
key file, the internet and Claude, the cable to the robot, the Chatterbox voice,
the gesture server and the robot's mode. Nothing is said, nothing is sent to the
arms and nothing is changed.

Each line is  [ok]  ready,  [note]  worth knowing,  or  [FIX]  with what to do.

Run it with the same settings as the conversation, after the gesture server is
up (scripts/convention.sh does both):
  python3 scripts/preflight.py [network_interface]
  python3 scripts/preflight.py lo --no-robot        # no robot attached
"""

import argparse
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
ROBOT_ADDRESS = "192.168.123.161"     # the G1's own computer on the robot cable
ROBOT_SUBNET = "192.168.123."
CLAUDE_SECONDS = 20.0

to_fix = []


def say(level: str, text: str, fix: str = ""):
    print(f"  [{level}] {text}")
    if fix:
        print(f"         -> {fix}")
    if level == "FIX":
        to_fix.append(text)


def env_file() -> dict:
    """The settings in the project's `env` file, loaded the way sb01_conversation.py loads them."""
    found = {}
    path = os.path.join(ROOT, "env")
    if os.path.isfile(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    found[key.strip()] = value.strip()
    os.environ.update(found)
    return found


def setting(name: str) -> str:
    return os.environ.get(name, "").strip()


def check_settings(in_file: dict):
    print("1. Settings")
    if not os.path.isfile(os.path.join(ROOT, "env")):
        other = os.path.isfile(os.path.join(ROOT, ".env"))
        say("note", "there is no file named env in the project folder" + (", but there is one named .env" if other else ""),
            "the program reads env (no dot): cp .env env" if other else "")
    key = setting("ANTHROPIC_API_KEY")
    if local_llm():
        say("ok", "replies come from the local model: no API key is needed")
    elif not key:
        say("FIX", "ANTHROPIC_API_KEY is not set, so the program stops at startup",
            "put ANTHROPIC_API_KEY=... in the file named env in the project folder")
    else:
        say("ok", "the Claude API key is set" + (" (from the env file)" if "ANTHROPIC_API_KEY" in in_file else ""))
    overriding = sorted(name for name in in_file if name.startswith("SB01_"))
    if overriding:
        say("note", f"the env file sets {', '.join(overriding)}: those win over anything typed on the command line")

    voice = setting("SB01_VOICE").lower() or "edge"
    url = setting("SB01_GESTURE_URL")
    cues = setting("SB01_GESTURE_CUES") == "1"
    print(f"      replies from:      {'a local model (Ollama)' if local_llm() else 'Claude, over the internet   (SB01_LLM=local for a local model)'}")
    print(f"      voice:             {voice}" + ("" if voice == "chatterbox" else "   (SB01_VOICE=chatterbox for the Chatterbox voice)"))
    print(f"      arm gestures:      {url or 'OFF  (SB01_GESTURE_URL is not set)'}")
    side = "right" if setting("SB01_BOARD_SIDE").lower() == "right" else "left"
    print("      teaching gestures: " + (f"on, pointing to the robot's {side}" if cues and url else "off   (SB01_GESTURE_CUES=1 turns them on)"))
    if voice not in ("edge", "chatterbox"):
        say("FIX", f"SB01_VOICE is {voice!r}, which is not a voice", "use SB01_VOICE=chatterbox")
    if cues and not url:
        say("FIX", "SB01_GESTURE_CUES=1 does nothing without SB01_GESTURE_URL", "add SB01_GESTURE_URL=http://127.0.0.1:8765")
    if setting("SB01_GESTURE_WAIST").lower() == "free":
        say("FIX", "SB01_GESTURE_WAIST=free lets the waist go: the torso bent backward with it on 2026-10-09",
            "remove SB01_GESTURE_WAIST unless this is a tethered experiment")
    cloud = sorted(name for name in os.environ if name.startswith("ROBOGESTURE_VOLC_"))
    if cloud:
        say("FIX", f"{', '.join(cloud)} set: these are the keys for RoboGesture's own cloud mode, which sends audio to ByteDance",
            "Yotie does not use that mode: remove them (unset, and take them out of ~/.bashrc)")
    notes = os.path.join(ROOT, "reference", "class")
    count = len([n for n in os.listdir(notes) if n.lower().endswith((".md", ".txt"))]) if os.path.isdir(notes) else 0
    say("ok" if count else "note", f"{count} course material files will be given to the model")


def local_llm() -> bool:
    return setting("SB01_LLM").lower() == "local"


def check_local_model():
    print("2. Local model")
    import json
    url = (setting("SB01_LOCAL_URL") or "http://127.0.0.1:11434").rstrip("/")
    with open(os.path.join(ROOT, "scripts", "sb01_conversation.py"), encoding="utf-8") as f:
        default = re.search(r'SB01_LOCAL_MODEL", ""\).strip\(\) or "([^"]+)"', f.read()).group(1)
    model = setting("SB01_LOCAL_MODEL") or default
    try:
        with urllib.request.urlopen(url + "/api/tags", timeout=5) as resp:
            have = [entry.get("name", "") for entry in json.loads(resp.read()).get("models", [])]
    except Exception as exc:
        say("FIX", f"Ollama does not answer at {url} ({getattr(exc, 'reason', exc)}), so Yotie could not reply",
            "start it:  ollama serve   (or install it from ollama.com)")
        return
    if model in have or model + ":latest" in have:
        say("ok", f"Ollama is running and has the model {model}")
    else:
        say("FIX", f"Ollama is running but does not have the model {model}", f"fetch it once, with internet:  ollama pull {model}")


def check_claude():
    if local_llm():
        return check_local_model()
    print("2. Internet and Claude")
    if not setting("ANTHROPIC_API_KEY"):
        say("note", "not tried: there is no API key")
        return
    import anthropic
    with open(os.path.join(ROOT, "scripts", "sb01_conversation.py"), encoding="utf-8") as f:
        model = re.search(r'model="([^"]+)"', f.read()).group(1)      # the model the conversation asks
    started = time.monotonic()
    try:
        client = anthropic.Anthropic(api_key=setting("ANTHROPIC_API_KEY"), timeout=CLAUDE_SECONDS, max_retries=0)
        client.messages.create(model=model, max_tokens=5, messages=[{"role": "user", "content": "Say hi."}])
    except anthropic.AuthenticationError:
        say("FIX", "Claude refused the API key", "check ANTHROPIC_API_KEY in the env file: no quotes, no spaces, the whole key")
    except anthropic.APIConnectionError as exc:
        say("FIX", f"Claude could not be reached ({type(exc).__name__})",
            "this computer has no working internet: check the WiFi, or use a phone hotspot")
    except anthropic.APIStatusError as exc:
        say("FIX", f"Claude answered with an error ({exc.status_code}: {str(exc)[:120]})")
    else:
        took = time.monotonic() - started
        say("ok" if took < 5 else "note", f"Claude ({model}) answered in {took:.1f} s" + ("" if took < 5 else ": the internet is slow here"))


def check_cable(interface: str):
    print("3. Cable to the robot")
    try:
        shown = subprocess.run(["ip", "-4", "-o", "addr", "show", interface], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        say("note", f"could not look at the network interfaces ({exc})")
        return False
    if shown.returncode != 0:
        say("FIX", f"this computer has no network interface named {interface}",
            "run `ip -4 addr` to see the names, and give the right one to the scripts")
        return False
    address = re.search(r"inet (\S+?)/", shown.stdout)
    if not address or not address.group(1).startswith(ROBOT_SUBNET):
        say("FIX", f"{interface} has {'the address ' + address.group(1) if address else 'no address'}, not one starting {ROBOT_SUBNET}",
            "plug the robot's Ethernet cable into this computer; the wired connection needs the manual address 192.168.123.222")
        return False
    say("ok", f"{interface} is up with the address {address.group(1)}")
    answered = subprocess.run(["ping", "-c", "1", "-W", "2", ROBOT_ADDRESS], capture_output=True).returncode == 0
    say("ok" if answered else "FIX", f"the robot {'answers' if answered else 'does not answer'} at {ROBOT_ADDRESS}",
        "" if answered else "is the robot switched on and fully started, and the cable in at both ends?")
    return answered


def check_voice():
    print("4. Voice")
    if (setting("SB01_VOICE").lower() or "edge") != "chatterbox":
        say("note", "Microsoft Edge voice (needs the internet for every reply); SB01_VOICE=chatterbox was not asked for")
        return
    import inspect
    from teleop import voice_chatterbox as vc
    try:
        from chatterbox.tts_turbo import ChatterboxTurboTTS
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    except ImportError as exc:
        say("FIX", f"Chatterbox is not installed in this Python ({exc}), so the program would fall back to the Edge voice",
            f"is the right environment active? Otherwise: {vc.INSTALL_HINT}")
        return
    if "nano" not in inspect.signature(ChatterboxTurboTTS.from_pretrained).parameters:
        say("FIX", "the installed Chatterbox has no Nano voice (it is the PyPI release), so English would fall back to the Edge voice",
            vc.INSTALL_HINT)
        return
    if "t3_model" not in inspect.signature(ChatterboxMultilingualTTS.from_pretrained).parameters:
        say("FIX", "the installed Chatterbox is not the version the speech framework was written for", vc.INSTALL_HINT)
        return
    say("ok", "Chatterbox is installed, with the Nano and Multilingual voices")
    try:
        engines = vc.gpu_engines()
        device, why = vc.choose_device(setting("SB01_CHATTERBOX_DEVICE"), engines)
    except vc.VoiceUnavailable as exc:
        say("FIX", f"{exc}, so the program would fall back to the Edge voice")
        return
    if device.startswith("cuda"):
        say("ok", f"the {' and '.join(engines) or 'whole'} voice will run on the graphics card ({why})")
        if engines == ("nano",):
            say("note", "only English is fast: Spanish, Chinese and the other languages are made on the processor and take much longer")
    elif setting("SB01_CHATTERBOX_DEVICE"):
        say("FIX", f"the voice will run on the processor, where replies are slow: {why}",
            "close other programs using the graphics card (nvidia-smi lists them)")
    else:
        say("note", "the voice will run on the processor, where replies are slow",
            "for the graphics card: SB01_CHATTERBOX_DEVICE=cuda SB01_CHATTERBOX_GPU_ENGINES=nano")
    try:
        tone = vc.chosen_tone("warm")
        say("ok", f"tone: {tone or 'plain'}")
    except vc.VoiceUnavailable as exc:
        say("FIX", str(exc))


def check_hearing():
    print("5. Hearing")
    from teleop import stt_whisper
    source = stt_whisper.chosen_source()
    if source == "g1-asr":
        say("ok", "the robot's own speech recognition (English and Chinese)")
        return
    try:
        import faster_whisper, silero_vad      # noqa: F401
    except ImportError as exc:
        say("FIX", f"Whisper cannot run ({exc}); the program would fall back to the robot's own recognizer",
            stt_whisper.INSTALL_HINT)
        return
    say("ok", f"{stt_whisper.describe(stt_whisper.load_config())}, from {source}")


def check_gesture_server():
    print("6. Gesture server")
    url = setting("SB01_GESTURE_URL")
    if not url:
        say("note", "arm gestures are off: SB01_GESTURE_URL is not set")
        return False
    try:
        urllib.request.urlopen(url, timeout=5).close()
    except urllib.error.HTTPError:
        pass                                    # it answered: it is running
    except Exception as exc:
        say("FIX", f"nothing answers at {url} ({getattr(exc, 'reason', exc)}), so the arms would not move",
            "start it in another terminal and wait for its 'ready' line:  "
            "~/RoboGesture/.venv/bin/python -u scripts/gesture_server.py")
        return False
    say("ok", f"the gesture server answers at {url}")
    return True


def check_robot(interface: str):
    print("7. Robot")
    try:
        from unitree_sdk2py.core.channel import ChannelFactoryInitialize
        from teleop.gesture_client import FSM_ALLOWED, GestureClient, GestureFault
    except ImportError as exc:
        say("FIX", f"the Unitree SDK is not installed in this Python ({exc})", "is the right environment active?")
        return
    ChannelFactoryInitialize(0, interface)
    client = GestureClient("http://127.0.0.1:9")     # only its state checks are used; nothing is sent
    try:
        deadline = time.monotonic() + 4.0
        while client._state is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if client._state is None:
            say("FIX", "no state messages are arriving from the robot (rt/lowstate)",
                f"is the robot fully started, and is {interface} the interface the cable is on?")
            return
        say("ok", "the robot is sending its state")
        try:
            client._require_supported_state()
        except GestureFault as fault:
            say("FIX", f"the arms would NOT move: {fault}",
                f"put the robot in walk mode with the remote (it reports FSM {FSM_ALLOWED[0]} there), standing on its own")
        else:
            say("ok", f"the robot is in walk mode (FSM {client._fsm_id()}): arm gestures will run")
    finally:
        client.close()


def main():
    parser = argparse.ArgumentParser(description="Is everything ready for Yotie to run?")
    parser.add_argument("interface", nargs="?", default="enp2s0")
    parser.add_argument("--no-robot", action="store_true", help="no robot attached: skip the cable and robot checks")
    args = parser.parse_args()

    in_file = env_file()
    checks = [lambda: check_settings(in_file), check_claude]
    if not args.no_robot:
        checks.append(lambda: check_cable(args.interface))
    checks += [check_voice, check_hearing, check_gesture_server]
    if not args.no_robot:
        checks.append(lambda: check_robot(args.interface))
    for check in checks:
        try:
            check()
        except Exception as exc:                # a check that breaks must never look like a pass
            say("note", f"this could not be checked ({type(exc).__name__}: {str(exc)[:160]})")

    print()
    if to_fix:
        print(f"NOT READY: {len(to_fix)} thing(s) to fix, marked [FIX] above.")
        return 1
    print("READY.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
