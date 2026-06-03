"""Vercel Serverless: POST /api/company_search -> 公司信息搜索"""
import json
import os
from http.server import BaseHTTPRequestHandler


def call_deepseek(prompt):
    """调用DeepSeek API生成公司简介"""
    import urllib.request

    api_key = os.environ.get("DEEPSEEK_API_KEY", "sk-63d4e005ecb646b08538368c5172ed82")
    if not api_key:
        return "Error: DEEPSEEK_API_KEY not configured"

    system_prompt = """你是一个企业信息助手。根据公司名称和行业，生成一段公司简介。
写法要求：
- 用一段自然的话介绍这家公司：做什么的、主营业务、客户群体、大致规模
- 如果是知名公司，可以提一下特点
- 如果公司名称不够明确，就根据行业做合理推断
- 3-5句话，保持客观简洁，不要编造具体数据
- 像一个了解这个行业的人在介绍客户，不要像填表
"""

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.6,
        "max_tokens": 200
    }

    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Error calling DeepSeek: {str(e)}"


def search_company_info(company_name, industry=""):
    """搜索公司信息,返回简介"""
    prompt = f"公司名称:{company_name}\n"
    if industry:
        prompt += f"行业:{industry}\n"
    prompt += "\n请生成该公司的简介(2-3句话):"

    intro = call_deepseek(prompt)
    return {"company_intro": intro.strip()}


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
        except:
            self._respond(400, {"error": "Invalid JSON"})
            return

        company_name = data.get("company_name", "").strip()
        if not company_name:
            self._respond(400, {"error": "company_name is required"})
            return

        industry = data.get("industry", "").strip()
        result = search_company_info(company_name, industry)
        self._respond(200, result)

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
