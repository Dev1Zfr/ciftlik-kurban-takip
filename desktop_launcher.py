import threading
import webbrowser

from waitress import serve

from app import app


def open_browser():
    webbrowser.open("http://127.0.0.1:5000")


if __name__ == "__main__":
    print("Çiftlik Takip Sistemi http://127.0.0.1:5000 adresinde çalışıyor.")
    print("Uygulamayı kapatmak için bu pencereyi kapatın veya Ctrl+C tuşlarına basın.")
    threading.Timer(1.5, open_browser).start()
    serve(app, host="127.0.0.1", port=5000, threads=4)
