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
        for word in re.split(r'[,,、。\s]+', query_lower):
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
        for word in re.split(r'[,,、。/\s+]+', scene):
            if len(word) >= 2 and word in query_lower:
                score += 3
        for word in re.split(r'[,,、。/\s::]+', applicable):
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

    # 1. 行业知识(完整传入)
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

        case_context += f"### 真实交付案例:{meta.get('industry', '')} - {meta.get('scene', '')}\n"
        case_context += f"客户规模:{meta.get('scale', '未知')}\n"

        # 客户痛点(学习客户会有什么疑问和需求)
        if pain:
            case_context += f"客户原始痛点:\n"
            for p in pain:
                case_context += f"  - {p}\n"

        # 方案架构
        if solution.get("architecture"):
            case_context += f"最终方案:{solution['architecture']}\n"

        # 完整的表结构和字段
        if tables:
            case_context += f"方案包含的子表和字段:\n"
            for t in tables[:6]:
                tname = t.get("table_name", "")
                purpose = t.get("purpose", "")
                usage_role = t.get("usage_role", "")
                fields = t.get("fields", [])
                case_context += f"  表「{tname}」({purpose})"
                if usage_role:
                    case_context += f" 使用者:{usage_role}"
                case_context += "\n"
                if fields:
                    # fields可能是字符串列表或dict列表
                    field_names = []
                    for f in fields[:15]:
                        if isinstance(f, str):
                            field_names.append(f)
                        elif isinstance(f, dict):
                            field_names.append(f.get("field_title", f.get("title", "")))
                    case_context += f"    字段:{', '.join(field_names)}\n"

        # 自动化规则(帮助AI知道该问什么自动化需求)
        auto_rules = solution.get("automation_rules", [])
        if not auto_rules:
            auto_rules = case.get("automation_rules", [])
        if auto_rules:
            case_context += f"配置的自动化规则:\n"
            for r in auto_rules[:5]:
                case_context += f"  - {r}\n"

        # 服务商沟通记录(学习如何提问)
        if comm_record:
            case_context += f"服务商与客户沟通记录:\n  {comm_record}\n"

        # 沟通亮点(学习服务商确认了哪些关键信息)
        if comm_highlights:
            case_context += f"沟通中确认的关键信息点(服务商在实际调研中需要弄清楚的):\n"
            for h in comm_highlights:
                case_context += f"  - {h}\n"

        # 交付描述
        if delivery_desc:
            desc = delivery_desc[:300] if len(delivery_desc) > 300 else delivery_desc
            case_context += f"交付说明:{desc}\n"

        case_context += "\n"

    # 如果精确匹配的案例没有沟通记录,补充一些有沟通记录的案例作为提问方式参考
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
                comm_examples += f"参考案例({meta.get('industry','')}-{meta.get('scene','')[:20]})中服务商确认的信息点:\n"
                if cr:
                    comm_examples += f"  沟通记录:{cr[:200]}\n"
                for h in ch[:6]:
                    comm_examples += f"  - {h}\n"
                comm_examples += "\n"
                if len(comm_examples) > 1500:
                    break
        if comm_examples:
            case_context += "\n### 其他行业的服务商提问参考(学习提问深度和方式)\n" + comm_examples

    # 3. 字段模板(完整传入字段细节)
    matched_tpl = match_field_template(query, field_templates)
    tpl_context = ""
    if matched_tpl:
        meta = matched_tpl.get("meta", {})
        tpl_context = f"### 字段经验池:{meta.get('industry', '')} - {meta.get('scene', '')}\n"
        tpl_context += f"该行业真实交付过{meta.get('total_tables', '?')}张表,{meta.get('total_fields', '?')}个字段\n"
        if meta.get("design_principle"):
            tpl_context += f"设计原则:{meta['design_principle']}\n"
        tpl_context += f"你需要据此判断该行业需要调研的方面:\n"
        for table in matched_tpl.get("tables", [])[:8]:
            tpl_context += f"  表「{table.get('table_name', '')}」"
            if table.get("description"):
                tpl_context += f"({table['description']})"
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

你的任务:根据客户行业和初始需求,为服务商输出一份**简洁清晰**的调研准备材料。

## ⚠️ 核心原则
- 问题要短,一句话能说清就不写两句
- 像面对面聊天,不要书面语
- 整体排版清爽,服务商一眼看清该问什么
- 不要在各部分之间加横线(---)

## 输出结构(严格3个部分,不要开场白/结尾总结,不要加横线分隔)

### PART1: 客户画像

**公司与需求背景**

先用一段自然的话介绍这家公司(基于客户提供的公司名称和行业信息,结合你对该行业的认知去描述):这家公司是做什么的、大概什么规模、主营业务是什么、客户群体是谁。写得像一个了解这个行业的人在给服务商介绍客户一样,不要像填表。

然后用几个要点补充服务商需要提前了解的信息:
- 这个行业目前的情况(市场环境、竞争压力、数字化程度等)
- 这个业务场景一般涉及哪些角色、哪些环节
- 客户这次的需求可能属于哪个业务板块
- 做这类项目需要考虑什么(基于行业经验)

❗ 重要:这段内容的目的是让服务商在联系客户前就对客户有基本了解,不要写得像填表或列清单。要像一个有经验的人在给你介绍情况一样自然。

**行业常见痛点**
- 🔥 痛点1
- 🔥 痛点2
- 🔥 痛点3

### PART2: 信息缺口

客户描述中明显缺失的关键信息,列3-5条,每条一句话:
- ❓ 缺失点

### PART3: 提问清单

❗❗❗ 这部分分为两个表格:「必问问题」和「深挖问题」

**必问问题**（严格11个）

| 序号 | 维度 | 提问 |
|------|------|------|
| 1 | 痛点收敛 | 问题正文(一句话)<br>*行业常见情况描述。可以进一步问客户:"XXX?""YYY?"* |
| 2 | 业务流程 | 问题正文(一句话)<br>*行业常见情况描述。可以进一步问客户:"XXX?""YYY?"* |
| ... | ... | ... |

**深挖问题**(可选3-5个,服务商想深入了解时使用)

| 序号 | 维度 | 提问 |
|------|------|------|
| 1 | 某维度 | 问题正文(一句话)<br>*行业常见情况描述。可以进一步问客户:"XXX?""YYY?"* |
| ... | ... | ... |

注意:每行的"提问"列内容格式两个表格相同:
- 第一行:问题正文(简短定性,一句话)
- 第二行(用 <br> 换行):*斜体小字*,先说行业常见情况,再说可以进一步问客户什么
- ❗不要出现"话术参考:""可追问:"这种前缀标签,直接写内容

## 提问维度(必问11个 + 深挖可邉3-5个)

**必问问题维度(严格11个):**

| # | 维度 | 核心意图 |
|---|------|----------|
| 1 | 痛点收敛 | 哪个环节最头疼/最常出错/最花时间?收敛为P0、P1、P2 |
| 2 | 业务流转+角色 | 围绕痛点的业务链流程,流程上有哪些角色/部门/外部方 |
| 3 | 现状工具链+瓶颈 | 现在用什么工具,为什么无法解决问题(这决定了新方案要规避的坑) |
| 4 | 数据现状 | 数据来源、存储位置、数量级、更新频次 |
| 5 | 自动化诉求 | 希望自动化实现什么、在什么场景下触发 |
| 6 | 数据接入方式 | 数据进入新表格的方式(手动录入/系统打通同步/导入/表单填报) |
| 7 | 使用者清单 | 谁来用智能表格,是否有外部人(客户、经销商、供应商) |
| 8 | 权限隔离 | 数据是否要隔离(如A销售只看自己的客户,B部门只看自己的数据) |
| 9 | 仪表盘 | 希望重点展示什么业务指标,以什么维度展示 |
| 10 | 交付预期 | 期望上线时间、上线节奏、预算范围 |
| 11 | 开放补充 | 还有什么想补充的 |

**深挖问题维度(可选3-5个,必须与智能表格交付相关):**
- 字段细节(某个环节需要记录哪些字段)
- 关联关系(表与表之间的关联,如订单关联客户、关联产品)
- 流转规则(什么条件下数据流转到下一步,是否要审批)
- 通知规则(什么情况下通知谁、通过什么方式)
- 数据迁移(现有数据是否需要导入、格式是否统一)
- 多表协同(是否需要多张表联动,如订单表+库存表+客户表)

## 提问规则

**必问问题:**
1. 严格11个问题,不多不少
2. 问题正文必须**简短定性**(一句话),用大白话,像聊天一样
3. 问题必须结合客户的行业特点来设计,不能泛泛地问
4. 每个问题后用 <br> 换行,紧跟 *斜体小字*,内容结构:
   - 先说行业常见情况(如"该行业常见痛点是XXX""典型流程是XXX")
   - 再说可以进一步问客户什么(直接写问句,不要加"话术参考:""可追问:"等前缀)
   - 如有常见选项,直接列举
5. 参考知识库中的案例和字段经验池

**深挖问题:**
1. 3-5个问题,是服务商想更深入了解时可以问的
2. 格式要求和必问问题完全一样(表格 + 斜体小字)
3. 内容必须与智能表格交付相关:字段细节、表间关联、流转规则、通知规则、数据迁移、多表协同等
4. 不要和必问问题重复,要是更深入一层的内容
5. 不要出现跟智能表格交付无关的问题(如团队管理、商业模式等)

## 输出格式示例(仅示意,实际内容需结合客户行业)

### PART1: 客户画像

**公司与需求背景**

XX公司是一家专做欧美市场女装出口的外贸企业,主要业务是接海外客户订单然后分发给国内多家工厂生产。团队规樠大概在几十人,业务员负责对接客户和跟单,这次主要是想解决订单管理和多工厂协同的问题。

- 服装外贸行业目前竞争激烈,客户订单小单快反趋势明显,对交付效率和跟单精细度要求越来越高
- 这个场景一般涉及:业务员、设计师、工厂联系人、货代;环节包括接单→打样→确认→排产→质检→发货
- 客户这次需求属于订单管理+生产协同板块,核心是解决从接单到交货的全流程跟踪
- 做这类项目需要考虑:多工厂分单的协同机制、交期预警、外部协作方权限控制、历史订单数据迁移

**行业常见痛点**
- 🔥 订单状态分散在微信群和Excel,无法实时查看进度
- 🔥 多工厂分单后信息同步滞后,导致交期延误
- 🔥 样品确认流程繁琐,客户反复修改无记录

### PART2: 信息缺口

- ❓ 未说明目前管理订单用什么工具
- ❓ 未描述团队规模和分工方式
- ❓ 未说明是否有外部协作方需要查看数据

### PART3: 提问清单

**必问问题**

| 序号 | 维度 | 提问 |
|------|------|------|
| 1 | 痛点收敛 | 目前哪个环节最让你头疼、最常出错或最花时间?<br>*服装外贸常见痛点:订单变更后生产计划调整不及时、多工厂分单信息同步滞后、样品确认反复无记录。"哪个步骤经常卡住?""有没有因信息没同步导致返工或客诉?"* |
| 2 | 业务流转+角色 | 一个订单从接单到交货,中间经过哪些环节和人?<br>*服装外贸典型流程:接单→打样→确认→生产→质检→发货,涉及业务员、设计、工厂、货代。"每个环节谁推进?信息怎么传?哪里容易断?"* |
| 3 | 现状工具链+瓶颈 | 现在用什么工具管,为什么觉得不够用?<br>*服装外贸常见工具:Excel、微信群、ERP(用友/金蝶)、丝路通。"是功能缺、太复杂没人用、还是数据打不通?""为什么现有工具解决不了这个问题?"* |
| 4 | 数据现状 | 相关数据现在存在哪里?大概多少条?多久更新一次?<br>*服装外贸企业数据通常分散在各业务员电脑和微信聊天中。"是每个人各管各的还是有统一地方?每天都有新数据还是周期性的?"* |
| 5 | 自动化诉求 | 有没有希望系统自动帮你做的事?在什么场景下触发?<br>*服装外贸常见自动化:订单状态变更自动通知、交货期临近提醒、生产进度自动汇总。"具体在什么条件下触发?触发后希望做什么?"* |
| 6 | 数据接入方式 | 数据怎么进到新表格里?<br>*常见方式:手动录入、表单填报、从现有系统自动同步、定期导入Excel。"是希望和现有系统打通自动同步,还是人工录入就行?"* |
| 7 | 使用者清单 | 谁来用这个表格?有没有外部人也要用?<br>*服装外贸常有外部协作方(工厂、货代、客户)需要查看或填写。"除了内部同事,工厂/客户/经销商需要看或填吗?"* |
| 8 | 权限隔离 | 数据需要按什么维度隔离?<br>*常见隔离方式:按人(销售只看自己的客户)、按部门、按区域、按角色。"具体谁不能看到谁的数据?"* |
| 9 | 仪表盘 | 最想看到什么业务指标?希望以什么维度展示?<br>*服装外贸常见指标:订单完成率、交货准时率、各工厂在制量、客户返单率。常见维度:按时间/按工厂/按业务员。"老板最关心哪个数字?"* |
| 10 | 交付预期 | 希望多久能用上?先上哪部分?预算大概多少?<br>*服装外贸客户通常希望1-2周内看到初版。"是一次性全部上线还是分阶段?有没有硬性时间节点?"* |
| 11 | 开放补充 | 还有什么想补充的吗?<br>*开放性问题,让客户补充前面没覆盖到的需求或顾虑。* |

**深挖问题**

| 序号 | 维度 | 提问 |
|------|------|------|
| 1 | 字段细节 | 核心环节需要记录哪些信息?<br>*服装外贸订单常见字段:客户名、款号、数量、交期、工厂、状态、备注。"每个环节需要填哪些信息?现在的表里有哪些列?"* |
| 2 | 表间关联 | 订单需不需要关联其他信息(客户、产品、工厂)?<br>*服装外贸常见关联:订单⇄客户、订单⇄款号/产品、订单⇄工厂。"是否需要分表管理还是全在一张表里?"* |
| 3 | 流转规则 | 数据从一个状态到下一个状态,有什么条件吗?<br>*服装外贸常见流转:客户确认后才能排产、质检通过才能发货。"是否需要审批?谁来审批?"* |
| 4 | 通知规则 | 什么情况下需要自动通知谁?<br>*服装外贸常见通知:交期临近提醒业务员、客户确认后通知工厂、异常告警通知主管。"通过企微消息还是其他方式?"* |

❗❗❗ 重要:以上是示例,实际输出必须根据客户的具体行业和需求来写,不要照抄示例。
"""


def generate_question_list(body):
    """返回知识库上下文和prompt,前端直接调DeepSeek"""
    industry = body.get("industry", "")
    # 支持新旧字段:优先使用 initial_demand,兼容旧的 pain_points/business_desc
    initial_demand = body.get("initial_demand", "")
    pain_points = body.get("pain_points", "")
    direction = body.get("direction", "")
    business_desc = body.get("business_desc", "")
    company_intro = body.get("company_intro", "")

    # 如果有 initial_demand,优先使用;否则合并旧字段
    if not initial_demand:
        initial_demand = f"{business_desc} {pain_points}".strip()

    # 构建知识库上下文
    context = build_context(industry, initial_demand or pain_points, direction or business_desc)

    # 组装用户prompt
    user_prompt = "## 客户信息\n"
    user_prompt += f"- 行业:{industry}\n"
    if company_intro:
        user_prompt += f"- 公司简介:{company_intro}\n"
    if initial_demand:
        user_prompt += f"- 客户初始需求表达:{initial_demand}\n"
    elif business_desc or pain_points:
        if business_desc:
            user_prompt += f"- 业务描述:{business_desc}\n"
        if pain_points:
            user_prompt += f"- 痛点/希望解决的问题:{pain_points}\n"
    if direction and direction != business_desc:
        user_prompt += f"- 需求方向:{direction}\n"

    if context["industry_knowledge"]:
        user_prompt += f"\n## 行业背景知识\n{context['industry_knowledge']}\n"
    if context["case_context"]:
        user_prompt += f"\n## 相关交付案例\n{context['case_context']}\n"
    if context["template_context"]:
        user_prompt += f"\n## 字段经验池参考\n{context['template_context']}\n"

    user_prompt += "\n请严格按PART1-PART3的结构输出调研准备材料。PART1公司背景要先用一段自然的话介绍这家公司(基于客户提供的信息和你对该行业的认知来描述,像给服务商介绍客户一样,不要像填表),然后用几个要点补充行业现状、涉及角色和环节、需要考虑的事项。PART2简洁。PART3提问清单严格11个必问问题+3-5个深挖问题,用Markdown表格格式(序号|维度|提问),每个问题后用<br>换行加斜体小字(先说行业常见情况,再给追问句子,不要加任何前缀标签)。"

    # 返回prompt供前端直接调DeepSeek(无超时限制)
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
