# 华博士 · 科研仪器领域智能体

**从实验需求出发，让仪器建议有依据、知识更新有版本。**

An experimental scientific-instrument agent with workflow-aware retrieval, evidence-backed recommendations, and reviewed knowledge releases.

## 工程导航与迭代逻辑

[迭代复盘](docs/EVOLUTION.md) · [工程模块](docs/MODULES.md) · [设计取舍与实验计划](docs/ENGINEERING.md) · [个人 AI 工程作品集](https://github.com/2137183172-cyber)

项目演进按“问题 → 设计选择 → 验证与边界”记录。早期修改来自原项目记录，公开仓库保留真实的首次公开日期。

## 为什么做这个项目

一句“我要做这个实验”，往往还不足以选出合适的设备。样本类型、处理步骤、通量和自动化要求，都可能改变答案。华博士尝试把这些约束逐步问清楚，再把实验步骤、设备角色和资料依据连接起来。

我们希望公开讨论一个问题：**仪器选型 AI 应该什么时候继续追问，什么时候给出建议，什么时候承认资料不足？**

## 当前实现与边界

- Python / FastAPI 对话服务与 Web 界面。
- 领域需求解析、产品检索、Neo4j 图谱及本地数据回退相关实现。
- 场景—步骤—设备—证据关系，以及审核数据的版本标识。
- 公开输出过滤与资料不足处理相关实现。
- 公开版只提供 3 条虚构设备记录，不包含真实仪器型号、商业参数、内部报价、客户数据或原始厂商资料。

这是领域 Agent 工程的开发预览，**尚未发布训练后的专用模型权重**。具体模块效果需要在公开数据上继续评测；合成数据不能支持真实采购决策。

## 快速启动

需要 Python 3.11。

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

访问 http://127.0.0.1:8000 。未配置模型与 Neo4j 时，部分功能使用本地回退，部分功能不可用。将 `.env.example` 复制为 `.env` 后配置自己的服务。管理员功能通过 `ADMIN_PASSWORD` 配置，公开版没有固定管理密码。

演示查询：`介绍演示离心设备`。所有示例设备均为虚构；页面中来自原业务的场景目录未附带真实内容。

## 架构

```mermaid
flowchart LR
    A[实验需求] --> B[解析与追问]
    B --> C[产品与场景检索]
    C --> D[审核知识 / 图谱 / 本地回退]
    D --> E[依据与推荐说明]
    E --> F[公开字段过滤]
```

## 值得一起探索

1. **知识更新一致性**：产品资料和图谱如何保持同一版本？
2. **设备角色边界**：如何避免把辅助设备描述成能完成核心实验步骤？
3. **可检验的回答**：能否让每个关键结论都关联到支持它的证据？

这些是工程探索方向，不代表已证明优于其他系统。

## 路线图与参与入口

- [ ] 公开一组“需要追问 / 可以推荐 / 应当拒答”的合成基准。
- [ ] 比较直接 LLM、RAG、带流程约束检索的表现，并公布失败案例。
- [ ] 补齐公开演示场景、启动回归测试和完整依赖锁定。
- [ ] 数据条件成熟后，探索领域微调与模型卡。

欢迎提交一个会让系统选错设备的问题，或一个实验步骤与设备角色容易混淆的案例。参见 [贡献说明](CONTRIBUTING.md) 与 [公开版范围](docs/PUBLIC_EDITION.md)。

MIT License。依赖与第三方资料遵循各自许可。

## 同一条仪器生命周期

配套项目：[lab-repair-agent](https://github.com/2137183172-cyber/lab-repair-agent)。两个项目分别探索仪器选型与维修协作。

[验证记录](docs/VALIDATION.md) · [参与讨论](https://github.com/2137183172-cyber/huaboshi-instrument-agent/discussions)

[公开 Projects 看板：主项目、模块与下一步实验](https://github.com/users/2137183172-cyber/projects/1)
