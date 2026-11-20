
import tkinter as tk
from tkinter import messagebox
import requests
import uuid
import threading
import time

API = "https://ratka66-production.up.railway.app"


class RatkaReceiver:
    def __init__(self, root):
        self.root = root
        self.root.title("РАТКА")
        self.root.geometry("400x250")
        self.root.resizable(False, False)

        self.device_id = str(uuid.uuid4())
        self.token = None
        self.running = True

        tk.Label(
            root,
            text="РАТКА",
            font=("Arial", 22, "bold")
        ).pack(pady=15)

        tk.Label(
            root,
            text="Код подключения:",
            font=("Arial", 12)
        ).pack()

        self.code_label = tk.Label(
            root,
            text="Получение кода...",
            font=("Arial", 20, "bold")
        )
        self.code_label.pack(pady=10)

        tk.Label(
            root,
            text="Введите этот код в Telegram-боте командой /pair",
            wraplength=350
        ).pack(pady=5)

        tk.Button(
            root,
            text="Отключить и закрыть",
            command=self.close
        ).pack(pady=12)

        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.register_device()

        threading.Thread(
            target=self.worker,
            daemon=True
        ).start()

    def register_device(self):
        try:
            response = requests.post(
                f"{API}/api/register",
                json={"device_id": self.device_id},
                timeout=10
            )
            response.raise_for_status()

            data = response.json()
            self.code_label.config(
                text=data.get("code", "Ошибка")
            )

        except Exception:
            self.code_label.config(text="Ошибка подключения")

    def worker(self):
        while self.running:
            try:
                if not self.token:
                    self.check_pairing()
                else:
                    self.get_messages()

            except Exception:
                pass

            time.sleep(3)

    def check_pairing(self):
        response = requests.get(
            f"{API}/api/status/{self.device_id}",
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()

            if data.get("paired"):
                self.token = data.get("token")

                if self.token:
                    self.root.after(
                        0,
                        lambda: self.code_label.config(
                            text="Подключено"
                        )
                    )

    def get_messages(self):
        response = requests.get(
            f"{API}/api/messages/{self.device_id}",
            headers={"X-Device-Token": self.token},
            timeout=10
        )

        if response.status_code != 200:
            return

        data = response.json()

        for message in data.get("messages", []):
            title = str(message.get("title", "Сообщение"))
            body = str(message.get("body", ""))

            self.root.after(
                0,
                lambda t=title, b=body: self.show_popup(t, b)
            )

    def show_popup(self, title, body):
        if not self.running:
            return

        popup = tk.Toplevel(self.root)
        popup.title(title)
        popup.geometry("400x200")
        popup.attributes("-topmost", True)

        label = tk.Label(
            popup,
            text=body,
            font=("Arial", 14),
            wraplength=350,
            padx=20,
            pady=20
        )
        label.pack(expand=True)

    def close(self):
        self.running = False

        try:
            requests.delete(
                f"{API}/api/device/{self.device_id}",
                headers={"X-Device-Token": self.token or ""},
                timeout=5
            )
        except Exception:
            pass

        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = RatkaReceiver(root)
    root.mainloop()
