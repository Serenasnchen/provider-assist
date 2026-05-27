"""Vercel Serverless: POST /api/export_doc -> 创建企微文档并写入内容"""
import json
import urllib.request
from http.server import BaseHTTPRequestHandler

MCP_URL = "https://qyapi.weixin.qq.com/mcp/robot-doc?apikey=S0RW0Ke7TfR0_NcWgTXq2Ht_BColuWjRzRVM9LMO3jHoIdKwI3gEPiNPnNxgkiPqhNXtAtM1_86okTOj8R5R8Q"


def call_mcp(tool_name, arguments):
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments}
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        MCP_URL, data=payload,
        headers={"Content-Type": "application/json; charset=utf-8", "Accept": "application/json, text/event-stream"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        ct = resp.headers.get("Content-Type", "")
        body = resp.read().decode("utf-8")
        if "text/event-stream" in ct:
            result = None
            for line in body.split("\n"):
                line = line.strip()
                if line.startswith("data: "):
                    try:
                        result = json.loads(line[6:])
                    except:
                        pass
            return result
        else:
            return json.loads(body)


def extract(mcp_resp):
    if not mcp_resp:
        return None
    result = mcp_resp.get("result", mcp_resp)
    if isinstance(result, dict):
        content = result.get("content", [])
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    try:
                        return json.loads(item["text"])
                    except:
                        return item.get("text")
        return result
    return result


def markdown_to_doc_content(markdown_text):
    """将Markdown文本转为企微文档API可接受的内容格式"""
    # 企微文档 insert_content_to_doc 接受 Markdown 格式的 content
    # 清理一些格式问题
    content = markdown_text.strip()
    return content


def create_wecom_doc(title, content):
    """创建企微文档并写入内容"""
    # 1. 创建文档 (doc_type=1 为普通文档)
    r = extract(call_mcp("create_doc", {"doc_type": 1, "doc_name": title}))
    if not r:
        return {"success": False, "error": "创建文档失败"}

    if isinstance(r, dict) and r.get("errcode", 0) != 0:
        return {"success": False, "error": f"创建文档失败: {r.get('errmsg', '')}"}

    docid = r.get("docid") if isinstance(r, dict) else None
    doc_url = r.get("url") if isinstance(r, dict) else None

    if not docid:
        return {"success": False, "error": "未获取到文档ID", "detail": str(r)}

    # 2. 写入内容
    try:
        write_result = call_mcp("insert_content_to_doc", {
            "docid": docid,
            "content": content
        })
    except Exception as e:
        # 即使写入失败，文档已创建，返回链接
        pass

    return {
        "success": True,
        "docid": docid,
        "url": doc_url,
        "title": title
    }


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
        except:
            self._respond(400, {"error": "Invalid JSON", "success": False})
            return

        title = data.get("title", "服务商助手文档")
        content = data.get("content", "")

        if not content:
            self._respond(400, {"error": "content is required", "success": False})
            return

        result = create_wecom_doc(title, content)
        self._respond(200 if result.get("success") else 500, result)

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
