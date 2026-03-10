# 测试指南

## 概述

本指南介绍如何运行 Kolya BR Proxy 价格系统的单元测试。

## 前置条件

安装测试依赖：

```bash
cd backend
pip install pytest pytest-asyncio httpx
```

## 运行测试

### 运行所有测试

```bash
cd backend
pytest
```

### 运行特定测试文件

```bash
pytest tests/test_pricing.py
```

### 运行特定测试类

```bash
pytest tests/test_pricing.py::TestPricingService
```

### 运行特定测试方法

```bash
pytest tests/test_pricing.py::TestPricingService::test_calculate_cost
```

### 详细输出模式

```bash
pytest -v
```

### 生成覆盖率报告

```bash
pip install pytest-cov
pytest --cov=app --cov-report=html
```

查看覆盖率报告：
```bash
open htmlcov/index.html
```

## 测试结构

### 测试文件

- `tests/test_pricing.py` - 价格系统测试

### 测试类

1. **TestModelPricingModel**
   - 数据库模型测试
   - CRUD 操作
   - 唯一约束

2. **TestPricingUpdater**
   - PricingUpdater 服务测试
   - AWS API 获取
   - 网页爬虫降级
   - 数据库操作

3. **TestPricingService**
   - 成本计算测试
   - 价格查询
   - 错误处理

4. **TestPricingIntegration**
   - 端到端工作流测试
   - 多区域场景

## 测试覆盖

### ModelPricing 模型
- ✅ 创建价格记录
- ✅ 唯一约束验证
- ✅ 字段验证

### PricingUpdater 服务
- ✅ 保存价格数据（插入）
- ✅ 保存价格数据（更新已存在）
- ✅ 获取价格（区域降级）
- ✅ 获取价格（未找到）
- ✅ 规范化区域名称
- ✅ 从 AWS Price List API 获取
- ✅ 从网页爬虫获取
- ✅ 更新所有价格（API 成功）
- ✅ 更新所有价格（降级到爬虫）
- ✅ 更新所有价格（两个源都失败）

### PricingService
- ✅ 计算成本（正常情况）
- ✅ 计算成本（大数字）
- ✅ 计算成本（模型未找到）
- ✅ 计算成本（零 token）
- ✅ 获取模型价格信息
- ✅ 获取价格信息未找到
- ✅ 无数据库计算成本

### 集成测试
- ✅ 完整价格工作流
- ✅ 同一模型多区域

## 编写新测试

### 测试模板

```python
import pytest
from decimal import Decimal

class TestNewFeature:
    """测试描述。"""

    @pytest.mark.asyncio
    async def test_feature(self, db_session):
        """测试特定行为。"""
        # 准备 (Arrange)
        # ... 设置测试数据

        # 执行 (Act)
        # ... 执行被测代码

        # 断言 (Assert)
        # ... 验证结果
        assert result == expected
```

### 使用 Fixtures

```python
@pytest.fixture
async def sample_data():
    """提供测试样本数据。"""
    return {
        "model_id": "test-model",
        "region": "us-east-1",
    }

@pytest.mark.asyncio
async def test_with_fixture(db_session, sample_data):
    """使用 fixture 的测试。"""
    # 在测试中使用 sample_data
    pass
```

### Mock 外部 API

```python
from unittest.mock import patch, AsyncMock

@pytest.mark.asyncio
async def test_api_call(db_session):
    """使用 mock API 的测试。"""
    with patch("httpx.AsyncClient") as mock_client:
        mock_response = AsyncMock()
        mock_response.json.return_value = {"data": "value"}
        mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

        # 使用 httpx.AsyncClient 的测试代码
        pass
```

## 持续集成

### GitHub Actions 示例

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
    - uses: actions/checkout@v2

    - name: Set up Python
      uses: actions/setup-python@v2
      with:
        python-version: '3.12'

    - name: Install dependencies
      run: |
        cd backend
        pip install -r requirements.txt
        pip install pytest pytest-asyncio pytest-cov

    - name: Run tests
      run: |
        cd backend
        pytest --cov=app --cov-report=xml

    - name: Upload coverage
      uses: codecov/codecov-action@v2
```

## 故障排查

### 问题：测试失败提示 "No module named 'app'"

**解决方案：**
```bash
cd backend
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
pytest
```

### 问题：异步测试不运行

**解决方案：**
确保安装了 `pytest-asyncio`：
```bash
pip install pytest-asyncio
```

### 问题：数据库连接错误

**解决方案：**
测试使用内存 SQLite 数据库。确保安装了 `aiosqlite`：
```bash
pip install aiosqlite
```

## 最佳实践

1. **测试隔离**：每个测试应该独立
2. **使用 Fixtures**：共享通用设置代码
3. **Mock 外部服务**：不要进行真实 API 调用
4. **测试边界情况**：零值、空值、错误
5. **清晰的测试名称**：描述正在测试的内容
6. **准备-执行-断言**：清晰地组织测试结构
7. **清理**：使用 fixtures 自动处理清理

## 性能

### 快速测试
- 使用内存数据库
- Mock 外部 API 调用
- 避免不必要的 I/O

### 慢速测试
- 使用 `@pytest.mark.slow` 标记
- 单独运行：`pytest -m "not slow"`

## 代码覆盖率目标

- 总体：> 80%
- 关键路径：100%
- 错误处理：100%

检查当前覆盖率：
```bash
pytest --cov=app --cov-report=term-missing
```
