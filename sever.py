import socket
import json
import threading
import logging
import time
import random
import string
from typing import Dict, Any, List, Optional


class Server:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.clients: List[Dict[str, Any]] = []
        self.controll_clients: List[Dict[str, Any]] = []
        self.controlled_clients: List[Dict[str, Any]] = []
        self.running = True
        self.lock = threading.Lock()

        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)

    def start(self) -> None:
        try:
            self.socket.bind((self.host, self.port))
            self.socket.listen()
            self.logger.info(f"Server started on {self.host}:{self.port}")

            threading.Thread(target=self.accept_clients, daemon=True).start()

            while self.running:
                time.sleep(0.1)
        except Exception as e:
            self.logger.error(f"Server error: {e}")
            self.stop()

    def accept_clients(self) -> None:
        while self.running:
            try:
                client_socket, addr = self.socket.accept()
                client_id = self._create_task_id()

                with self.lock:
                    self.clients.append({
                        "id": client_id,
                        "socket": client_socket,
                        "ip": addr[0],
                        "port": addr[1],
                        "time": time.strftime('%Y-%m-%d %H:%M:%S')
                    })

                threading.Thread(
                    target=self.handle_client,
                    args=(client_socket, client_id),
                    daemon=True
                ).start()
            except socket.error as e:
                if self.running:
                    self.logger.error(f"Error accepting client: {e}")

    def _create_task_id(self) -> str:
        return 'id_' + ''.join(random.choices(string.ascii_letters + string.digits, k=10))

    def handle_client(self, client_socket: socket.socket, client_id: str) -> None:
        buffer = ""
        while self.running:
            try:
                data = client_socket.recv(1048576).decode('utf-8')
                if not data:
                    break

                buffer += data
                while True:
                    try:
                        msg, idx = json.JSONDecoder().raw_decode(buffer)
                        print("receive_message：", msg)
                        self.handle_client_message(client_id, msg)
                        buffer = buffer[idx:].lstrip()
                    except ValueError:
                        break
            except (socket.error, UnicodeDecodeError) as e:
                self.logger.error(f"Client {client_id} error: {e}")
                break

        self.close_client(client_id)

    def remove_client_from_list(self, client_list: List[Dict[str, Any]], client_id: str) -> None:
        with self.lock:
            for i in range(len(client_list) - 1, -1, -1):
                if client_list[i]["id"] == client_id:
                    del client_list[i]
                    break

    def close_client(self, client_id: str) -> None:
        client = self.get_client(client_id)
        if client:
            try:
                if "socket" in client:
                    client["socket"].close()
            except socket.error as e:
                self.logger.error(f"Error closing client socket: {e}")

            self.remove_client_from_list(self.clients, client_id)
            self.remove_client_from_list(self.controlled_clients, client_id)
            self.remove_client_from_list(self.controll_clients, client_id)
            self.logger.info(f"Client {client_id} disconnected")

    def init_client(self, client_id: str, data: Dict[str, Any]) -> None:
        client_info = self.get_client(client_id)
        if not client_info:
            return

        self.send_message(client_info["socket"], {"mode": "init", "id": client_id})

        with self.lock:
            if data["client_mode"] == "control":
                self.controll_clients.append(client_info)
                self.logger.info(f"New control client: {client_info['ip']}:{client_info['port']} ({client_id})")
            elif data["client_mode"] == "controlled":
                self.controlled_clients.append(client_info)
                self.logger.info(f"New controlled client: {client_info['ip']}:{client_info['port']} ({client_id})")

    def clients_list(self, client_id: str) -> None:
        client = self.get_client(client_id)
        if not client:
            return

        with self.lock:
            controlled_clients = [
                {k: v for k, v in c.items() if k != 'socket'}
                for c in self.controlled_clients
            ]

        self.send_message(client["socket"], {
            "mode": "client_list",
            "data": controlled_clients
        })

    def directory(self, data: Dict[str, Any], controll_client_id: str) -> None:
        target_client = self.get_client(data["param"]["client_id"])
        if target_client:
            self.send_message(target_client["socket"], {
                "mode": "directory",
                "param": {
                    "controll_client_id": controll_client_id,
                    "root": data["param"]["root"]
                }
            })

    def init_download(self, data: Dict[str, Any], controll_client_id: str) -> None:
        target_client = self.get_client(data["param"]["client_id"])
        if target_client:
            self.send_message(target_client["socket"], {
                "mode": "init_download",
                "param": {
                    "controll_client_id": controll_client_id,
                    "file": data["param"]["file"],
                    "output": data["param"].get("output", "")
                }
            })

    def download(self, data: Dict[str, Any], controll_client_id: str) -> None:
        target_client = self.get_client(data["param"]["client_id"])
        if target_client:

            while True:

                if data["data"]["chunk"]:

                    message = {
                        "mode": "download",
                        "param": {
                            "controll_client_id": controll_client_id,
                            "file": data["param"]["file"],
                            "output": data["param"].get("output", ""),
                            "data": data["data"]["data"],
                            "chunk": True
                        }
                    }
                    self.send_message(target_client["socket"], message)
                else:
                    message = {
                        "mode": "download",
                        "param": {
                            "controll_client_id": controll_client_id,
                            "file": data["param"]["file"],
                            "output": data["param"].get("output", ""),
                            "data": "",
                            "chunk": False
                        }
                    }
                    self.send_message(target_client["socket"], message)
                    break

    def return_result(self, data: Dict[str, Any]) -> None:
        target_client = self.get_client(data["controll_client_id"])
        if target_client:
            self.send_message(target_client["socket"], data)

    def remote_control(self, data):
        try:
            target_client = self.get_client(data["client_id"])
            if target_client:
                self.send_message(target_client["socket"], {
                    "mode": "init_remote_control",
                    "controll_client_id": data["controll_client_id"],
                    "data": data["data"]
                })
        except Exception as e:
            self.logger.error(f"Remote control error: {e}")

    def handle_client_message(self, client_id: str, data: Dict[str, Any]) -> None:

            if data["mode"] == "init":
                self.init_client(client_id, data)
            elif data["mode"] == "close":
                self.close_client(client_id)
            elif data["mode"] == "clients_list":
                self.clients_list(client_id)
            elif data["mode"] == "directory":
                self.directory(data, client_id)
            elif data["mode"] == "return":
                self.return_result(data)
            elif data["mode"] == "init_download":
                self.init_download(data, client_id)
            elif data["mode"] == "init_remote_control":
                self.remote_control(data)

    def send_message(self, client_socket: socket.socket, message: Dict[str, Any]) -> None:
        print("send：", message)
        try:
            client_socket.send(json.dumps(message).encode('utf-8'))
        except (socket.error, json.JSONDecodeError) as e:
            self.logger.error(f"Error sending message: {e}")

    def get_client(self, client_id: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            for client in self.clients:
                if client["id"] == client_id:
                    return client
        return None

    def stop(self) -> None:
        self.running = False
        try:
            with self.lock:
                for client in self.clients:
                    try:
                        client["socket"].close()
                    except socket.error:
                        pass
                self.socket.close()
        except Exception as e:
            self.logger.error(f"Error during server shutdown: {e}")
        finally:
            self.logger.info("Server stopped")


if __name__ == "__main__":
    server = Server('0.0.0.0', 43234)
    try:
        server.start()
    except KeyboardInterrupt:
        server.stop()