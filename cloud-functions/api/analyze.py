"""Vercel Serverless: POST /api/analyze -> 会议转写结构化分析（生成三件套）"""
import json
import os
import re
from http.server import BaseHTTPRequestHandler
from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge"


def load_industry_knowledge():
    industries = {}
    ind_dir = KNOWLEDGE_DIR / "industries"
    if ind_dir.exists():
        for f in ind_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                industries[f.stem] = data
            except:
                pass
    return industries


def load_detailed_cases():
    cases = []
    cases_dir = KNOWLEDGE_DIR / "cases"
    if cases_dir.exists():
        for f in cases_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                cases.append(data)
            except:
                pass
    return cases


def load_field_templates():
    templates = []
    tpl_dir = KNOWLEDGE_DIR / "field_templates"
    if tpl_dir.exists():
        for f in tpl_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                templates.append(data)
            except:
                pass
    return templates


def match_industry(industry, industry_knowledge):
    if not industry:
        return None
    industry_lower = industry.lower()
    for key, data in industry_knowledge.items():
        tags = [t.lower() for t in data.get("tags", [])]
        name = data.get("industry_name", "").lower()
        if industry_lower in name or any(industry_lower in t or t in industry_lower for t in tags):
            return data
    return None


def match_cases(query, detailed_cases, top_k=2):
    if not query or not detailed_cases:
        return []
    query_lower = query.lower()
    scored = []
    for case in detailed_cases:
        score = 0
        meta = case.get("meta", {})
        case_industry = meta.get("industry", "").lower()
        case_scene = meta.get("scene", "").lower()
        if case_industry in query_lower or query_lower in case_industry:
            score += 5
        if case_scene in query_lower:
            score += 3
        summary = case.get("demand_summary", "").lower()
        for word in re.split(r'[，,、。\s]+', query_lower):
            if len(word) >= 2 and word in summary:
                score += 2
        if score > 0:
            scored.append((score, case))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:top_k]]


def match_field_templates(query, templates, top_k=2):
    if not query or not templates:
        return []
    query_lower = query.lower()
    scored = []
    for tpl in templates:
        score = 0
        meta = tpl.get("meta", {})
        industry = meta.get("industry", "").lower()
        scene = meta.get("scene", "").lower()
        applicable = meta.get("applicable_when", "").lower()
        if industry in query_lower or query_lower in industry:
            score += 5
        for word in re.split(r'[，,、。/\s+]+', scene):
            if len(word) >= 2 and word in query_lower:
                score += 3
        for word in re.split(r'[，,、。/\s：:]+', applicable):
            if len(word) >= 2 and word in query_lower:
                score += 2
        if score >= 4:
            scored.append((score, tpl))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [t for _, t in scored[:top_k]]


def format_template_for_prompt(tpl):
    """格式化字段模板为AI可读文本"""
    if not tpl:
        return ""
    meta = tpl.get("meta", {})
    lines = [f"### 字段经验池：{meta.get('industry', '')} - {meta.get('scene', '')}"]
    lines.append(f"来源：{meta.get('source', '真实交付案例')}")
    lines.append(f"规模：{meta.get('total_tables', '?')}张表，{meta.get('total_fields', '?')}个字段")
    if meta.get("design_principle"):
        lines.append(f"设计原则：{meta['design_principle']}")
    lines.append("")
    for table in tpl.get("tables", []):
        lines.append(f"**表：{table.get('table_name', '')}**")
        if table.get("description"):
            lines.append(f"  用途：{table['description']}")
        for group in table.get("field_groups", []):
            gname = group.get("group_name", "")
            fields = group.get("fields", [])
            field_strs = [f.get("title", "") for f in fields[:8]]
            lines.append(f"  [{gname}] {', '.join(field_strs)}")
    return "\n".join(lines)


def build_analysis_context(industry, transcript):
    """基于行业和转写内容构建知识库上下文"""
    query = f"{industry} {transcript[:200]}".strip()

    industry_knowledge = load_industry_knowledge()
    detailed_cases = load_detailed_cases()
    field_templates = load_field_templates()

    # 匹配行业
    industry_data = match_industry(industry, industry_knowledge)
    industry_text = ""
    if industry_data:
        content = industry_data.get("content", "")
        industry_text = content[:2000] if len(content) > 2000 else content

    # 匹配案例
    matched_cases = match_cases(query, detailed_cases, top_k=2)
    case_context = ""
    for case in matched_cases:
        meta = case.get("meta", {})
        solution = case.get("solution", {})
        case_context += f"【案例：{meta.get('industry', '')} - {meta.get('scene', '')}】\n"
        case_context += f"  架构：{solution.get('architecture', '')}\n"
        tables = solution.get("tables", [])
        if tables:
            for t in tables[:5]:
                case_context += f"  - {t.get('table_name', '')}: {', '.join(f.get('title','') for f in t.get('fields', [])[:6])}\n"
        rules = solution.get("automation_rules", [])
        if rules:
            case_context += f"  自动化：{'; '.join(rules[:3])}\n"
        case_context += "\n"

    # 匹配字段模板
    matched_tpls = match_field_templates(query, field_templates, top_k=2)
    tpl_context = ""
    for tpl in matched_tpls:
        tpl_context += format_template_for_prompt(tpl) + "\n\n"

    return {
        "industry_knowledge": industry_text,
        "case_context": case_context.strip(),
        "template_context": tpl_context.strip()
    }


def call_deepseek(system_prompt, user_prompt):
    """调用DeepSeek API"""
    import urllib.request

    api_key = os.environ.get("DEEPSEEK_API_KEY", "sk-63d4e005ecb646b08538368c5172ed82")
    if not api_key:
        return "Error: DEEPSEEK_API_KEY not configured"

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.5,
        "max_tokens": 6000
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
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Error calling DeepSeek: {str(e)}"


SYSTEM_PROMPT_REPORT = """你是一个专业的企业微信智能表格售前方案顾问。根据服务商与客户的沟通记录，生成结构化的需求洞察报告。

## 输出格式（严格遵守，直接输出，不要开场白/总结语/注意事项）

## 客户信息
- 行业：
- 规模：
- 需求方向：

## 核心痛点
逐条列出客户提到的痛点，每条用客户原话引用，并简要分析该痛点的业务影响：
1. **痛点名称**："客户原话引用"
   - 影响：xxx

## 业务场景
- 核心流程：用箭头描述完整业务链路（如：业务员提交 → 中台复审 → 后台归档）
- 涉及角色：列出每个环节对应的角色/部门
- 数据流向：数据从哪里产生、在哪里流转、最终在哪里使用

## 详细规格
- 数据规模：预估数据量（条/月）、使用人数
- 权限需求：按角色说明（谁能看什么、谁能改什么）
- 提醒/通知：需要哪些自动通知场景
- 对接需求：是否有外部系统需要对接

## 智能表格搭建方案

### 子表结构
按表格形式列出每张子表：
| 子表名称 | 用途 | 核心字段（6-8个） | 使用者 |
|---------|------|------------------|--------|

### 自动化规则
逐条列出关键自动化（触发条件 → 执行动作）：
1. 当xxx时 → 自动xxx
2. ...

### 推荐视图
- 表格视图：用于xxx
- 看板视图：用于xxx
- 仪表盘：管理层看xxx指标

### 权限设计
按角色说明数据隔离策略

## 预估交付周期
- 第一期（x周）：xxx
- 第二期（x周）：xxx

## 待确认事项

AI 自动识别沟通记录中客户没有讲清楚的地方，列出需要服务商后续跟进确认的事项：
- ❓ 具体问题描述（例如"是否需要与ERP对接？客户提到了用友但没说是否要数据同步"）
- ❓ ...
- ❓ ...
列出所有需要二次确认的事项，帮服务商知道哪些信息还没拿到。

## 原则
1. 基于沟通记录中客户明确说到的内容，不要臆测
2. 痛点必须用客户原话引用（加引号），这是报告最有说服力的部分
3. 方案要细致到字段级别，服务商看了就知道要搭什么
4. 不要输出开场白、总结语或"请注意"之类的废话
5. 报告要有层次感：痛点用加粗、流程用箭头、方案用表格
6. 待确认事项是关键产出：分析客户话语中的模糊地带和遗漏"""


SYSTEM_PROMPT_SCHEMA = """你是一个专业的企业微信智能表格架构师。根据客户需求设计智能表格Demo结构。

## 输出格式（严格JSON，不要markdown代码块包裹，直接输出JSON）

{"doc_name":"表格名称","sheets":[{"sheet_name":"子表名称","fields":[{"field_title":"字段名","field_type":"字段类型"}],"sample_records":[{"字段名":"示例值"}]}]}

## 字段类型只能用
FIELD_TYPE_TEXT, FIELD_TYPE_NUMBER, FIELD_TYPE_SINGLE_SELECT, FIELD_TYPE_DATE_TIME, FIELD_TYPE_CURRENCY, FIELD_TYPE_PERCENTAGE, FIELD_TYPE_PROGRESS, FIELD_TYPE_PHONE_NUMBER, FIELD_TYPE_EMAIL, FIELD_TYPE_URL, FIELD_TYPE_CHECKBOX

## 设计原则
1. 如果有字段经验池，根据客户实际需求从中挑选合适的表和字段组合，不要照搬全部
2. 客户没提到的需求对应的表可以不给
3. 客户提了经验池中没有的需求，自行补充合理字段
4. 子表数量根据客户实际需求复杂度确定
5. 每个子表给6-10个核心字段
6. 每个子表给2-3条示例数据（数据要真实可信，贴合行业）
7. 字段命名要专业、贴合行业术语
8. 一张表聚焦一个业务对象"""


def analyze_transcript(body):
    """分析会议转写，生成三件套"""
    industry = body.get("industry", "")
    transcript = body.get("transcript", "")
    output_type = body.get("output_type", "all")  # report / schema / all

    if not transcript:
        return {"error": "transcript is required"}

    # 构建知识库上下文
    context = build_analysis_context(industry, transcript)

    kb_context = ""
    if context["industry_knowledge"]:
        kb_context += f"## 行业知识\n{context['industry_knowledge']}\n\n"
    if context["case_context"]:
        kb_context += f"## 相关交付案例\n{context['case_context']}\n\n"
    if context["template_context"]:
        kb_context += f"## 字段经验池（仅供参考，需结合客户实际需求选用）\n{context['template_context']}\n\n"

    results = {}

    # 生成需求报告
    if output_type in ("all", "report"):
        user_prompt = f"{kb_context}## 客户沟通记录\n\n{transcript}\n\n请基于以上沟通记录，生成结构化的需求分析报告。"
        results["report"] = call_deepseek(SYSTEM_PROMPT_REPORT, user_prompt)

    # 生成字段设计方案
    if output_type in ("all", "schema"):
        user_prompt = f"{kb_context}## 客户沟通记录\n\n{transcript}\n\n请基于以上沟通记录设计智能表格的表和字段结构，输出JSON。"
        schema_text = call_deepseek(SYSTEM_PROMPT_SCHEMA, user_prompt)
        results["schema"] = schema_text

        # 尝试从schema中提取JSON作为demo
        try:
            json_match = re.search(r'```json\s*(.*?)\s*```', schema_text, re.DOTALL)
            if json_match:
                results["demo_json"] = json.loads(json_match.group(1))
            else:
                results["demo_json"] = json.loads(schema_text)
        except:
            results["demo_json"] = None

    results["context_used"] = {
        "industry_matched": bool(context["industry_knowledge"]),
        "cases_matched": bool(context["case_context"]),
        "templates_matched": bool(context["template_context"])
    }

    return results


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
        except:
            self._respond(400, {"error": "Invalid JSON"})
            return

        if not data.get("transcript"):
            self._respond(400, {"error": "transcript is required"})
            return

        result = analyze_transcript(data)
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
