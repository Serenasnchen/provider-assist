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
    """构建知识库上下文供AI生成提问清单"""
    query = f"{industry} {direction} {pain_points}".strip()

    industry_knowledge = load_industry_knowledge()
    detailed_cases = load_detailed_cases()
    field_templates = load_field_templates()

    # 匹配行业知识
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
        pain = case.get("pain_points", [])
        solution = case.get("solution", {})
        tables = solution.get("tables", [])
        case_context += f"【案例：{meta.get('industry', '')} - {meta.get('scene', '')}】\n"
        case_context += f"  痛点：{'; '.join(pain[:4])}\n"
        if tables:
            table_names = [t.get("table_name", "") for t in tables[:6]]
            case_context += f"  方案涉及：{', '.join(table_names)}\n"
        case_context += "\n"

    # 匹配字段模板
    matched_tpl = match_field_template(query, field_templates)
    tpl_context = ""
    if matched_tpl:
        meta = matched_tpl.get("meta", {})
        tpl_context = f"【字段经验池：{meta.get('industry', '')} - {meta.get('scene', '')}】\n"
        tpl_context += f"  涉及{meta.get('total_tables', '?')}张表，{meta.get('total_fields', '?')}个字段\n"
        for table in matched_tpl.get("tables", [])[:5]:
            tpl_context += f"  - {table.get('table_name', '')}: "
            groups = table.get("field_groups", [])
            group_names = [g.get("group_name", "") for g in groups]
            tpl_context += "、".join(group_names) + "\n"

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
        "max_tokens": 3000
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

你的任务是：根据客户的行业、业务描述和痛点，结合知识库中的行业知识和交付案例，为服务商生成一份高质量的需求调研提问清单。

## 17个必须覆盖的维度

以下维度在提问清单中都需要涉及到（不需要分阶段，自然组织即可）：

1. 公司概况 - 行业、主营、规模
2. 业务模式 - B2B/B2C/内部管理、核心业务链
3. 组织架构 - 涉及的部门和人员
4. 现状工具 - 现在用什么管理（Excel/系统/纸质）
5. 痛点收敛 - 多个问题时确认优先级
6. 业务流转 - 核心流程每一步谁做什么
7. 角色清单 - 内部使用者 + 外部参与方
8. 数据来源 - 数据在哪产生、量级、更新频率
9. 数据流向 - 谁录入、谁审批、谁查看
10. 堵点分析 - 卡在哪、为什么解决不好
11. 自动化诉求 - 哪些希望系统自动做
12. 权限设计 - 谁看什么、谁改什么
13. 数据接入 - 是否对接外部系统
14. 仪表盘 - 管理层想看什么
15. 通知提醒 - 什么场景需要提醒
16. 预算范围
17. 交付预期 - 时间、节奏

## 提问规则

1. 问题必须结合客户的行业和业务特点来设计，不是泛泛地问。比如客户是汽车贷款行业、说了"订单流转"的痛点，你就应该问"从业务员提交贷款申请到放款，中间要过几道审核？每道审核是谁来做、看什么资料？"——而不是问"请描述一下你们的业务流程"。
2. 如果知识库提供了行业知识或交付案例，要参考案例中涉及的业务场景来设计问题。比如案例显示该行业通常需要"设备台账管理"，就应该问客户"你们有多少台设备需要管？现在设备信息记在哪里？"
3. 如果知识库提供了字段经验池，要参考其中涉及的业务维度来发现客户可能遗漏的需求点，设计探测性问题。
4. 问题用大白话，像面对面聊天一样自然，禁止"请问贵司""能否介绍一下"这种官腔。
5. 一个问题可以覆盖多个追问点，用逗号连接。
6. 总问题数控制在15-20个。

## 输出格式

- 直接输出，不要开场白和总结语
- 每个问题前标注维度：`【维度名】`
- 问题编号用 1. 2. 3.
- 每个问题后用 > 引用格式写一句"问这个是为了确认什么"
- 相关联的问题可以连续排列，形成自然的追问逻辑"""


def generate_question_list(body):
    """生成智能提问清单"""
    industry = body.get("industry", "")
    pain_points = body.get("pain_points", "")
    direction = body.get("direction", "")
    description = body.get("description", "")

    # 构建知识库上下文
    context = build_context(industry, pain_points, direction)

    # 组装用户prompt
    user_prompt = f"## 客户信息\n"
    user_prompt += f"- 行业：{industry}\n"
    if description:
        user_prompt += f"- 描述：{description}\n"
    if pain_points:
        user_prompt += f"- 痛点：{pain_points}\n"
    if direction:
        user_prompt += f"- 需求方向：{direction}\n"

    if context["industry_knowledge"]:
        user_prompt += f"\n## 行业背景知识\n{context['industry_knowledge']}\n"
    if context["case_context"]:
        user_prompt += f"\n## 相关交付案例\n{context['case_context']}\n"
    if context["template_context"]:
        user_prompt += f"\n## 字段经验池参考\n{context['template_context']}\n"

    user_prompt += "\n请根据以上信息，为服务商生成一份分维度的提问清单。"

    # 调用AI
    result = call_deepseek(SYSTEM_PROMPT, user_prompt)

    return {
        "question_list": result,
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
