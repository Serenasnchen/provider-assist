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


def format_for_wecom_doc(title, raw_content):
    """将原始文本格式化为企微文档友好的Markdown"""
    import re
    lines = []
    # 文档标题
    lines.append(f"# {title}")
    lines.append("")
    lines.append("---")
    lines.append("")

    question_num = 0  # 自动给问题编号

    # 处理原始内容
    for line in raw_content.split("\n"):
        stripped = line.strip()
        # 标准化标题级别
        if stripped.startswith("## ") or stripped.startswith("### "):
            lines.append("")
            lines.append(stripped)
            lines.append("")
            question_num = 0  # 每个新section重置编号
        elif stripped.startswith("> "):
            lines.append(stripped)
        elif stripped.startswith("- ") or stripped.startswith("* "):
            lines.append(stripped)
        elif stripped and stripped[0].isdigit() and ". " in stripped[:5]:
            # 已经有编号的问题，保留
            lines.append(stripped)
        elif re.match(r'^[\[【]', stripped):
            # 以维度标签开头但没有编号的问题行，自动加编号
            question_num += 1
            lines.append(f"{question_num}. {stripped}")
        elif stripped == "---":
            lines.append("")
            lines.append("---")
            lines.append("")
        elif stripped:
            lines.append(stripped)
        else:
            lines.append("")

    # 添加页脚
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*由「服务商助手」AI 生成*")

    return "\n".join(lines)


def create_wecom_doc(title, content):
    """创建企微文档并写入内容"""
    # 0. 格式化内容
    formatted_content = format_for_wecom_doc(title, content)

    # 1. 创建文档 (doc_type=3 为企微文档)
    r = extract(call_mcp("create_doc", {"doc_type": 3, "doc_name": title}))
    if not r:
        return {"success": False, "error": "创建文档失败: 无响应"}

    if isinstance(r, dict) and r.get("errcode", 0) != 0:
        return {"success": False, "error": f"创建文档失败: {r.get('errmsg', '')}"}

    docid = r.get("docid") if isinstance(r, dict) else None
    doc_url = r.get("url") if isinstance(r, dict) else None

    if not docid:
        return {"success": False, "error": "未获取到文档ID", "detail": str(r)}

    # 2. 用 edit_doc_content 写入格式化的 Markdown 内容
    try:
        write_result = call_mcp("edit_doc_content", {
            "docid": docid,
            "content": formatted_content,
            "content_type": 1
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
