"""Vercel Serverless: POST /api/chat -> DeepSeek API 代理（Key不暴露前端）"""
import json
import urllib.request
from http.server import BaseHTTPRequestHandler

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_KEY = "sk-63d4e005ecb646b08538368c5172ed82"


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
        except:
            self._respond(400, {"error": "Invalid JSON"})
            return

        messages = data.get("messages", [])
        max_tokens = data.get("max_tokens", 4500)
        temperature = data.get("temperature", 0.7)

        if not messages:
            self._respond(400, {"error": "messages required"})
            return

        payload = json.dumps({
            "model": "deepseek-chat",
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature
        }, ensure_ascii=False).encode("utf-8")

        req = urllib.request.Request(
            DEEPSEEK_URL, data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {DEEPSEEK_KEY}"
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=55) as resp:
                # 分块读取避免IncompleteRead
                chunks = []
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    chunks.append(chunk)
                body = b"".join(chunks).decode("utf-8")
                result = json.loads(body)
                self._respond(200, result)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8") if e.fp else ""
            self._respond(e.code, {"error": f"DeepSeek error: {e.code}", "detail": err_body})
        except Exception as e:
            self._respond(500, {"error": str(e)})

    def do_OPTIONS(self):
        self._respond(200, {})

    def _respond(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
