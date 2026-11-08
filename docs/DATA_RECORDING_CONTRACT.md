# PixelWorld 数据记录契约

版本：`pixelworld-recording-v1`。用途固定为 **agentic SFT候选轨迹** 与 **token/生成/修订分析**。原始档案是事实来源；规范化导出不覆盖原文、不生成未返回的思考或未保存的视频。

## 每条新run自动保存

```text
run/
├── input_snapshot/             # 模型运行前的首帧、prompt、规则、helpers及合法额外输入
├── task_prompt.txt             # 精确任务文本
├── workspace/                  # 模型工作区和最终产物
├── logs/
│   ├── events.raw.jsonl        # 原始CLI stdout
│   ├── events.jsonl            # 带外部时间戳的事件
│   ├── full_rollout.jsonl      # CLI公开的完整消息/工具历史
│   ├── rollout-blobs/          # 大内容正文，SHA校验
│   ├── tool_images/            # 实际返回图片
│   ├── token_usage.json
│   └── token_budget.json
├── trace/                      # 已冻结候选、代码历史、RGB/PNG与检查图
└── recording/
    ├── index.json              # 来源、模型/track、完整性、训练候选标记和文件索引
    ├── conversation_events.jsonl
    ├── api_usage.jsonl
    ├── candidates.jsonl
    └── media/                  # 规范化轨迹引用的已返回图片
```

输入快照与记录目录都在模型workspace外，不向模型反馈预算、分数、标签或旧结果。规则/工具的初始版本有SHA，避免后来模型修改工作文件后丢失训练输入。旧run没有初始快照时明确标记`legacy_workspace_fallback`。

## Agentic SFT出口

- 保留用户/开发者消息、assistant文字、工具调用的名字与原始参数格式、对应工具反馈以及图片资源。不是只保存最终代码。
- 工具调用区分freeform与JSON，保留call_id与native_type；工作目录规范化为`{WORKSPACE}`，原始路径与消息仍在私有raw档案。
- 保存API公开的reasoning内容/摘要。加密思考不作为训练target，不恢复未公开思考。
- `supervision_candidate`仅标明assistant文字与动作可以成为监督目标；工具环境反馈不默认作为模型生成目标。目标模型的chat template、工具schema和reasoning训练配方另行适配。
- `sft_full_trajectory_candidate`要求生成/审计通过、消息可解析、引用内容可恢复、调用与反馈配对完整、轨迹未被预算中断。失败或部分轨迹继续保存，可以用于分析或明确的前缀/负样本处理，但不混成完整正样本。
- 完整性不等于物理/视觉质量。默认`quality_review=unreviewed`、`source_split=unassigned`、`training_ready=false`；经质量选择和划分之后才用于训练。
- 保留benchmark/case/protocol与输入hash，区分评测来源。由评测条件生成的轨迹不得默默混成训练集，再把同一批当未见测试。

规范化事件是与训练框架无关的中间格式。它保留native工具类型和第一出现顺序、最新消息内容；精确的history mutation与实际上下文变化仍在raw档案，不能把中间格式误称为厂商隐藏上下文的完整复刻。

## 分析出口

- `api_usage.jsonl`保留API request id、时间、原始input/output/reasoning/cache usage和累计值。重复事件去重；不通过训练导出文本重新分词来计算预算。
- `usage_coverage`区分逐请求记录、累计观察、终端总量和missing。累计观察/终端记录不伪装成逐请求调用数。
- `candidates.jsonl`记录候选快照、时间、RGB和代码SHA、分辨率/FPS，以及当时已上报的usage水位。该水位不是独立的渲染完成成本。
- 首次、中间、最终状态和50k预算/overshoot可回溯。代码重执行、RGB变化和视觉检查分别分析，不将模型自述当工具证据。
- 中断、缺失、不可解析、未匹配调用和缺blob都明确标记。token缺失不按0处理。

## 记录边界

记录CLI/API已公开的内容；隐藏思考、未返回的响应尾部和未保存的内存草稿无法恢复。候选/代码观察器是采样记录，快速同名覆盖可能漏快照；当前不声称逐文件写入无遗漏。只对有证据的版本做修订分析。

所有生成数据只在本地/实验输出目录维护，不提交到代码仓库。当前实现不启动训练、不调用新的生成模型。

## 导出已有run

```bash
python -m pixelworld.cli export-records --run /path/to/run
```

该命令只读原run并建立`recording/`导出，不改变其生成结果、状态或模型上下文。新run在结束后自动执行同样的导出。
