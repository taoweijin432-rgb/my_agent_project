# 前端工作台

这是 AI 测试用例生成助手的 React + TypeScript 前端工作台，基于 Vite 构建，默认通过本地 Vite proxy 访问 FastAPI 后端。

## 功能范围

- 测试用例同步生成和异步任务提交。
- 生成结果表格展示、Excel 导出、pytest 模板导出。
- 异步任务列表和任务详情查看。
- 知识库文档查询、更新、删除和检索验证。
- 生成历史、质量门控查看和门控审批。
- 基于当前用例的需求覆盖率评估，并支持人工确认后沉淀覆盖缺口到知识库。

## 代码结构

- `src/App.tsx`：当前页面组合和主要状态编排入口，后续会继续拆成更细的页面组件。
- `src/api/client.ts`：后端 API client，以及 URL 拼接、health URL、query string、错误消息归一化等可测试辅助函数。
- `src/api/download.ts`：浏览器 Blob 下载工具，供 Excel 和 pytest 模板导出复用。
- `src/api/generate.ts`：生成请求归一化，包括文本 trim、数值范围夹取和空 focus type 处理。
- `src/api/requirements.ts`：覆盖率评估需求点文本解析和标签拆分。
- `src/api/format.ts`：日期、耗时、百分比和状态/类型标签展示格式化。
- `src/api/settings.ts`：API Base 和 API Key 的 localStorage 持久化。
- `src/api/types.ts`：前端使用的后端 DTO TypeScript 类型。
- `src/components/GeneratePanel.tsx`：用例生成表单、同步生成和异步任务提交。
- `src/components/JobsPanel.tsx`：异步任务列表、状态过滤、任务详情和结果回填。
- `src/components/KnowledgePanel.tsx`：知识文档列表、upsert/delete 和检索验证。
- `src/components/HistoryPanel.tsx`：生成历史、门控列表、详情查看、覆盖率入口和审批处理。
- `src/components/CoveragePanel.tsx`：需求覆盖率输入、评估调用、结果展示和缺口沉淀。
- `src/components/ResultView.tsx`：生成结果展示、Excel/pytest 导出和检索上下文展示。
- `src/components/common.tsx`：状态徽标、指标、空状态、提示条、标签列表和片段列表等共享展示组件。

## 环境

- Node.js 20+
- npm 10+
- 后端 API 默认运行在 `http://127.0.0.1:8000`

项目级 npm 源配置在 `.npmrc` 中：

```text
registry=https://registry.npmmirror.com/
audit=false
fund=false
```

## 安装

```bash
cd frontend
npm install --ignore-scripts --omit=optional
```

当前工程显式安装了 Linux x64 平台所需的 Rollup 和 esbuild 原生包，因此可以在本机保持较小依赖体积。如果要在 macOS、Windows 或 ARM 环境运行，建议改用普通安装：

```bash
npm install
```

## 开发运行

先启动后端：

```bash
./.venv/bin/python scripts/run_server.py --host 127.0.0.1 --port 8000
```

再启动前端：

```bash
cd frontend
npm run dev
```

打开：

```text
http://127.0.0.1:5173
```

页面顶部默认 API Base 是 `/api/v1`，开发模式会由 Vite 转发到 `http://127.0.0.1:8000`。API Key 使用后端 `.env.runtime` 中的 `APP_API_KEY`，在页面顶部输入后点击保存。

如需修改代理目标，创建本地 `.env.local`，该文件不提交：

```bash
printf 'VITE_API_PROXY_TARGET=http://127.0.0.1:8000\n' > .env.local
```

## 测试

```bash
cd frontend
npm test
```

当前 Vitest 覆盖配置持久化、API URL/错误/Blob 请求逻辑、下载工具、生成请求归一化、需求解析、展示格式化，以及生成、任务、导出、覆盖率、门控审批和知识库交互的组件行为。

## 构建

```bash
cd frontend
npm run build
```

构建产物输出到 `frontend/dist/`，该目录不提交到仓库。
