"""啟動程式：python -m app [--no-browser]"""
import socket
import sys
import threading
import time
import webbrowser

import uvicorn

from . import config

URL = f"http://{config.HOST}:{config.PORT}"


def port_open() -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((config.HOST, config.PORT)) == 0


def open_browser_when_ready() -> None:
    for _ in range(60):
        if port_open():
            webbrowser.open(URL)
            return
        time.sleep(0.5)


def main() -> None:
    no_browser = "--no-browser" in sys.argv
    if port_open():
        print(f"程式已經在執行中：{URL}")
        if not no_browser:
            webbrowser.open(URL)
        return
    if not no_browser:
        threading.Thread(target=open_browser_when_ready, daemon=True).start()
    print(f"單字複習系統執行中：{URL}")
    print("關閉這個視窗就會結束程式。")
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, log_level="warning")


if __name__ == "__main__":
    main()
