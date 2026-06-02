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
                    # fields可能是字符串列表或dict列表
                    field_names = []
                    for f in fields[:15]:
                        if isinstance(f, str):
                            field_names.append(f)
                        elif isinstance(f, dict):
                            field_names.append(f.get("field_title", f.get("title", "")))
                    case_context += f"    字段：{', '.join(field_names)}\n"

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


SYSTEM_PROMPT = """你是一个资深的企业微信智能表格定制开发售前顾问。

你的任务：根据客户行业和初始需求，为服务商输出一份**简洁清晰**的调研准备材料。

## ⚠️ 核心原则
- 问题要短，一句话能说清就不写两句
- 像面对面聊天，不要书面语
- 每个问题下方用小字给服务商提示（行业参考/引导方向/工具示例）
- 整体排版清爽，让服务商一眼看清该问什么

## 输出结构（严格3个部分，不要开场白/结尾总结）

---

### PART1: 客户画像

简要几行即可：
- 公司简介（有则引用，无则根据公司名推断一句话）
- 行业常见痛点（列3个，每个一句话）

---

### PART2: 信息缺口

客户描述中明显缺失的关键信息，列3-5条，每条一句话：
- ❓ 缺失点

---

### PART3: 提问清单

**格式要求**：每个问题独占一块，结构如下：

---
**[维度标签]**

问题正文（一句话，简短直白）

> 💡 备注：给服务商的小字提示，包含行业参考/引导维度/常见选项等

---

## 提问维度（共8个，每个维度1个问题）

| # | 维度 | 核心意图 |
|---|------|----------|
| 1 | 痛点收敛 | 如果只能优先解决一个问题，最想解决什么？ |
| 2 | 业务流程 | 围绕这个痛点，业务是怎么流转的？经过哪些人？ |
| 3 | 现状工具 | 现在用什么工具/方式在管？ |
| 4 | 数据现状 | 数据现在存在哪里？量级多大？ |
| 5 | 自动化 | 有没有希望系统自动帮你做的事？ |
| 6 | 使用者与权限 | 谁来用？数据需要隔离吗？ |
| 7 | 看板指标 | 最想看到什么数据指标？ |
| 8 | 交付预期 | 希望多久上线？预算范围？ |

## 提问规则

1. 总共8个问题，不多不少
2. 问题正文必须**简短**（一句话，最多两句），用大白话
3. 每个问题下方必须有 > 💡 备注（小字），包含：
   - 该行业常见的选项/示例（如「常用工具：飞书表格、Excel、ERP、纸质台账」）
   - 服务商引导方向（如「可以从响应速度、出错率、信息同步延迟等维度引导」）
   - 行业痛点提示（如「该行业客户通常在XX环节最痛」）
4. 问题必须结合客户的行业特点来设计，不能泛泛地问
5. 参考知识库中的案例和字段经验池，让问题更有针对性

## 示例（仅示意格式，实际内容需结合行业）

**[痛点收敛]**

如果只能优先解决一个问题，最想解决什么？

> 💡 该行业常见痛点：订单跟进混乱、生产进度不透明、客户信息分散。可以引导客户从「最花时间」或「最容易出错」的角度来回答。

**[现状工具]**

现在用什么工具同步信息？

> 💡 常见选项：Excel手工台账、微信群接龙、ERP系统（用友/金蝶）、纸质单据。问清楚为什么现有工具不够用。

"""


def generate_question_list(body):
    """返回知识库上下文和prompt，前端直接调DeepSeek"""
    industry = body.get("industry", "")
    # 支持新旧字段：优先使用 initial_demand，兼容旧的 pain_points/business_desc
    initial_demand = body.get("initial_demand", "")
    pain_points = body.get("pain_points", "")
    direction = body.get("direction", "")
    business_desc = body.get("business_desc", "")
    company_intro = body.get("company_intro", "")
    
    # 如果有 initial_demand，优先使用；否则合并旧字段
    if not initial_demand:
        initial_demand = f"{business_desc} {pain_points}".strip()

    # 构建知识库上下文
    context = build_context(industry, initial_demand or pain_points, direction or business_desc)

    # 组装用户prompt
    user_prompt = "## 客户信息\n"
    user_prompt += f"- 行业：{industry}\n"
    if company_intro:
        user_prompt += f"- 公司简介：{company_intro}\n"
    if initial_demand:
        user_prompt += f"- 客户初始需求表达：{initial_demand}\n"
    elif business_desc or pain_points:
        if business_desc:
            user_prompt += f"- 业务描述：{business_desc}\n"
        if pain_points:
            user_prompt += f"- 痛点/希望解决的问题：{pain_points}\n"
    if direction and direction != business_desc:
        user_prompt += f"- 需求方向：{direction}\n"

    if context["industry_knowledge"]:
        user_prompt += f"\n## 行业背景知识\n{context['industry_knowledge']}\n"
    if context["case_context"]:
        user_prompt += f"\n## 相关交付案例\n{context['case_context']}\n"
    if context["template_context"]:
        user_prompt += f"\n## 字段经验池参考\n{context['template_context']}\n"

    user_prompt += "\n请严格按PART1-PART3的结构输出调研准备材料。PART1和PART2要精简，PART3提问清单严格8个问题，每个问题用“[维度]”+ 一句话问题 + 小字备注格式。问题要短，备注给服务商提示行业参考、引导方向、常见工具选项。"

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
