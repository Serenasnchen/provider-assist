"""Vercel Serverless: POST /api/upload -> 解析上传的文档为纯文本"""
import json
import base64
import re
from http.server import BaseHTTPRequestHandler


def parse_docx_basic(data):
    """从docx中提取文本（docx本质是zip中的xml）"""
    import zipfile
    import io
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        xml_content = zf.read("word/document.xml").decode("utf-8")
        # 提取所有<w:t>标签中的文本
        texts = re.findall(r'<w:t[^>]*>(.*?)</w:t>', xml_content)
        # 按段落分组
        paragraphs = re.findall(r'<w:p[^>]*>(.*?)</w:p>', xml_content, re.DOTALL)
        result = []
        for para in paragraphs:
            para_texts = re.findall(r'<w:t[^>]*>(.*?)</w:t>', para)
            if para_texts:
                result.append("".join(para_texts))
        return "\n".join(result) if result else "\n".join(texts)
    except Exception as e:
        return f"[docx解析失败: {str(e)}]"


def parse_txt(data):
    """解析纯文本文件"""
    try:
        return data.decode("utf-8")
    except:
        try:
            return data.decode("gbk")
        except:
            return data.decode("utf-8", errors="ignore")


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_type = self.headers.get("Content-Type", "")
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        extracted_text = ""
        filename = ""

        if "multipart/form-data" in content_type:
            # Parse multipart form data
            boundary = content_type.split("boundary=")[1] if "boundary=" in content_type else ""
            if boundary:
                parts = body.split(("--" + boundary).encode())
                for part in parts:
                    if b"filename=" in part:
                        # Extract filename
                        header_end = part.find(b"\r\n\r\n")
                        if header_end == -1:
                            continue
                        headers_str = part[:header_end].decode("utf-8", errors="ignore")
                        fn_match = re.search(r'filename="([^"]*)"', headers_str)
                        if fn_match:
                            filename = fn_match.group(1)
                        file_data = part[header_end + 4:]
                        # Remove trailing \r\n--
                        if file_data.endswith(b"\r\n"):
                            file_data = file_data[:-2]

                        if filename.endswith(".docx"):
                            extracted_text = parse_docx_basic(file_data)
                        elif filename.endswith(".txt"):
                            extracted_text = parse_txt(file_data)
                        elif filename.endswith(".doc"):
                            extracted_text = "[.doc格式需转为.docx后上传，或直接粘贴文本内容]"
                        elif filename.endswith(".pdf"):
                            extracted_text = "[PDF解析暂不支持服务端处理，请复制PDF文本内容后粘贴]"
                        else:
                            extracted_text = parse_txt(file_data)
        else:
            # JSON body with base64 encoded file
            try:
                data = json.loads(body)
                filename = data.get("filename", "")
                file_b64 = data.get("file_data", "")
                if file_b64:
                    file_data = base64.b64decode(file_b64)
                    if filename.endswith(".docx"):
                        extracted_text = parse_docx_basic(file_data)
                    elif filename.endswith(".txt"):
                        extracted_text = parse_txt(file_data)
                    else:
                        extracted_text = parse_txt(file_data)
            except:
                self._respond(400, {"error": "Invalid request"})
                return

        if not extracted_text:
            self._respond(400, {"error": "无法解析文件内容", "filename": filename})
            return

        self._respond(200, {
            "text": extracted_text,
            "filename": filename,
            "char_count": len(extracted_text)
        })

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
