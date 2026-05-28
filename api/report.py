"""Vercel Serverless: POST /api/report -> 上报数据到平台管理智能表格"""
import json
import urllib.request
from http.server import BaseHTTPRequestHandler

MCP_URL = "https://qyapi.weixin.qq.com/mcp/robot-doc?apikey=S0RW0Ke7TfR0_NcWgTXq2Ht_BColuWjRzRVM9LMO3jHoIdKwI3gEPiNPnNxgkiPqhNXtAtM1_86okTOj8R5R8Q"

# 平台管理表的 docid 和 sheet_id
ADMIN_DOC_ID = "dc_bZyjyIOKIjKHoMi-VenuLgp7VE_ewIkFQAkKchu23cPN2eGaM6Rjs3dpnZSFPg93IEeXW8ucr4Ee7NBXv7SvQ"
ADMIN_DOC_URL = "https://doc.weixin.qq.com/smartsheet/s3_AH4An3gNAAQCNxid8qo3aTDSUBpKd_a?scode=AJEAIQdfAAoAeNT8OKAH4An3gNAAQ"
SHEET_CLIENTS = "q979lj"   # 客户汇总表
SHEET_RECORDS = "1abkq2"   # 沟通记录表


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


def create_admin_table():
    """首次创建平台管理智能表格（包含2个子表）"""
    schema = {
        "doc_name": "服务商助手-平台管理",
        "sheets": [
            {
                "sheet_name": "客户汇总",
                "fields": [
                    {"field_title": "服务商", "field_type": "FIELD_TYPE_TEXT"},
                    {"field_title": "客户名称", "field_type": "FIELD_TYPE_TEXT"},
                    {"field_title": "客户行业", "field_type": "FIELD_TYPE_TEXT"},
                    {"field_title": "业务描述", "field_type": "FIELD_TYPE_TEXT"},
                    {"field_title": "痛点", "field_type": "FIELD_TYPE_TEXT"},
                    {"field_title": "当前状态", "field_type": "FIELD_TYPE_SINGLE_SELECT"},
                    {"field_title": "提问清单链接", "field_type": "FIELD_TYPE_URL"},
                    {"field_title": "需求报告链接", "field_type": "FIELD_TYPE_URL"},
                    {"field_title": "Demo链接", "field_type": "FIELD_TYPE_URL"},
                    {"field_title": "创建时间", "field_type": "FIELD_TYPE_DATE_TIME"},
                    {"field_title": "最后更新", "field_type": "FIELD_TYPE_DATE_TIME"}
                ]
            },
            {
                "sheet_name": "沟通记录",
                "fields": [
                    {"field_title": "服务商", "field_type": "FIELD_TYPE_TEXT"},
                    {"field_title": "客户名称", "field_type": "FIELD_TYPE_TEXT"},
                    {"field_title": "客户行业", "field_type": "FIELD_TYPE_TEXT"},
                    {"field_title": "沟通内容", "field_type": "FIELD_TYPE_TEXT"},
                    {"field_title": "内容长度", "field_type": "FIELD_TYPE_NUMBER"},
                    {"field_title": "上传时间", "field_type": "FIELD_TYPE_DATE_TIME"}
                ]
            }
        ]
    }

    # 创建智能表格
    r = extract(call_mcp("create_doc", {"doc_type": 10, "doc_name": schema["doc_name"]}))
    if not r or (isinstance(r, dict) and r.get("errcode", 0) != 0):
        return {"success": False, "error": "创建表格失败", "detail": str(r)}

    docid = r.get("docid", "")
    url = r.get("url", "")

    # 获取默认sheet并添加字段
    # 注意：新建的智能表格默认有一个空sheet，我们需要配置它
    # 先添加第一个sheet的字段
    for sheet_def in schema["sheets"]:
        for field in sheet_def["fields"]:
            try:
                call_mcp("add_field", {
                    "docid": docid,
                    "sheet_name": sheet_def["sheet_name"],
                    "field_title": field["field_title"],
                    "field_type": field["field_type"]
                })
            except:
                pass

    return {
        "success": True,
        "docid": docid,
        "url": url
    }


def text_val(s):
    """TEXT字段需要数组格式"""
    return [{"type": "text", "text": str(s)}] if s else [{"type": "text", "text": ""}]


def report_client(data):
    """上报客户数据到汇总表"""
    provider = data.get("provider_name", "")
    client = data.get("client_name", "")
    values = {
        "服务商": text_val(provider),
        "客户名称": text_val(client),
        "客户行业": text_val(data.get("industry", "")),
        "业务描述": text_val(data.get("business_desc", "")[:500]),
        "痛点": text_val(data.get("pain_points", "")[:500]),
        "当前状态": data.get("status", "")
    }
    # URL字段
    if data.get("step1_doc_url"):
        values["提问清单链接"] = [{"link": data["step1_doc_url"], "text": "提问清单"}]
    if data.get("report_doc_url"):
        values["需求报告链接"] = [{"link": data["report_doc_url"], "text": "需求报告"}]
    if data.get("demo_url"):
        values["Demo链接"] = [{"link": data["demo_url"], "text": "Demo"}]
    if data.get("transcript_doc_url"):
        values["沟通记录原始材料"] = [{"link": data["transcript_doc_url"], "text": "沟通记录"}]

    try:
        r = extract(call_mcp("smartsheet_add_records", {
            "docid": ADMIN_DOC_ID,
            "sheet_id": SHEET_CLIENTS,
            "records": [{"values": values}]
        }))
        return {"success": True, "result": str(r)[:200]}
    except Exception as e:
        return {"success": False, "error": str(e)}


def report_transcript(data):
    """上报沟通记录：
    - 粘贴文字 → 创建企微文档存全文
    - 上传Word → 直接上传到企微文件系统
    两种情况都把链接写入沟通记录表 + 客户汇总表
    """
    transcript = data.get("transcript", "")
    file_base64 = data.get("file_base64", "")  # 如果服务商上传了文件
    file_name = data.get("file_name", "")
    provider_name = data.get("provider_name", "")
    client_name = data.get("client_name", "")
    industry = data.get("industry", "")

    doc_url = ""

    if file_base64 and file_name:
        # 服务商直接上传了Word文件 → 上传到企微
        try:
            r = extract(call_mcp("upload_doc_file", {
                "file_name": file_name,
                "file_base64_content": file_base64
            }))
            if r and isinstance(r, dict):
                doc_url = r.get("url", "") or r.get("file_url", "")
        except:
            pass
    elif transcript:
        # 服务商粘贴文字 → 创建企微文档（相当于Word）
        try:
            doc_title = f"{client_name} - 沟通记录"
            r = extract(call_mcp("create_doc", {"doc_type": 3, "doc_name": doc_title}))
            if r and isinstance(r, dict) and r.get("errcode", 0) == 0:
                docid = r.get("docid", "")
                doc_url = r.get("url", "")
                content = f"# {client_name} 沟通记录\n\n"
                content += f"- 服务商：{provider_name}\n"
                content += f"- 行业：{industry}\n\n---\n\n"
                content += transcript
                call_mcp("edit_doc_content", {"docid": docid, "content": content, "content_type": 1})
        except:
            pass

    # 写入沟通记录sheet
    values = {
        "服务商": text_val(provider_name),
        "客户名称": text_val(client_name),
        "客户行业": text_val(industry),
        "沟通内容": text_val(transcript[:500] + ("..." if len(transcript) > 500 else "")),
        "内容长度": len(transcript) or len(file_base64)
    }
    if doc_url:
        values["文档链接"] = [{"link": doc_url, "text": "查看文档"}]

    try:
        r = extract(call_mcp("smartsheet_add_records", {
            "docid": ADMIN_DOC_ID,
            "sheet_id": SHEET_RECORDS,
            "records": [{"values": values}]
        }))
        return {"success": True, "doc_url": doc_url}
    except Exception as e:
        return {"success": False, "error": str(e), "doc_url": doc_url}


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
        except:
            self._respond(400, {"error": "Invalid JSON"})
            return

        action = data.get("action", "report_client")

        if action == "init":
            result = create_admin_table()
        elif action == "report_client":
            result = report_client(data)
        elif action == "report_transcript":
            result = report_transcript(data)
        else:
            result = {"error": "Unknown action"}

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
