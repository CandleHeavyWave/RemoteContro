import socket
import json
import threading
import os
import sys
from typing import Dict, Any, Optional

import cv2
import numpy as np
import time
import base64
from PIL import ImageGrab


class Client:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.socket.connect((self.host, self.port))
            self.id: Optional[str] = None
            threading.Thread(target=self.receive_message, daemon=True).start()
            self.init_control()
            while True:
                pass
        except socket.error as e:
            print(f"Connection error: {e}")
            sys.exit(1)

    def __del__(self) -> None:
        self.close()

    def init_control(self) -> None:
        init_message = {"mode": "init", "client_mode": "controlled"}
        self.send_message(init_message)

    def send_message(self, message: Dict[str, Any]) -> None:
        try:
            print("send：", message)
            self.socket.send(json.dumps(message).encode('utf-8'))
        except (socket.error, json.JSONDecodeError) as e:
            print(f"Error sending message: {e}")
            self.close()

    def receive_message(self) -> None:
        buffer = ""
        while True:
            try:
                data = self.socket.recv(1048576).decode('utf-8')

                if not data:
                    break
                buffer += data
                while True:
                    try:
                        msg, idx = json.JSONDecoder().raw_decode(buffer)
                        print("receive_message：", msg)
                        self.handle_message(msg)
                        buffer = buffer[idx:].lstrip()
                    except ValueError:
                        break
            except (socket.error, UnicodeDecodeError) as e:
                print(f"Error receiving message: {e}")
                self.close()
                break

    def directory(self, data: Dict[str, Any]) -> None:
        try:
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
        except (KeyError, OSError) as e:
            print(f"Directory error: {e}")

    def download(self, file_path: str, controll_client_id: str, output: str) -> None:
        try:
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(1048576)  # 每次读取4KB
                    if not chunk:
                        break
                    # 将二进制数据转换为十六进制字符串发送
                    chunk_data = chunk.hex()
                    response = {
                        "mode": "return",
                        "controll_client_id": controll_client_id,
                        "data": {
                            "mode": "download",
                            "data": chunk_data,
                            "file": file_path,
                            "output": output,
                            "chunk": True  # 添加一个标记，表示这是分块传输
                        }
                    }
                    self.send_message(response)
            # 发送完成标志
            response = {
                "mode": "return",
                "controll_client_id": controll_client_id,
                "data": {
                    "mode": "download",
                    "data": "",
                    "file": file_path,
                    "output": output,
                    "chunk": False  # 标记传输完成
                }
            }
            self.send_message(response)
        except (IOError, KeyError) as e:
            print(f"Download error: {e}")

    def init_downlaod(self, data):
        file_path = data["param"]["file"]
        controll_client_id = data["param"]["controll_client_id"]
        output = data["param"].get("output", "")

        self.download(file_path, controll_client_id, output)

    def remote_control(self, data):
        try:
            fps = data["data"].get("fps", 25)
            definition = data["data"].get("definition", 720)
            quality = data["data"].get("quality", 70)
            target_ratio = 16 / 9  # 固定16:9比例

            # 分辨率映射（保持16:9比例）
            resolutions = {
                360: (640, 360),  # 16:9
                480: (854, 480),  # 16:9
                720: (1280, 720),  # 16:9
                1080: (1920, 1080),  # 16:9
                "2k": (2560, 1440),  # 16:9
                "4k": (3840, 2160)  # 16:9
            }
            target_size = resolutions.get(definition, (1280, 720))

            while True:
                # 捕获屏幕
                start_time = time.time()
                img = ImageGrab.grab()
                img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

                # 获取原始尺寸和比例
                original_height, original_width = img.shape[:2]
                original_ratio = original_width / original_height

                # 保持固定比例处理
                if original_ratio > target_ratio:
                    # 宽屏，上下加黑边
                    new_width = original_width
                    new_height = int(new_width / target_ratio)
                    delta_height = new_height - original_height
                    top, bottom = delta_height // 2, delta_height - (delta_height // 2)
                    img = cv2.copyMakeBorder(img, top, bottom, 0, 0, cv2.BORDER_CONSTANT, value=[0, 0, 0])
                elif original_ratio < target_ratio:
                    # 窄屏，左右加黑边
                    new_height = original_height
                    new_width = int(new_height * target_ratio)
                    delta_width = new_width - original_width
                    left, right = delta_width // 2, delta_width - (delta_width // 2)
                    img = cv2.copyMakeBorder(img, 0, 0, left, right, cv2.BORDER_CONSTANT, value=[0, 0, 0])

                # 调整到目标大小
                img = cv2.resize(img, target_size)

                # 压缩图像
                encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
                _, buffer = cv2.imencode('.jpg', img, encode_param)

                jpg_as_text = base64.b64encode(buffer).decode('utf-8')

                response = {
                    "mode": "return",
                    "controll_client_id": data["controll_client_id"],
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

                # 精确控制帧率
                process_time = time.time() - start_time
                sleep_time = max(0, (1 / fps) - process_time)
                time.sleep(sleep_time)

        except Exception as e:
            print(f"Remote control error: {e}")
            self.close()

    def init_remote_control(self, data):
        threading.Thread(target=self.remote_control, args=(data,), daemon=True).start()

    def handle_message(self, data: Dict[str, Any]) -> None:
        try:
            if data["mode"] == "init":
                self.id = data["id"]
            elif data["mode"] == "directory":
                self.directory(data)
            elif data["mode"] == "init_download":
                self.init_downlaod(data)
            elif data["mode"] == "init_remote_control":
                self.init_remote_control(data)
        except KeyError as e:
            print(f"Invalid message format: {e}")

    def close(self) -> None:
        try:
            if hasattr(self, 'socket') and self.socket:
                self.send_message({"mode": "close"})
                self.socket.close()
        except Exception as e:
            print(f"Error closing client: {e}")
        finally:
            sys.exit()


if __name__ == "__main__":
    client = Client('192.168.1.120', 43234)