# 视频自动化发布流程方案

## 目标

通过飞书多维表格管理视频文案，实现：
1. 文案自动读取
2. 视频自动生成（闪剪）
3. 视频号自动发布
4. 全流程状态可追踪
5. 飞书通知

---

## 一、多维表格结构

**表格**：`视频号发布记录`
**Base Token**：`XX8abIKw7a9GwBsVt57crlbHnOe`
**Table ID**：`tblHptO4dDJckuFF`
**folder-token**：`O1gkfkkv9l3xtpdKUUwcCIunnMb`（新媒体运营文件夹，飞书云盘）

### 字段定义

| 字段名 | 类型 | 说明 |
|--------|------|------|
| 视频标题 | text | 视频短标题 |
| 文案内容 | text | 视频配音文案 |
| 视频描述 | text | 视频号发布页的描述（含话题标签） |
| 视频文件路径 | text | 本地视频文件路径 |
| 视频链接 | text | 飞书云盘预览链接 |
| 视频号链接 | text | 发布后填入 |
| 发布状态 | select | 见下方完整选项 |
| 发布时间 | datetime | 实际发布时间 |
| 视频类型 | select | 日报/周报/月报/专题 |
| 原创标志 | select | 是/否 |
| 视频标签 | text | 话题标签（逗号分隔） |
| 错误信息 | text | 失败时记录具体错误 |
| 创建时间 | datetime | |
| 归档时间 | datetime | |
| 归档天数 | number | |
| 下架时间 | datetime | |
| 下架操作时间 | datetime | |
| 文件大小MB | number | |

### 发布状态完整选项

```
草稿 → 待制作 → 制作中 → 待下载 → 下载中 → 待发布 → 发布中 → 已发布
                                                          ↓
                                              生成失败 / 下载失败
                                              发布失败 / 上传失败
                                                          ↓
已归档
```

---

## 二、模块架构

```
video_factory/
├── update_status.py          # 统一状态更新工具（所有模块调用）
├── selectors.json            # DOM 选择器配置（版本化，不硬编码）
├── shanjian_make.py          # 闪剪模块：做同款 → 导出 → 下载
├── video_publish.py          # 视频号模块：上传 → 填表 → 发布
├── workflow_runner.py        # 串起多个模块（可选）
├── cron_publish.py           # 定时调度（调用各模块）
└── PLAN-video-workflow.md    # 本方案文档
```

### 设计原则

- **每个模块可独立运行**：单独调闪剪、单独发视频号
- **关键节点必须更新状态**：失败时写错误信息到表格
- **不合并流程**：闪剪和视频号是两个独立动作，分别追踪状态

---

## 三、发布状态节点定义

### 3.1 闪剪模块（shanjian_make.py）

| 节点 | 状态 | 触发时机 |
|------|------|----------|
| 开始处理 | `制作中` | 从表格取到「待制作」记录，开始操作闪剪 |
| 导出渲染成功 | `待下载` | 点完「导出视频」按钮，渲染任务提交到闪剪云端 |
| 下载完成 | `待发布` | 视频文件写入本地磁盘，视频文件路径写入表格 |

### 3.2 视频号模块（video_publish.py）

| 节点 | 状态 | 触发时机 |
|------|------|----------|
| 开始处理 | `发布中` | 从表格取到「待发布」记录，开始操作视频号后台 |
| 发布成功 | `已发布` | 点发布后页面跳转到视频号已发布列表；发布时间、视频号链接写入表格 |
| 发布失败 | `发布失败` | 点发布后出现错误提示；错误信息写入表格 |

### 3.3 失败处理

每个模块任何节点失败时：
- 状态更新为对应的失败状态（如「生成失败」「发布失败」）
- 错误信息写入「错误信息」字段（记录具体报错）
- 不影响其他记录的处理

### 3.4 错误场景覆盖（所有崩溃点必须捕获）

**闪剪模块错误处理：**

| 错误场景 | 处理方式 |
|----------|----------|
| 模板匹配失败（找不到卡片） | 写「生成失败」+ 错误信息（包含匹配的关键字） |
| 做同款按钮点击失败（超时） | 重试 3 次，再失败写「生成失败」 |
| 编辑器窗口未打开（超时 30s） | 写「生成失败」+ 错误信息 |
| 渲染超时（5 分钟无新视频） | 写「生成失败」+ 错误信息 |
| 下载链接捕获失败 | 写「下载失败」+ 错误信息 |
| curl 下载失败 | 重试 3 次，再失败写「下载失败」 |

**视频号模块错误处理：**

| 错误场景 | 处理方式 |
|----------|----------|
| 视频上传失败（文件过大/格式不对） | 写「上传失败」+ 错误信息 |
| Shadow DOM 选择器失效 | 写「发布失败」+ 具体选择器名称 |
| 发布按钮点击无响应（超时） | 重试 3 次，再失败写「发布失败」 |
| 发布后页面未跳转（假成功） | 加 URL 校验，失败写「发布失败」 |
| 飞书云盘上传失败 | 重试 3 次，不阻塞发布流程，只记录到错误信息 |

**try-except 原则：** 所有外部调用（lark-cli、curl、Playwright）必须包在 try-except 中，except 分支执行状态更新 + 错误信息写入，不允许裸崩溃。

---

## 四、闪剪模块（shanjian_make.py）

### 4.1 功能

- 输入：record_id（从表格读取）
- 输出：本地 MP4 文件路径写入表格「视频文件路径」字段

### 4.2 核心参数

| 参数 | 值 |
|------|-----|
| Cookie 文件 | `~/.video_factory/shanjian_cookies.json` |
| 模板匹配 | 按「视频标题」关键字匹配作品列表中的模板 |
| 下载输出目录 | `~/Videos/` |

### 4.3 执行流程

```
输入 record_id
    ↓
从表格读取：视频标题、文案内容、视频类型
    ↓
发布状态 → 制作中
    ↓
滚动到目标模板卡片（scrollIntoView）
    ↓
hover 卡片，显示「做同款」按钮
    ↓
点击「做同款」（button.lt-button:has-text("做同款")）
    ↓
等待编辑器新窗口打开（doc.shanjian.tv）
    ↓
[节点A] 发布状态 → 制作中（已在上面设置）
    ↓
滚动到水印文字，双击选中 → keyboard.type(新水印)
    ↓
右侧正文框填入文案内容
    ↓
点击「确认」进入编辑器
    ↓
点击「导出视频」
    ↓
[节点B] 发布状态 → 待下载（渲染任务已提交）
    ↓
等待渲染完成（轮询作品列表，新视频出现）
    ↓
hover 最新作品，显示下载按钮
    ↓
点击下载，捕获 MP4 URL
    ↓
curl 下载到 ~/Videos/{视频标题}.mp4
    ↓
[节点C] 发布状态 → 待发布
        视频文件路径 → 写入表格
    ↓
完成
```

### 4.4 关键 DOM 选择器（2026-04-25 验证）

选择器写入 `selectors.json` 配置文件，不硬编码在代码中。

**selectors.json 结构：**
```json
{
  "version": "2026-04-25",
  "shanjian": {
    "work_card": "[class*=\"_item_\"]",
    "make_same_btn": "button.lt-button:has-text(\"做同款\")",
    "watermark_p": "p",
    "rich_text_editor": "[class*=\"_rich-text_1a7l5_4\"]",
    "export_btn": "button:has-text(\"导出视频\")",
    "download_btn": "i[class*=\"Mywork-Download\"]"
  },
  "wechat": {
    "upload_input": "input[type=\"file\"]",
    "title_input": "input[placeholder*=\"概括视频\"]",
    "desc_editor": "div[contenteditable=\"true\"][data-placeholder=\"添加描述\"]",
    "publish_btn": "text=直接发表",
    "success_popup": "text=我知道了"
  }
}
```

**版本机制：** 每次 DOM 变化，更新 `version` 字段，代码启动时校验版本号，不匹配则报警。

### 4.5 水印修改方法（波哥亲授）

```
1. mouse.dblclick(x, y) → 双击触发文字全选
2. keyboard.type('新水印文字') → 打字替换选中文字
3. mouse.click(空白区域) → 点击画板保存
```

⚠️ **关键**：必须先 scrollIntoView 把卡片滚动到 viewport 内再 hover。

---

## 五、视频号模块（video_publish.py）

### 5.1 功能

- 输入：record_id（从表格读取）
- 输出：视频号链接写入表格「视频号链接」字段

### 5.2 核心参数

| 参数 | 值 |
|------|-----|
| Cookie 文件 | `~/.video_factory/video_account_state.json` |
| 发布页面 | `https://channels.weixin.qq.com/platform/post/create` |
| 发布后跳转 | `https://channels.weixin.qq.com/platform/` |

### 5.3 执行流程

```
输入 record_id
    ↓
从表格读取：视频标题（去换行）、视频描述、视频合集、原创标志
    ↓
发布状态 → 发布中
    ↓
打开 Chrome，进入发布页面
    ↓
上传视频文件（input[type=file]）
    ↓
等待「直接发表」按钮出现
    ↓
[节点A] 发布状态 → 发布中（已在上面设置）
    ↓
填视频标题（input placeholder 包含"概括视频"）
    ↓
填视频描述（div[contenteditable][data-placeholder="添加描述"]）
    ↓
选合集（如有）
    ↓
原创声明（默认勾选）
    ↓
截图保存 /tmp/publish_ready.png
    ↓
上传截图到飞书云盘（folder-token: O1gkfkkv9l3xtpdKUUwcCIunnMb）
    ↓
发送链接到波哥飞书（ou_3fd64a876310d0ce01c08f6248814463）
    ↓
[调试阶段] 停在发布按钮前，等波哥确认
    ↓
[正式上线] 直接点发布
    ↓
等待页面跳转，检测发布成功
    ↓
[节点B] 发布状态 → 已发布
        发布时间 → 当前时间
        视频号链接 → 当前 URL
    ↓
上传视频到飞书云盘
    ↓
发送发布成功通知到飞书群
    ↓
完成
```

### 5.4 字段映射（表格 → 视频号页面）

| 表格字段 | 视频号页面元素 |
|----------|----------------|
| 视频文件路径 | 上传按钮 → input[type=file] |
| 视频标题（去\n） | 短标题 input（placeholder 包含"概括视频"） |
| 视频描述 | 描述 div（contenteditable=true，placeholder="添加描述"） |
| 视频合集 | 合集选择框 |
| 原创标志（默认"是"） | 原创声明 checkbox |

### 5.5 视频号字段选择器

| 元素 | 选择器 | 填写方式 |
|------|--------|----------|
| 上传按钮 | `input[type="file"]` | set_input_files(path) |
| 短标题 | shadow-dom 内 input（placeholder 包含"概括视频"） | 原型链 set.call + dispatchEvent |
| 视频描述 | shadow-dom 内 div（contenteditable=true，data-placeholder="添加描述"） | textContent + dispatchEvent |
| 发表按钮 | shadow-dom 内 text="直接发表" | JS click |
| 发表成功弹窗 | shadow-dom 内 text="我知道了" | JS click |

---

## 六、统一状态更新工具（update_status.py）

### 6.1 函数签名

```python
def update_status(record_id: str, status: str, extra_fields: dict = None, error: str = None):
    """
    更新记录状态
    
    record_id: 记录ID
    status: 目标状态（见发布状态选项）
    extra_fields: 额外要更新的字段（dict）
    error: 错误信息（传入则写入选错误信息字段）
    """
```

### 6.2 状态常量

```python
STATUS_DRAFT = "草稿"
STATUS_PENDING_MAKE = "待制作"
STATUS_MAKING = "制作中"
STATUS_PENDING_DOWNLOAD = "待下载"
STATUS_DOWNLOADING = "下载中"
STATUS_PENDING_PUBLISH = "待发布"
STATUS_PUBLISHING = "发布中"
STATUS_PUBLISHED = "已发布"
STATUS_FAILED_MAKE = "生成失败"
STATUS_FAILED_DOWNLOAD = "下载失败"
STATUS_FAILED_PUBLISH = "发布失败"
STATUS_ARCHIVED = "已归档"
```

### 6.3 使用方式

```python
from update_status import update_status, STATUS_MAKING, STATUS_PENDING_DOWNLOAD

# 闪剪开始
update_status(record_id, STATUS_MAKING)

# 导出渲染成功
update_status(record_id, STATUS_PENDING_DOWNLOAD)

# 下载完成
update_status(record_id, STATUS_PENDING_PUBLISH, {"视频文件路径": "/Users/sam/Videos/xxx.mp4"})
```

---

## 七、工作流串接（workflow_runner.py）

将闪剪和视频号模块串起：

```
待制作记录
    ↓
shanjian_make.py → 闪剪生成视频 → 待发布
    ↓
video_publish.py → 视频号发布 → 已发布
    ↓
上传飞书云盘 → 发通知
```

每个环节记录详细日志，失败时停止并报告。

---

## 八、飞书通知

### 8.1 通知接收人

| 用途 | 接收人 | open_id |
|------|--------|---------|
| 视频号待确认 | 波哥 | ou_3fd64a876310d0ce01c08f6248814463 |
| 发布成功通知 | 团队工作报告群 | oc_e8b467f584d247feb1f6bf63bbe33d66 |

### 8.2 通知内容格式

**调试阶段（截图确认）**：
```
🎬 视频已生成，待发布确认

📺 标题：{视频标题}
📁 预览截图：{飞书云盘截图链接}

请确认后回复"可以发了"，将自动发布到视频号。
```

**正式发布成功**：
```
🎉 视频已发布！

📺 标题：{视频标题}
🔗 视频号：{视频号链接}
👀 预览：{飞书云盘链接}
```

---

## 九、执行计划

### 阶段一：基础设施

| 步骤 | 内容 | 依赖 | 状态 |
|------|------|------|------|
| 1.1 | 编写 `update_status.py`（统一状态更新工具 + 状态常量） | — | ⬜ |
| 1.2 | `update_status.py` 单独测试（mock 记录验证状态写入正确） | 1.1 | ⬜ |
| 1.3 | 创建 `selectors.json`（闪剪 + 视频号选择器配置 + 版本号） | — | ⬜ |
| 1.4 | `selectors.json` 加载 + 版本校验代码（各模块共用） | 1.3 | ⬜ |

### 阶段二：闪剪模块

| 步骤 | 内容 | 依赖 | 状态 |
|------|------|------|------|
| 2.1 | 改造 `shanjian_make.py`：接入 `update_status.py` + `selectors.json`，关键节点更新状态，所有外部调用包 try-except | 1.2, 1.4 | ⬜ |
| 2.2 | `shanjian_make.py` 单独测试（跑完闪剪全流程，验证表格状态从「待制作」→「待发布」，验证错误场景写入「生成失败」） | 2.1 | ⬜ |

### 阶段三：视频号模块

| 步骤 | 内容 | 依赖 | 状态 |
|------|------|------|------|
| 3.1 | 改造 `video_publish.py`：接入 `update_status.py` + `selectors.json`，关键节点更新状态，所有外部调用包 try-except | 1.2, 1.4 | ⬜ |
| 3.2 | `video_publish.py` 单独测试（跑完视频号全流程，验证表格状态从「待发布」→「已发布」，验证错误场景写入「发布失败」） | 3.1 | ⬜ |

### 阶段四：联调

| 步骤 | 内容 | 依赖 | 状态 |
|------|------|------|------|
| 4.1 | 编写 `workflow_runner.py`（串接闪剪→视频号全流程） | 2.2, 3.2 | ⬜ |
| 4.2 | 全流程联调（从「待制作」到「已发布」，验证完整状态流转） | 4.1 | ⬜ |

### 阶段五：上线

| 步骤 | 内容 | 依赖 | 状态 |
|------|------|------|------|
| 5.1 | 配置 cron 定时任务 | 4.2 | ⬜ |
| 5.2 | 去掉调试阶段的截图确认逻辑（改为全自动发布） | 4.2 | ⬜ |

---

### 执行原则

1. **每步只做一件事**：写完 `update_status.py` 单独测试，再写 `shanjian_make.py`
2. **每个模块可独立运行**：闪剪和视频号分别调通，再串起来
3. **失败立即停**：某步报错不继续，修复后再跑
4. **状态更新不过跳**：「制作中」之后才能是「待下载」，依此类推
5. **所有外部调用必须包 try-except**：lark-cli、curl、Playwright 都不允许裸崩溃
6. **选择器不硬编码**：统一从 `selectors.json` 读取，版本不匹配报警

---

## 十、风险与注意事项

1. **闪剪 Cookie 有效期**：`token` 过期后需重新导出，建议定期检查
2. **视频号 Cookie 有效期**：`video_account_state.json` 过期后需重新扫码
3. **闪剪渲染时间**：约 1-3 分钟，轮询间隔建议 30 秒
4. **视频号上传**：大文件耗时，wait_for_function 超时设 5 分钟
5. **状态不跳跃**：每个关键节点必须单独更新，不允许跳状态
6. **错误信息记录**：任何失败都要写具体错误，方便排查

---

## GSTACK REVIEW REPORT

### Phase 1: CEO Review (SELECTIVE EXPANSION mode)

#### 0A: Premise Challenge

| # | 前提 | 评估 | 风险 |
|---|------|------|------|
| P1 | 闪剪视频生成完全自动化 | ⚠️ 部分成立 | 渲染+下载可自动，但模板匹配依赖「视频标题」关键字，若标题变化可能匹配失败 |
| P2 | 视频号发布可自动完成 | ⚠️ 部分成立 | 上传+填表可自动，但发布按钮调试阶段需人工确认（波哥要求） |
| P3 | 飞书多维表格是状态管理最优解 | ✅ 合理 | 已有 lark-cli 工具，状态字段天然适合 select 类型 |
| P4 | 状态粒度「关键节点」足够用 | ✅ 成立 | 波哥确认：失败后需手动重做的步骤才算关键节点，这个标准清晰 |
| P5 | 闪剪和视频号应该独立模块 | ✅ 成立 | 独立则调试灵活，合并则调用简单，按波哥要求独立更好 |

**关键风险**：P1/P2 的「部分成立」意味着上线后仍可能有卡点，特别是闪剪 DOM 结构变化时的模板匹配失败。

#### 0B: What Already Exists

| 子问题 | 现有代码 | 位置 |
|--------|----------|------|
| 定时调度 | `cron_publish.py` | `/Users/sam/video_factory/cron_publish.py` |
| 闪剪自动化 | `shanjian_v2.py` | `/Users/sam/video_factory/` (未找到，见 PLAN) |
| 视频号发布 | `publish_real.py` | `/Users/sam/video_factory/` (见 PLAN) |
| 飞书表格读写 | `lark-cli` | 系统已配置 |
| 截图上传 | `lark-cli drive +upload` | 已有能力 |

#### 0C: Dream State

```
CURRENT: 手动登录闪剪 → 手动生成视频 → 手动上传视频号
    ↓
THIS PLAN: update_status + shanjian_make + video_publish + workflow_runner
    ↓
12-MONTH IDEAL: 每日自动生成发布，波哥只负责审核已发布的视频链接
```

#### 0D: Mode Selection — SELECTIVE EXPANSION

选择「保持范围 + 精选扩展」，因为：
- 核心流程已清晰，不需大扩张
- 有两个可以提升完整性的扩展点（见下方）

#### 0E: Temporal Interrogation

| 时间点 | 预期行为 |
|--------|----------|
| HOUR 1 | update_status.py 写完，mock 测试通过 |
| HOUR 2 | shanjian_make.py 改造完成，单独跑通 |
| HOUR 3 | video_publish.py 改造完成，单独跑通 |
| HOUR 4 | workflow_runner.py 串接完毕 |
| HOUR 5 | 联调，发现 DOM 选择器问题 |
| HOUR 6+ | 修复 bug，截图确认逻辑，微调 |

#### 0F: Mode Confirmed

SELECTIVE EXPANSION — 核心流程锁定，两个精选扩展建议：

**扩展1（推荐）：断点恢复机制**
当前方案取记录时找「待制作」或「待发布」，但没有记录处理到哪一步。如果中途崩溃，下次会重新开始，导致重复处理。

建议：每次状态更新同时记录「最后处理时间」，取记录时加时间窗口过滤（避免刚更新的记录被立刻再取）。

**扩展2（可选）：重试机制**
闪剪渲染可能失败（闪剪云端问题），当前方案会直接标记「生成失败」。可以加一个重试逻辑（最多3次，间隔30秒）。

---

### Phase 1: CEO Findings

**Finding C1 — HIGH**
闪剪模板匹配依赖「视频标题」关键字，如果标题包含特殊字符或与模板名称差异较大，可能匹配失败。

Fix: 增加模糊匹配（关键词重合度 > 60% 则匹配），并在匹配失败时写错误信息到表格而不是直接崩溃。

**Finding C2 — MEDIUM**
视频号发布页面的 Shadow DOM 结构不稳定（微信可能随时改版），一旦选择器失效整个流程卡死。

Fix: 选择器写入配置文件而非硬编码，建立选择器版本号机制，每次发版前做选择器验证。

**Finding C3 — LOW**
调试阶段的截图确认是波哥手动点「可以发了」，但方案没有写明这个确认的接口（飞书消息关键词触发？定时轮询？）。

Fix: 确认方案：收到波哥飞书消息含「可以发了」则自动触发发布（需接入飞书消息监听）。

---

### Phase 3: Eng Review

#### 3.1 Architecture

```
┌─────────────────────────────────────────────────────┐
│  cron_publish.py (定时触发)                         │
│  ├── workflow_runner.py (可选，串接模块)             │
│  │   ├── shanjian_make.py (闪剪)                   │
│  │   │   └── update_status.py (状态更新)            │
│  │   └── video_publish.py (视频号)                  │
│  │       └── update_status.py (状态更新)            │
│  └── lark-cli (飞书通知/云盘)                      │
└─────────────────────────────────────────────────────┘
```

架构清晰，依赖单向无环，update_status 是共享叶子节点，模块间无循环依赖。

**问题**: workflow_runner.py 如果存在，它和 cron_publish.py 的职责有重叠（都是串接模块）。建议：workflow_runner 做成可选，cron_publish.py 直接调用各模块。

#### 3.2 State Machine Verification

**闪剪状态流：**
```
待制作 → 制作中 → 待下载 → 待发布
           ↓
       生成失败
```

路径验证：
- ✅ 待制作 → 制作中（开始处理）
- ✅ 制作中 → 待下载（点导出）
- ✅ 待下载 → 待发布（下载完成）
- ✅ 任意 → 生成失败（任何节点失败）

**视频号状态流：**
```
待发布 → 发布中 → 已发布
              ↓
          发布失败
```

路径验证：
- ✅ 待发布 → 发布中（开始处理）
- ✅ 发布中 → 已发布（点发布成功）
- ✅ 发布中 → 发布失败（发布出错）

#### 3.3 Error Paths — Missing

**闪剪错误场景未覆盖：**

| 错误场景 | 当前处理 | 建议 |
|----------|----------|------|
| 模板匹配失败（找不到卡片） | 崩溃 | 写「生成失败」+错误信息 |
| 做同款按钮点击失败 | 崩溃 | 重试3次，再失败写「生成失败」 |
| 编辑器窗口未打开超时 | 崩溃 | 写「生成失败」+错误信息 |
| 渲染超时（5分钟无新视频） | 崩溃 | 写「生成失败」+错误信息 |
| 下载链接捕获失败 | 崩溃 | 写「下载失败」+错误信息 |

**视频号错误场景未覆盖：**

| 错误场景 | 当前处理 | 建议 |
|----------|----------|------|
| 视频上传失败（文件过大/格式不对） | 崩溃 | 写「上传失败」+错误信息 |
| Shadow DOM 选择器失效 | 崩溃 | 写「发布失败」+具体选择器 |
| 发布按钮点击无响应 | 崩溃 | 重试3次，再失败写「发布失败」 |
| 发布后页面未跳转（假成功） | 标记已发布 | 加 URL 校验确认真正发布成功 |

#### 3.4 Test Coverage — Critical Gap

**无测试文件**。这是一个自动化流程，崩溃风险高，但没有任何测试。

建议的最小测试集：
1. `test_update_status.py` — 验证状态写入/读取正确（mock lark-cli）
2. `test_state_machine.py` — 验证状态流转符合设计（单元测试）
3. `test_template_match.py` — 验证关键字匹配逻辑正确

---

### Decision Audit Trail

| # | Phase | Decision | Classification | Principle | Rationale |
|---|-------|----------|-----------|-----------|-----------|
| D1 | CEO | 保持当前模块独立设计 | MECHANICAL | P4 (DRY) | 独立模块调试灵活，合并引入耦合 |
| D2 | CEO | 不加入自动重试（当前阶段） | MECHANICAL | P3 (Pragmatic) | 重试增加复杂度，第一版先跑通再优化 |
| D3 | CEO | 断点恢复暂不实现 | TASTE | P2 (Boil lakes) | 有价值但非第一版必须，先交付核心流程 |
| D4 | Eng | workflow_runner 降级为可选 | MECHANICAL | P5 (Explicit) | 避免与 cron_publish 职责重叠 |
| D5 | Eng | 所有崩溃点必须捕获写错误信息 | MECHANICAL | P1 (Completeness) | 没有错误信息就无法定位问题 |
| D6 | Eng | 选择器写入配置文件 | TASTE | P2 (Boil lakes) | 硬编码选择器是隐性技术债，上线后难以维护 |

---

### Completion Summary

| 维度 | 评分 | 说明 |
|------|------|------|
| CEO 完整性 | 9/10 | 错误场景覆盖完整，选择器配置化已纳入 |
| 工程实现 | 8/10 | 状态机设计合理，try-except 全覆盖 |
| 可维护性 | 8/10 | 选择器版本化，错误信息规范化 |
| 上线风险 | LOW | 错误路径全覆盖，上线后可定位任何失败 |

**已纳入：** 错误场景覆盖（3.4 节）、选择器配置化（selectors.json）、try-except 原则（执行原则第 5 条）

**最大风险**: 闪剪 DOM 变化 → 通过 selectors.json 版本机制 + 调试阶段截图确认捕获

**最大机会**: 波哥的「调试阶段截图确认」是人工 QA 环节，善用这个机制早期捕获 DOM 变化问题

---

*评审完成时间: 2026-04-26 | 评审工具: /autoplan (gstack)*
