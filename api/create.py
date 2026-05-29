"""Vercel Serverless Function: POST /api/create → 调用企微 MCP 创建智能表格"""
import json
import urllib.request
from http.server import BaseHTTPRequestHandler

MCP_URL = "https://qyapi.weixin.qq.com/mcp/robot-doc?apikey=S0RW0Ke7TfR0_NcWgTXq2Ht_BColuWjRzRVM9LMO3jHoIdKwI3gEPiNPnNxgkiPqhNXtAtM1_86okTOj8R5R8Q"


def call_mcp(tool_name, arguments):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool_name, "arguments": arguments}}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(MCP_URL, data=payload, headers={"Content-Type": "application/json; charset=utf-8", "Accept": "application/json, text/event-stream"})
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


def setup_sheet_fields(docid, sid, fields, records, steps, sname):
    """为单个智能表格的默认子表配置字段和数据"""
    fr = extract(call_mcp("smartsheet_get_fields", {"docid": docid, "sheet_id": sid}))
    dfid, dftype = None, "FIELD_TYPE_TEXT"
    if isinstance(fr, dict):
        fl = fr.get("fields", [])
        if fl:
            dfid = fl[0].get("field_id")
            dftype = fl[0].get("field_type", "FIELD_TYPE_TEXT")

    if fields and dfid:
        call_mcp("smartsheet_update_fields", {
            "docid": docid, "sheet_id": sid,
            "fields": [{"field_id": dfid, "field_title": fields[0]["field_title"], "field_type": fields[0].get("field_type", "FIELD_TYPE_TEXT")}]
        })
        if len(fields) > 1:
            call_mcp("smartsheet_add_fields", {
                "docid": docid, "sheet_id": sid,
                "fields": [{"field_title": f["field_title"], "field_type": f["field_type"]} for f in fields[1:]]
            })
        steps.append(f"  {len(fields)} 个字段已配置")

    if records:
        cf = extract(call_mcp("smartsheet_get_fields", {"docid": docid, "sheet_id": sid}))
        fmap = {}
        if isinstance(cf, dict):
            for f in cf.get("fields", []):
                fmap[f["field_title"]] = f

        fmtd = []
        for rec in records:
            vals = {}
            for k, v in rec.items():
                if k not in fmap:
                    continue
                ft = fmap[k].get("field_type", "FIELD_TYPE_TEXT")
                if ft == "FIELD_TYPE_TEXT":
                    vals[k] = [{"type": "text", "text": str(v)}]
                elif ft in ("FIELD_TYPE_NUMBER", "FIELD_TYPE_CURRENCY", "FIELD_TYPE_PERCENTAGE", "FIELD_TYPE_PROGRESS"):
                    try:
                        vals[k] = float(v)
                    except:
                        vals[k] = [{"type": "text", "text": str(v)}]
                elif ft == "FIELD_TYPE_SINGLE_SELECT":
                    vals[k] = [{"text": str(v)}]
                elif ft == "FIELD_TYPE_DATE_TIME":
                    vals[k] = str(v)
                elif ft == "FIELD_TYPE_CHECKBOX":
                    vals[k] = bool(v)
                elif ft in ("FIELD_TYPE_PHONE_NUMBER", "FIELD_TYPE_EMAIL", "FIELD_TYPE_BARCODE"):
                    vals[k] = str(v)
                else:
                    vals[k] = [{"type": "text", "text": str(v)}]
            fmtd.append({"values": vals})

        if fmtd:
            call_mcp("smartsheet_add_records", {"docid": docid, "sheet_id": sid, "records": fmtd})
            steps.append(f"  {len(fmtd)} 条示例数据已写入")


def process_create(schema):
    """单文档多子表模式：创建一个智能表格，包含所有子表"""
    doc_name = schema.get("doc_name", "Demo智能表格")
    sheets = schema.get("sheets", [])
    if not sheets:
        return {"error": "sheets 为空", "success": False}

    steps = []

    # 1. 创建文档
    r = extract(call_mcp("create_doc", {"doc_type": 10, "doc_name": doc_name}))
    if not r or (isinstance(r, dict) and r.get("errcode", 0) != 0):
        return {"error": "创建文档失败", "detail": str(r), "success": False}

    docid = r.get("docid") if isinstance(r, dict) else None
    doc_url = r.get("url") if isinstance(r, dict) else None
    if not docid:
        return {"error": "未获取 docid", "detail": str(r), "success": False}
    steps.append("文档已创建")

    # 2. 获取默认子表
    sr = extract(call_mcp("smartsheet_get_sheet", {"docid": docid}))
    default_sid = None
    if isinstance(sr, dict):
        sl = sr.get("sheet_list", sr.get("sheets", []))
        if isinstance(sl, list) and sl:
            default_sid = sl[0].get("sheet_id")

    created = []
    for idx, sdef in enumerate(sheets):
        sname = sdef.get("sheet_name", f"子表{idx+1}")
        fields = sdef.get("fields", [])
        records = sdef.get("sample_records", [])

        if idx == 0 and default_sid:
            # 第一个子表：复用默认子表，重命名
            sid = default_sid
            call_mcp("smartsheet_update_sheet", {
                "docid": docid, "sheet_id": sid,
                "properties": {"sheet_id": sid, "title": sname}
            })
        else:
            # 后续子表：新建
            sr2 = extract(call_mcp("smartsheet_add_sheet", {"docid": docid, "title": sname}))
            sid = None
            if isinstance(sr2, dict):
                sid = sr2.get("sheet_id") or (sr2.get("properties", {}) or {}).get("sheet_id")
            if not sid:
                steps.append(f"子表「{sname}」创建失败")
                continue
            # 重命名新子表（properties 里必须同时带 sheet_id 和 title）
            call_mcp("smartsheet_update_sheet", {
                "docid": docid, "sheet_id": sid,
                "properties": {"sheet_id": sid, "title": sname}
            })

        steps.append(f"子表「{sname}」就绪")

        # 配置字段和数据
        setup_sheet_fields(docid, sid, fields, records, steps, sname)
        created.append({"sheet_name": sname, "sheet_id": sid})

    return {"success": True, "doc_name": doc_name, "docid": docid, "url": doc_url, "sheets": created, "steps": steps}


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            schema = json.loads(body)
        except:
            self._respond(400, {"error": "无效 JSON"})
            return
        result = process_create(schema)
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
