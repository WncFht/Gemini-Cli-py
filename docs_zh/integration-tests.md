# 集成测试

本文档提供了有关本项目中使用的集成测试框架的信息。

## 概述

集成测试旨在验证 Gemini CLI 的端到端功能。它们在受控环境中执行构建的二进制文件，并验证其在与文件系统交互时的行为是否符合预期。

这些测试位于 `integration-tests` 目录中，并使用自定义测试运行器运行。

## 运行测试

集成测试不作为默认 `npm run test` 命令的一部分运行。它们必须使用 `npm run test:integration:all` 脚本显式运行。

集成测试也可以使用以下快捷方式运行：

```bash
npm run test:e2e
```

## 运行特定的测试集

要运行测试文件的子集，您可以使用 `npm run <integration test command> <file_name1> ....`，其中 `<integration test command>` 是 `test:e2e` 或 `test:integration*`，而 `<file_name>` 是 `integration-tests/` 目录中的任何 `.test.js` 文件。例如，以下命令运行 `list_directory.test.js` 和 `write_file.test.js`：

```bash
npm run test:e2e list_directory write_file
```

### 按名称运行单个测试

要按名称运行单个测试，请使用 `--test-name-pattern` 标志：

```bash
npm run test:e2e -- --test-name-pattern "reads a file"
```

### 运行所有测试

要运行整个集成测试套件，请使用以下命令：

```bash
npm run test:integration:all
```

### 沙盒矩阵

`all` 命令将针对 `no sandboxing`、`docker` 和 `podman` 运行测试。
可以使用以下命令运行每种单独的类型：

```bash
npm run test:integration:sandbox:none
```

```bash
npm run test:integration:sandbox:docker
```

```bash
npm run test:integration:sandbox:podman
```

## 诊断

集成测试运行器提供了多种诊断选项，以帮助追踪测试失败。

### 保留测试输出

您可以保留在测试运行期间创建的临时文件以供检查。这对于调试文件系统操作的问题非常有用。

要保留测试输出，您可以使用 `--keep-output` 标志或将 `KEEP_OUTPUT` 环境变量设置为 `true`。

```bash
# 使用标志
npm run test:integration:sandbox:none -- --keep-output

# 使用环境变量
KEEP_OUTPUT=true npm run test:integration:sandbox:none
```

当保留输出时，测试运行器将打印出该测试运行的唯一目录的路径。

### 详细输出

为了更详细的调试，`--verbose` 标志会将 `gemini` 命令的实时输出流式传输到控制台。

```bash
npm run test:integration:sandbox:none -- --verbose
```

在同一命令中使用 `--verbose` 和 `--keep-output` 时，输出会流式传输到控制台，并保存到测试临时目录中的日志文件中。

详细输出的格式清晰地标识了日志的来源：

```
--- TEST: <file-name-without-js>:<test-name> ---
... gemini 命令的输出 ...
--- END TEST: <file-name-without-js>:<test-name> ---
```

## 代码检查和格式化

为确保代码质量和一致性，集成测试文件作为主构建过程的一部分进行代码检查。您还可以手动运行代码检查器和自动修复程序。

### 运行代码检查器

要检查代码检查错误，请运行以下命令：

```bash
npm run lint
```

您可以在命令中包含 `--fix` 标志，以自动修复任何可修复的代码检查错误：

```bash
npm run lint --fix
```

## 目录结构

集成测试在 `.integration-tests` 目录内为每次测试运行创建一个唯一的目录。在此目录中，为每个测试文件创建一个子目录，并在其中为每个单独的测试用例创建一个子目录。

这种结构使得可以轻松地定位特定测试运行、文件或用例的产物。

```
.integration-tests/
└── <run-id>/
    └── <test-file-name>.test.js/
        └── <test-case-name>/
            ├── output.log
            └── ...其他测试产物...
```

## 持续集成

为确保集成测试始终运行，`.github/workflows/e2e.yml` 中定义了一个 GitHub Actions 工作流。该工作流在每个拉取请求和推送到 `main` 分支时自动运行集成测试。

该工作流在不同的沙盒环境中运行测试，以确保在每个环境中都对 Gemini CLI 进行了测试：

- `sandbox:none`: 在没有任何沙盒的情况下运行测试。
- `sandbox:docker`: 在 Docker 容器中运行测试。
- `sandbox:podman`: 在 Podman 容器中运行测试。 