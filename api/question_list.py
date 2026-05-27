"""Vercel Serverless: POST /api/question_list -> 智能提问清单生成"""
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


def match_field_template(query, templates):
    if not query or not templates:
        return None
    query_lower = query.lower()
    best_score = 0
    best_tpl = None
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
        if score > best_score:
            best_score = score
            best_tpl = tpl
    return best_tpl if best_score >= 4 else None


def build_context(industry, pain_points, direction):
    """构建知识库上下文供AI生成提问清单 - 深度引用所有层级"""
    query = f"{industry} {direction} {pain_points}".strip()

    industry_knowledge = load_industry_knowledge()
    detailed_cases = load_detailed_cases()
    field_templates = load_field_templates()

    # 1. 行业知识（完整传入）
    industry_data = match_industry(industry, industry_knowledge)
    industry_text = ""
    if industry_data:
        content = industry_data.get("content", "")
        industry_text = content[:3000] if len(content) > 3000 else content

    # 2. 案例深度提取 - 完整内容
    matched_cases = match_cases(query, detailed_cases, top_k=3)
    case_context = ""
    for case in matched_cases:
        meta = case.get("meta", {})
        pain = case.get("pain_points", [])
        solution = case.get("solution", {})
        tables = solution.get("tables", [])
        comm_record = case.get("communication_record", "")
        comm_highlights = case.get("communication_highlights", [])
        delivery_desc = case.get("delivery_description", "")

        case_context += f"### 真实交付案例：{meta.get('industry', '')} - {meta.get('scene', '')}\n"
        case_context += f"客户规模：{meta.get('scale', '未知')}\n"

        # 客户痛点（学习客户会有什么疑问和需求）
        if pain:
            case_context += f"客户原始痛点：\n"
            for p in pain:
                case_context += f"  - {p}\n"

        # 方案架构
        if solution.get("architecture"):
            case_context += f"最终方案：{solution['architecture']}\n"

        # 完整的表结构和字段
        if tables:
            case_context += f"方案包含的子表和字段：\n"
            for t in tables[:6]:
                tname = t.get("table_name", "")
                purpose = t.get("purpose", "")
                usage_role = t.get("usage_role", "")
                fields = t.get("fields", [])
                case_context += f"  表「{tname}」({purpose})"
                if usage_role:
                    case_context += f" 使用者：{usage_role}"
                case_context += "\n"
                if fields:
                    case_context += f"    字段：{', '.join(fields[:15])}\n"

        # 自动化规则（帮助AI知道该问什么自动化需求）
        auto_rules = solution.get("automation_rules", [])
        if not auto_rules:
            auto_rules = case.get("automation_rules", [])
        if auto_rules:
            case_context += f"配置的自动化规则：\n"
            for r in auto_rules[:5]:
                case_context += f"  - {r}\n"

        # 服务商沟通记录（学习如何提问）
        if comm_record:
            case_context += f"服务商与客户沟通记录：\n  {comm_record}\n"

        # 沟通亮点（学习服务商确认了哪些关键信息）
        if comm_highlights:
            case_context += f"沟通中确认的关键信息点（服务商在实际调研中需要弄清楚的）：\n"
            for h in comm_highlights:
                case_context += f"  - {h}\n"

        # 交付描述
        if delivery_desc:
            desc = delivery_desc[:300] if len(delivery_desc) > 300 else delivery_desc
            case_context += f"交付说明：{desc}\n"

        case_context += "\n"

    # 如果精确匹配的案例没有沟通记录，补充一些有沟通记录的案例作为提问方式参考
    has_comm = any(
        c.get("communication_record") or c.get("communication_highlights")
        for c in matched_cases
    )
    if not has_comm:
        comm_examples = ""
        for case in detailed_cases:
            ch = case.get("communication_highlights", [])
            cr = case.get("communication_record", "")
            if ch or cr:
                meta = case.get("meta", {})
                comm_examples += f"参考案例（{meta.get('industry','')}-{meta.get('scene','')[:20]}）中服务商确认的信息点：\n"
                if cr:
                    comm_examples += f"  沟通记录：{cr[:200]}\n"
                for h in ch[:6]:
                    comm_examples += f"  - {h}\n"
                comm_examples += "\n"
                if len(comm_examples) > 1500:
                    break
        if comm_examples:
            case_context += "\n### 其他行业的服务商提问参考（学习提问深度和方式）\n" + comm_examples

    # 3. 字段模板（完整传入字段细节）
    matched_tpl = match_field_template(query, field_templates)
    tpl_context = ""
    if matched_tpl:
        meta = matched_tpl.get("meta", {})
        tpl_context = f"### 字段经验池：{meta.get('industry', '')} - {meta.get('scene', '')}\n"
        tpl_context += f"该行业真实交付过{meta.get('total_tables', '?')}张表，{meta.get('total_fields', '?')}个字段\n"
        if meta.get("design_principle"):
            tpl_context += f"设计原则：{meta['design_principle']}\n"
        tpl_context += f"你需要据此判断该行业需要调研的方面：\n"
        for table in matched_tpl.get("tables", [])[:8]:
            tpl_context += f"  表「{table.get('table_name', '')}」"
            if table.get("description"):
                tpl_context += f"（{table['description']}）"
            tpl_context += ":\n"
            for g in table.get("field_groups", [])[:5]:
                gname = g.get("group_name", "")
                fields = [f.get("title", "") for f in g.get("fields", [])[:8]]
                tpl_context += f"    [{gname}] {', '.join(fields)}\n"

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
        "temperature": 0.7,
        "max_tokens": 3500
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
        with urllib.request.urlopen(req, timeout=55) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Error calling DeepSeek: {str(e)}"


SYSTEM_PROMPT = """你是一个资深的企业微信智能表格定制开发售前顾问，拥有丰富的行业交付经验。

你的任务是：根据客户的行业、业务描述和痛点，结合知识库中的行业知识和交付案例，为服务商输出一份完整的调研准备材料。

## 输出结构（严格按以下4个部分输出，不要开场白）

### PART1: 业务场景速览

用2-3句话总结客户可能的业务场景，帮服务商快速理解这个客户大概率处在什么背景下。格式例如：
"这是一个XX行业客户，核心业务是XX，目前的主要问题可能是XX、XX和XX。基于同行业经验，他们通常需要XX。"

### PART2: 缺失信息检测

判断客户描述中缺了哪些关键信息，逐条列出。每条说明为什么这个信息很重要。格式：
- ❓ 业务流程不清晰：客户只说了"订单管理"，但没说从哪一步到哪一步、中间经过几个角色
- ❓ 数据现状不明：不确定现在是用Excel还是有系统，影响方案设计
- ❓ ...

### PART3: 建议追问维度

告诉服务商应该重点从哪几个方向深入调研，每个方向给一句话说明为什么重要。格式：
1. **流程梳理** - 需要把从XX到XX的完整链路画清楚，才能确定需要几张表
2. **角色权限** - 涉及多个角色操作同一套数据，需要明确谁看谁改
3. **自动化场景** - 客户提到XX痛点，背后可能有XX自动化需求
4. ...
（列出5-8个最关键的追问方向）

### PART4: 详细提问清单

逐条列出需要问客户的具体问题。

## 17个必须覆盖的维度

1. 公司概况  2. 业务模式  3. 组织架构  4. 现状工具  5. 痛点收敛
6. 业务流转  7. 角色清单  8. 数据来源  9. 数据流向  10. 堵点分析
11. 自动化诉求  12. 权限设计  13. 数据接入  14. 仪表盘  15. 通知提醒
16. 预算范围  17. 交付预期

## 提问规则

1. 每个问题只聚焦一个维度
2. 问题必须结合客户的行业和业务特点来设计，不能泛泛地问
3. 参考知识库中的服务商沟通记录，学习真实场景下的提问方式
4. 参考字段经验池中的字段维度，设计探测性问题
5. 问题用大白话，像面对面聊天一样自然
6. 问题要细致具体，不能笼统
7. 总问题数控制在20-28个，核心维度多问几个
8. 每个问题标注维度标签

## PART4输出格式

每个问题格式：
[维度名] 问题内容
> 问这个是为了确认什么"""


def generate_question_list(body):
    """返回知识库上下文和prompt，前端直接调DeepSeek"""
    industry = body.get("industry", "")
    pain_points = body.get("pain_points", "")
    direction = body.get("direction", "")
    business_desc = body.get("business_desc", "")

    # 构建知识库上下文
    context = build_context(industry, pain_points, direction or business_desc)

    # 组装用户prompt
    user_prompt = "## 客户信息\n"
    user_prompt += f"- 行业：{industry}\n"
    if business_desc:
        user_prompt += f"- 业务描述：{business_desc}\n"
    if pain_points:
        user_prompt += f"- 痛点/希望解决的问题：{pain_points}\n"
    if direction:
        user_prompt += f"- 需求方向：{direction}\n"

    if context["industry_knowledge"]:
        user_prompt += f"\n## 行业背景知识\n{context['industry_knowledge']}\n"
    if context["case_context"]:
        user_prompt += f"\n## 相关交付案例\n{context['case_context']}\n"
    if context["template_context"]:
        user_prompt += f"\n## 字段经验池参考\n{context['template_context']}\n"

    user_prompt += "\n请严格按PART1-PART4的结构输出完整的调研准备材料。"

    # 返回prompt供前端直接调DeepSeek（无超时限制）
    return {
        "system_prompt": SYSTEM_PROMPT,
        "user_prompt": user_prompt,
        "context_used": {
            "industry_matched": bool(context["industry_knowledge"]),
            "cases_matched": bool(context["case_context"]),
            "template_matched": bool(context["template_context"])
        }
    }


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
        except:
            self._respond(400, {"error": "Invalid JSON"})
            return

        if not data.get("industry"):
            self._respond(400, {"error": "industry is required"})
            return

        result = generate_question_list(data)
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
