# 可展示工程模块

这里展示公开仓库中的实现。它们共享领域数据和服务，不是独立发布的多个产品。

## 版本化知识与图谱

- 输入：审核产品与场景文件。
- 设计：稳定键、文件指纹、图谱 ready 状态和当前生效版本。
- 输出：可校验的关系计划与对应版本的图谱上下文。
- 源码：[reviewed_graph.py](../backend/reviewed_graph.py)。
- 边界：公开样例是合成数据，不能通过正式发布审核；完整真实 Neo4j 同步未在公开版联调。

## 实验步骤与设备角色

- 输入：需求描述、样本约束与场景步骤。
- 设计：区分核心、必选、辅助、替代、前置、下游和不兼容等关系。
- 输出：带角色和适用范围的场景/设备说明。
- 源码：[demand_profile.py](../backend/demand_profile.py)、[knowledge_catalog.py](../backend/knowledge_catalog.py)、[scenario_service.py](../backend/scenario_service.py)。
- 边界：这类结构约束不等于已经证明模型具有科学推理能力；原始场景数据没有公开。

## 确定性事实与公开输出

- 输入：已整理的事实与回答对象。
- 设计：显式事实字段、内部字段识别、递归输出过滤、空值保留。
- 输出：面向公开接口的可展示字段。
- 源码：[product_publication.py](../backend/product_publication.py)、[公开事实字段](../scripts/publish_reviewed_products.py)。
- 边界：字段过滤不替代完整系统安全审计；发布脚本在公开版仅保留字段定义。

## 证据驱动的渠道协作

- 输入：三方画像、需求、产品/应用标签和人工核验记录。
- 设计：确定性匹配理由、阶段前置条件、本机访问限制。
- 输出：候选匹配、待核实事项与协作进度。
- 源码：[channel_service.py](../backend/channel_service.py)、[precision_service.py](../backend/precision_service.py)、[growth_service.py](../backend/growth_service.py)。
- 本地入口：`/channels`、`/growth`，只使用本机地址和合成记录。
- 边界：不自动发送消息，不代表真实授权核验；不是三方远程生产门户，也不是已实现的自主销售 Agent。

建议顺序：先看 [迭代动因](EVOLUTION.md)，再看源码和 [验证范围](VALIDATION.md)。
