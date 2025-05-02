import websocket
import requests
import json
import time
import uuid
import random
import base64
import xml.etree.ElementTree as ET
import subprocess

# DVR connection settings
DVR_IP = "192.168.68.121"
DVR_PORT = 51986
USERNAME = "admin"
PASSWORD = "chosen04"
DESIRED_CHANNEL_NUMBER = 1  # Change to desired camera

session_id = None
ws = None
channel_uuid = None
ffmpeg_process = None

def build_channel_uuid(channel_number):
    return f"{{{channel_number:08X}-0000-0000-0000-000000000000}}"

def login_and_get_session():
    url = f"http://{DVR_IP}:{DVR_PORT}/doLogin"
    headers = {
        "Content-Type": "application/xml",
        "Origin": f"http://{DVR_IP}:{DVR_PORT}",
        "Referer": f"http://{DVR_IP}:{DVR_PORT}/",
    }
    password_base64 = base64.b64encode(PASSWORD.encode('utf-8')).decode('utf-8')

    xml_payload = f"""<?xml version="1.0" encoding="utf-8"?>
<request version="1.0" systemType="NVMS-9000" clientType="WEB">
  <content>
    <userName><![CDATA[{USERNAME}]]></userName>
    <password><![CDATA[{password_base64}]]></password>
  </content>
</request>"""

    response = requests.post(url, headers=headers, data=xml_payload)
    print(f"[Login] HTTP status: {response.status_code}")
    try:
        root = ET.fromstring(response.text)
        sid = root.find(".//sessionId").text.strip("{}")
        print(f"[Login] Got sessionId: {sid}")
        return sid
    except Exception as e:
        print(f"[Login] Failed to parse sessionId: {e}")

def extract_hevc_from_message(raw_bytes):
    start_code = b'\x00\x00\x00\x01'
    index = raw_bytes.find(start_code)
    return raw_bytes[index:] if index != -1 else None

def generate_task_id():
    template = "00000000-0000-0000-0000-000000000000"
    hex_chars = "0123456789abcdef"
    result = ""
    for i in range(len(template)):
        if template[i] == "-":
            result += "-"
        else:
            result += random.choice(hex_chars)
    return "{" + result + "}"

def start_ffmpeg_stream():
    global ffmpeg_process
    ffmpeg_cmd = [
        "ffmpeg",
        "-f", "hevc",
        "-i", "pipe:0",
        "-fflags", "nobuffer",
        "-flags", "low_delay",
        "-strict", "experimental",
        "-an",  # disable audio
        "-f", "mpegts",
        "udp://127.0.0.1:12345"
    ]
    ffmpeg_process = subprocess.Popen(
        ffmpeg_cmd,
        stdin=subprocess.PIPE
    )
    print("[FFmpeg] Started streaming process")

def send_preview_open(wsapp):
    task_id = generate_task_id()
    preview_msg = {
        "url": "/device/preview/open",
        "basic": {
            "ver": "1.0",
            "time": int(time.time() * 1000),
            "id": 1,
            "nonce": random.randint(0, 0xFFFFFFFF)
        },
        "data": {
            "task_id": task_id,
            "channel_id": channel_uuid,
            "stream_index": 1,
            "audio": False
        }
    }
    wsapp.send(json.dumps(preview_msg))
    print("**********TX**********")
    print("device/preview/open:", json.dumps(preview_msg, indent=2))

def on_open2(wsapp):
    print("[Opened] WebSocket connected")
    send_preview_open(wsapp)

def on_message2(ws, message):
    global ffmpeg_process
    if isinstance(message, bytes):
        hevc_data = extract_hevc_from_message(message)
        if hevc_data and ffmpeg_process:
            print(f"[Binary Frame] Streaming {len(hevc_data)} bytes to ffplay")
            try:
                ffmpeg_process.stdin.write(hevc_data)
                ffmpeg_process.stdin.flush()
            except Exception as e:
                print("[FFmpeg] Error writing to stdin:", e)
        else:
            print("[Binary Frame] No HEVC start code found")
    else:
        try:
            msg = json.loads(message)
            print("**********RX**********")
            print("[Text Frame] JSON parsed:", json.dumps(msg, indent=2))            
        except Exception as e:
            print(f"Error parsing JSON message: {e}")

def on_error(wsapp, error):
    print("[Error]", error)

def on_close(wsapp, code, msg):
    print("[Closed]", code, msg)

if __name__ == "__main__":
    session_id = login_and_get_session()
    if not session_id:
        print("[Error] Could not login, aborting.")
        exit(1)

    channel_uuid = build_channel_uuid(DESIRED_CHANNEL_NUMBER)
    start_ffmpeg_stream()

    ws_url = f"ws://{DVR_IP}:{DVR_PORT}/requestWebsocketConnection?sessionID={session_id}"
    headers = {
        "Origin": f"http://{DVR_IP}:{DVR_PORT}",
        "Cookie": f"sessionId={session_id}",
        "Pragma": "no-cache",
        "Cache-Control": "no-cache"
    }

    ws = websocket.WebSocketApp(
        ws_url,
        header=[f"{k}: {v}" for k, v in headers.items()],
        on_open=on_open2,
        on_message=on_message2,
        on_error=on_error,
        on_close=on_close
    )

    ws.run_forever()
