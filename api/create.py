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


def normalize_field_type(ft):
    """确保 field_type 带有 FIELD_TYPE_ 前缀"""
    if not ft:
        return "FIELD_TYPE_TEXT"
    ft = ft.strip().upper()
    if not ft.startswith("FIELD_TYPE_"):
        ft = "FIELD_TYPE_" + ft
    # 映射常见别名
    alias_map = {
        "FIELD_TYPE_DATE": "FIELD_TYPE_DATE_TIME",
        "FIELD_TYPE_DATETIME": "FIELD_TYPE_DATE_TIME",
        "FIELD_TYPE_SELECT": "FIELD_TYPE_SINGLE_SELECT",
        "FIELD_TYPE_MULTISELECT": "FIELD_TYPE_MULTI_SELECT",
        "FIELD_TYPE_MULTI": "FIELD_TYPE_MULTI_SELECT",
        "FIELD_TYPE_PHONE": "FIELD_TYPE_PHONE_NUMBER",
        "FIELD_TYPE_TEL": "FIELD_TYPE_PHONE_NUMBER",
        "FIELD_TYPE_LINK": "FIELD_TYPE_URL",
        "FIELD_TYPE_MONEY": "FIELD_TYPE_CURRENCY",
        "FIELD_TYPE_AMOUNT": "FIELD_TYPE_CURRENCY",
        "FIELD_TYPE_PERCENT": "FIELD_TYPE_PERCENTAGE",
        "FIELD_TYPE_NUM": "FIELD_TYPE_NUMBER",
        "FIELD_TYPE_INT": "FIELD_TYPE_NUMBER",
        "FIELD_TYPE_BOOL": "FIELD_TYPE_CHECKBOX",
        "FIELD_TYPE_BOOLEAN": "FIELD_TYPE_CHECKBOX",
    }
    ft = alias_map.get(ft, ft)
    # 验证是否是合法类型
    valid_types = {
        "FIELD_TYPE_TEXT", "FIELD_TYPE_NUMBER", "FIELD_TYPE_SINGLE_SELECT",
        "FIELD_TYPE_MULTI_SELECT", "FIELD_TYPE_DATE_TIME", "FIELD_TYPE_CHECKBOX",
        "FIELD_TYPE_USER", "FIELD_TYPE_PHONE_NUMBER", "FIELD_TYPE_EMAIL",
        "FIELD_TYPE_URL", "FIELD_TYPE_CURRENCY", "FIELD_TYPE_PERCENTAGE",
        "FIELD_TYPE_PROGRESS", "FIELD_TYPE_AUTO_NUMBER", "FIELD_TYPE_LOCATION",
        "FIELD_TYPE_CREATED_TIME", "FIELD_TYPE_MODIFIED_TIME",
        "FIELD_TYPE_CREATED_USER", "FIELD_TYPE_MODIFIED_USER",
        "FIELD_TYPE_BARCODE", "FIELD_TYPE_RATING",
    }
    if ft not in valid_types:
        return "FIELD_TYPE_TEXT"
    return ft


def setup_sheet_fields(docid, sid, fields, records, steps, sname):
    """为单个智能表格的默认子表配置字段和数据"""
    fr = extract(call_mcp("smartsheet_get_fields", {"docid": docid, "sheet_id": sid}))
    dfid = None
    if isinstance(fr, dict):
        fl = fr.get("fields", [])
        if fl:
            dfid = fl[0].get("field_id")

    if fields and dfid:
        # 更新第一个字段（复用默认字段）
        call_mcp("smartsheet_update_fields", {
            "docid": docid, "sheet_id": sid,
            "fields": [{"field_id": dfid, "field_title": fields[0]["field_title"], "field_type": normalize_field_type(fields[0].get("field_type", "TEXT"))}]
        })
        # 分批添加剩余字段（每批最多5个，避免API限制）
        remaining = fields[1:]
        batch_size = 5
        for i in range(0, len(remaining), batch_size):
            batch = remaining[i:i+batch_size]
            resp = call_mcp("smartsheet_add_fields", {
                "docid": docid, "sheet_id": sid,
                "fields": [{"field_title": f["field_title"], "field_type": normalize_field_type(f.get("field_type", "TEXT"))} for f in batch]
            })
            r = extract(resp)
            if isinstance(r, dict) and r.get("errcode", 0) != 0:
                steps.append(f"  ⚠️ 添加字段批次失败: {r.get('errmsg', '')}")
        steps.append(f"  {len(fields)} 个字段已配置")
    elif fields and not dfid:
        # 没拿到默认字段ID，尝试直接全部添加
        batch_size = 5
        for i in range(0, len(fields), batch_size):
            batch = fields[i:i+batch_size]
            call_mcp("smartsheet_add_fields", {
                "docid": docid, "sheet_id": sid,
                "fields": [{"field_title": f["field_title"], "field_type": normalize_field_type(f.get("field_type", "TEXT"))} for f in batch]
            })
        steps.append(f"  {len(fields)} 个字段已添加(fallback)")

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
    """创建文档+处理第一个子表"""
    doc_name = schema.get("doc_name", "Demo智能表格")
    sheets = schema.get("sheets", [])
    if not sheets:
        return {"error": "sheets 为空", "success": False}

    steps = []

    # 创建文档
    r = extract(call_mcp("create_doc", {"doc_type": 10, "doc_name": doc_name}))
    if not r or (isinstance(r, dict) and r.get("errcode", 0) != 0):
        return {"error": "创建文档失败", "detail": str(r), "success": False}

    docid = r.get("docid") if isinstance(r, dict) else None
    doc_url = r.get("url") if isinstance(r, dict) else None
    if not docid:
        return {"error": "未获取 docid", "detail": str(r), "success": False}
    steps.append("文档已创建")

    # 获取默认子表
    sr = extract(call_mcp("smartsheet_get_sheet", {"docid": docid}))
    default_sid = None
    if isinstance(sr, dict):
        sl = sr.get("sheet_list", sr.get("sheets", []))
        if isinstance(sl, list) and sl:
            default_sid = sl[0].get("sheet_id")

    # 只处理第一个子表
    sdef = sheets[0]
    sname = sdef.get("sheet_name", "子表1")
    fields = sdef.get("fields", [])
    records = sdef.get("sample_records", [])

    sid = default_sid
    if sid:
        call_mcp("smartsheet_update_sheet", {"docid": docid, "sheet_id": sid, "properties": {"sheet_id": sid, "title": sname}})
    steps.append(f"子表「{sname}」就绪")
    setup_sheet_fields(docid, sid, fields, records, steps, sname)

    return {"success": True, "doc_name": doc_name, "docid": docid, "url": doc_url,
            "sheets": [{"sheet_name": sname, "sheet_id": sid}],
            "steps": steps, "remaining": len(sheets) - 1}


def process_add_sheet(data):
    """为已有文档添加一个子表（含字段+数据）"""
    docid = data.get("docid")
    sdef = data.get("sheet")
    if not docid or not sdef:
        return {"error": "缺少 docid 或 sheet", "success": False}

    steps = []
    sname = sdef.get("sheet_name", "子表")
    fields = sdef.get("fields", [])
    records = sdef.get("sample_records", [])

    sr2 = extract(call_mcp("smartsheet_add_sheet", {"docid": docid, "title": sname}))
    sid = None
    if isinstance(sr2, dict):
        sid = sr2.get("sheet_id") or (sr2.get("properties", {}) or {}).get("sheet_id")
    if not sid:
        return {"error": f"子表「{sname}」创建失败", "success": False}

    # 重命名子表（add_sheet的title参数可能不生效）
    call_mcp("smartsheet_update_sheet", {
        "docid": docid, "sheet_id": sid,
        "properties": {"sheet_id": sid, "title": sname}
    })

    steps.append(f"子表「{sname}」就绪")
    setup_sheet_fields(docid, sid, fields, records, steps, sname)

    return {"success": True, "sheet_name": sname, "sheet_id": sid, "steps": steps}


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
        except:
            self._respond(400, {"error": "无效 JSON"})
            return

        # 分流：如果有 docid + sheet，是追加子表；否则是创建新文档
        if data.get("docid") and data.get("sheet"):
            result = process_add_sheet(data)
        else:
            result = process_create(data)
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
