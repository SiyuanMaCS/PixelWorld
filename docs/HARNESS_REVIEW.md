# PixelWorld 当前harness审核

2026-11-08，依据当前runner/media/interaction代码及已准备smoke输入核对。主接口为I2V，历史T2V与音频接口保留，但不是本轮新增实验范围。

## 结构

外层数据adapter只准备官方允许的首帧、文本或控制/历史；runner按指定model/provider/track新起用户已有的Codex或TRAE CLI。外部观察器记录输入快照、原始消息、图片、API usage、代码和候选；输出验证与官方eval在生成之后独立进行。SFT导出不会反馈给生成agent。

```text
run/
  input_snapshot/     初始提供文件的外部副本
  task_prompt.txt     实际送给CLI的stdin指令
  workspace/          被测agent工作区
    first_frame.png
    prompt.txt
    GENERATION_RULES.md
    artifact_io.py
    player_template.html
    task_spec.json    可选，任务/媒体规格
    .tmp/             初始为空
    generate.py       agent之后写出的程序
    pixels.npz        agent计算RGB，helper保存
    frames/           编号PNG
    inspection.png, transition_check.png, index.html
  logs/               原始事件、完整rollout、图片/blobs、usage
  trace/              已冻结候选、代码历史
  recording/          SFT候选事件与分析账本/索引
  run_manifest.json
```

模型配置、50k数字、评测视频、mask、得分和其他case代码不放进模型任务。CLI自身普通system/tool指令仍存在；同backend版本/config固定，不能称为空白system或跨CLI完全同系统。

## Agent说明

Text：

> Generate the RGB video requested in `prompt.txt`, following `GENERATION_RULES.md`. `first_frame.png` is available through local code and numeric RGB operations; it is not attached visually. Visual image tools are disabled. Choose your own approach.
> You must produce the required output artifacts before finishing.

Vision-Agent：

> Generate the RGB video requested in `prompt.txt`, following `GENERATION_RULES.md`. `first_frame.png` is attached visually. Visual image tools are available. Choose your own approach.
> You must produce the required output artifacts before finishing.

启用新token预算的默认任务另加：

> Aim for high-quality output while considering efficiency.

显式`task_file`实验覆盖保留其原文，不静默添加该句。两个默认track差异是图片附件/视觉工具；Text仍可用Python读取PNG数值并将统计打印为文字。

当前基础I2V规则：只使用first_frame/prompt，工作限本workspace；生成20张256×144 RGB、4FPS、5秒，frame00逐像素等于输入；必须写generate.py、运行它，并至少调用一次artifact_io.save，结束前必须存在必需输出产物；可用本地绘图、复制/变形、解析几何、法线/光照与数学运动；不使用外部AI生成器、学习权重、外部模拟/渲染引擎、参考未来、mask/score、memory、网络和其他agent；自主保存/检查/修改，无必需OBSERVATION/METHOD报告。

helper只保存模型算出的数组，生成uint32 0xRRGGBB张量、PNG、检查表和HTML；player只播放像素。两者不含场景运动算法或未来颜色预测。模型须自己完成场景分析与后续像素计算。

生成规则同时明确要求：`Keep generate.py runnable so it regenerates the submitted RGB video.` 即保留可重新运行、生成所提交RGB视频的程序；这是一项交付要求。若模型修订视频，每个修订候选也要先保存；同时避免没有明确改进目标的反复修订，保持效率。

## 不同任务怎样适配

基本I2V通常只改输入准备和task_spec：官方首帧、官方描述/控制、保持比例的预处理、输出宽高/帧数/FPS；共享Task、工具边界、helper与记录结构保留。动态rules仅代入尺寸/时间和允许输入列表。

接口变化另改少量通用语义：

- V2V允许合法历史MP4、帧与时间信息；只生成历史之后的预测，输出frame00为未来帧，不强制复制历史末帧。现有Verified全量V2V素材协议还未完整准备。
- 交互任务仍按单turn I2V生成，外层逐个发送当前动作；下一turn只收到上turn生成的最后PNG，不收到旧代码、参考视频或未来动作列表。预算每turn计，episode成本另汇总。
- 历史T2V接口不放首帧，所有帧从文本生成。当前主要研究I2V。

旧smoke实际准备的输出规格：

| 任务 | 合法输入形式 | 已做smoke规格 | 状态 |
|---|---|---|---|
| Physics-IQ | 官方首帧+BPP-base | 256×144，20帧/4FPS/5秒 | 已有完整官方eval |
| RoboJudge shared-50 | 首帧+原任务文本及固定机器人前缀 | 256×192，20帧/4FPS | I2V生成smoke，不当完整榜单 |
| WBench | 首帧+当前动作，逐turn末帧交接 | 256×143，20帧/4FPS，每turn5秒 | 旧四turnsmoke |
| WorldArena | 首帧+任务描述 | 256×192，121帧/24FPS | validation预览，低于推荐640×480 |
| WorldScore | 首帧+场景/风格+相机意图 | 256×175，50帧/10FPS | 单场景transition预览 |

这些不是所有benchmark的统一官方生成参数。正式运行必须核对完整官方输入与生成/评分协议、标明预处理偏离。Principia/PVBench目前只完成候选和资源核对，未固定正式输出秒数/FPS；不借用MORPHEUS样例2.7秒或把eval读取上限当生成长度。

task_spec允许task_type、width、height、frames、fps、audio以及benchmark/turn/action；不会接受gt轨迹/物理参数作为媒体字段。输出时长为frames/fps。模型不收到人为撰写的解题坐标、事件时间表或参考续帧；官方prompt本身明确的合法条件保留。

I2V首帧必须与输出帧宽高一致。若改变输出分辨率，当前准备器需要同时给出相应尺寸的首帧；“固定低分辨率输入、输出更大尺寸且首帧仍逐像素相同”不是只改task_spec就能实现的实验，需要另定义明确首帧约束。

## 预算、隔离和记录

50k是外部after-request阈值，跨请求/同case恢复attempt累计，不给模型数字；单请求可能overshoot并记录。截止后按时间保留此前最后合法候选，不按eval分数选择，不规定固定review轮数。无合法候选记预算失败；无实时用量支持记计数不可用。

workspace-write主要控制写和工具网络。外部读取还由任务契约和审计约束；它不是Docker式仅五文件可读的物理mount。初始文件/普通工具版本/CLI配置受控，旧日志缺失不解释成没调用工具。

原始CLI暴露内容与blobs保留，规范化SFT事件和API账本分开。隐藏未返回思考、未完成响应与未保存草稿不补造；快照观察器可能漏快速同名覆盖。旧v1与新v2条件、预览与正式协议、可见事件与模型自述都分别标记。
