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

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
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


SYSTEM_PROMPT_REPORT = """你是一个专业的企业微信智能表格售前方案顾问。你的任务是根据服务商与客户的沟通记录（会议转写/文字记录），生成结构化的需求分析报告。

## 输出要求

请严格按以下结构输出Markdown格式的报告：

### 一、客户概况
- 公司名称/行业/规模
- 当前痛点和管理现状

### 二、需求分析
按优先级列出客户的核心需求，每条需求包含：
- 需求描述
- 业务背景（为什么需要）
- 涉及的业务场景

### 三、方案建议
- 整体方案架构
- 建议的智能表数量和用途
- 关键自动化规则
- 权限设计建议

### 四、实施建议
- 分期规划（如适用）
- 数据迁移注意事项
- 风险提示

### 五、预估工作量
- 表格搭建
- 自动化配置
- 培训交付

## 重要原则
1. 报告要基于沟通记录中客户明确说到的内容，不要臆测
2. 结合行业知识和案例经验，给出专业建议
3. 如果有字段经验池参考，用它来验证方案的完整性，但不要照搬
4. 语言专业但易懂，服务商可以直接用这份报告给客户看"""


SYSTEM_PROMPT_SCHEMA = """你是一个专业的企业微信智能表格架构师。你的任务是根据客户需求，设计智能表格的表和字段结构。

## 输出要求

请严格输出JSON格式，结构如下：
```json
{
  "tables": [
    {
      "table_name": "表名",
      "description": "表的用途说明",
      "fields": [
        {
          "title": "字段名",
          "type": "字段类型",
          "description": "字段说明",
          "required": true/false
        }
      ]
    }
  ],
  "relations": [
    {"from": "表A.字段X", "to": "表B.字段Y", "type": "1:N"}
  ],
  "automation_rules": ["规则1", "规则2"]
}
```

## 字段类型可选值
text(文本), number(数字), select(单选), multi_select(多选), date(日期), member(成员), attachment(附件), formula(公式), link(关联), checkbox(复选框), url(链接), phone(电话), email(邮箱), location(地点), progress(进度), currency(货币)

## 设计原则
1. 如果有字段经验池，参考它来设计（不是照搬，而是结合客户实际需求选用合适的）
2. 表之间通过"关联字段"连接，形成数据网络
3. 一张表聚焦一个业务对象
4. 字段命名要业务化，不要技术化
5. 必填字段标记 required: true
6. 预留合理的统计/分析字段（如公式字段）"""


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
