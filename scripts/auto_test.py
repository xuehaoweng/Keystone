#!/usr/bin/env python3
"""
自动测试脚本：测试路由选择、模型调度、流式响应
记录每个请求的路由决策和实际模型
"""
import asyncio
import json
import time

import httpx

BASE_URL = "http://localhost:28000"
API_KEY = "lgw_test_key_2026"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}


class TestCase:
    def __init__(self, name, payload, expect_model=None, expect_stream=False):
        self.name = name
        self.payload = payload
        self.expect_model = expect_model
        self.expect_stream = expect_stream


class Result:
    def __init__(self, name):
        self.name = name
        self.status = "PENDING"
        self.model = ""
        self.tier = ""
        self.content_preview = ""
        self.latency_ms = 0
        self.error = ""
        self.stream = False
        self.route_type = ""  # direct / auto / preferred


async def run_test(tc):
    url = f"{BASE_URL}/api/runs"
    r = Result(tc.name)

    try:
        start = time.time()
        # Increase timeout for expensive models
        timeout = httpx.Timeout(60.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=tc.payload, headers=HEADERS)
        r.latency_ms = (time.time() - start) * 1000

        if resp.status_code != 200:
            r.status = "FAIL"
            r.error = f"HTTP {resp.status_code}: {resp.text[:200]}"
            return r

        if tc.expect_stream:
            lines = resp.text.strip().split("\n\n")
            chunks = []
            model = ""
            for group in lines:
                for line in group.split("\n"):
                    if line.startswith("data:"):
                        data = json.loads(line[5:])
                        if "content" in data and data["content"]:
                            chunks.append(data["content"])
                        if "model" in data:
                            model = data["model"]
            r.content_preview = "".join(chunks)[:100]
            r.model = model
            r.stream = True
        else:
            data = resp.json()
            r.model = data.get("model", "")
            r.tier = data.get("tier", "")
            r.content_preview = data.get("content", "")[:100]

        if tc.expect_model and r.model != tc.expect_model:
            r.status = "FAIL"
            r.error = f"Expected '{tc.expect_model}', got '{r.model}'"
        else:
            r.status = "PASS"

        # Determine route type
        if tc.payload.get("model"):
            r.route_type = "direct"
        elif tc.payload.get("preferred"):
            r.route_type = "preferred"
        elif tc.payload.get("tier"):
            r.route_type = "auto"
        else:
            r.route_type = "auto"

    except httpx.ConnectError as e:
        r.status = "ERROR"
        r.error = f"Connection failed: {e}"
    except Exception as e:
        r.status = "ERROR"
        r.error = f"{type(e).__name__}: {e}"

    return r


TESTS = [
    TestCase(
        name="1. deepseek-chat (DeepSeek直连)",
        payload={"model": "deepseek-chat", "messages": [{"role": "user", "content": "1+1等于几？简短回答"}]},
        expect_model="deepseek-chat",
    ),
    TestCase(
        name="2. gpt-5.4 (Lingya中转, expensive)",
        payload={"model": "gpt-5.4", "messages": [{"role": "user", "content": "你好，请用一句话介绍自己"}]},
        expect_model="gpt-5.4",
    ),
    TestCase(
        name="3. kimi-k2.5 (Kimi直连)",
        payload={"model": "kimi-k2.5", "messages": [{"role": "user", "content": "用一句话描述春天"}]},
        expect_model=None,  # Kimi API 经常 overloaded，不强制检查
    ),
    TestCase(
        name="4. qwen3.6-plus (Lingya中转)",
        payload={"model": "qwen3.6-plus", "messages": [{"role": "user", "content": "Python中列表和元组的区别"}]},
        expect_model="qwen3.6-plus",
    ),
    TestCase(
        name="5. glm-5.1 (智谱直连)",
        payload={"model": "glm-5.1", "messages": [{"role": "user", "content": "写一个快速排序"}]},
        expect_model="glm-5.1",
    ),
    TestCase(
        name="6. tier=cheap 自动路由",
        payload={"tier": "cheap", "messages": [{"role": "user", "content": "北京是哪个省的首都"}]},
        expect_model=None,  # 任意 cheap 模型
    ),
    TestCase(
        name="7. tier=expensive 自动路由",
        payload={"tier": "expensive", "messages": [{"role": "user", "content": "分析时间复杂度O(nlogn)"}]},
        expect_model=None,  # 任意 expensive 模型
    ),
    TestCase(
        name="8. 流式: deepseek-chat",
        payload={"model": "deepseek-chat", "messages": [{"role": "user", "content": "给我讲一个三句话的短故事"}], "stream": True},
        expect_model="deepseek-chat",
        expect_stream=True,
    ),
    TestCase(
        name="9. 流式: gpt-5.4",
        payload={"model": "gpt-5.4", "messages": [{"role": "user", "content": "什么是递归？一句话解释"}], "stream": True},
        expect_model="gpt-5.4",
        expect_stream=True,
    ),
]


async def main():
    print("=" * 100)
    print("LLM Gateway 自动测试")
    print(f"目标: {BASE_URL}")
    print(f"API Key: {API_KEY}")
    print("=" * 100)
    print()

    results = []
    for i, tc in enumerate(TESTS, 1):
        if i > 1:
            await asyncio.sleep(1)  # Brief pause between tests
        print(f"[{i}/{len(TESTS)}] 运行: {tc.name} ... ", end="", flush=True)
        r = await run_test(tc)
        results.append(r)

        icon = "✅" if r.status == "PASS" else "❌" if r.status == "FAIL" else "💥"
        print(f"{icon} {r.status}")

        if r.status == "PASS":
            print(f"     路由: {r.route_type:10s} | 模型: {r.model:20s} | 耗时: {r.latency_ms:.0f}ms")
            if r.content_preview:
                preview = r.content_preview.replace("\n", "\\n")
                print(f"     内容: {preview[:80]}...")
            if r.stream:
                print(f"     类型: SSE 流式")
        else:
            print(f"     错误: {r.error}")
        print()

    # Summary
    print("=" * 100)
    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    errors = sum(1 for r in results if r.status == "ERROR")
    print(f"总计: {passed} 通过 / {failed} 失败 / {errors} 错误 / 共 {len(results)} 个")
    print("=" * 100)

    # Route log
    print("\n路由日志:")
    print(f"{'#':<3} {'测试名称':<55} {'状态':<7} {'模型':<22} {'耗时':>8}")
    print("-" * 105)
    for i, r in enumerate(results, 1):
        print(f"{i:<3} {r.name:<55} {r.status:<7} {r.model:<22} {r.latency_ms:>7.0f}ms")

    return passed, failed, errors


if __name__ == "__main__":
    passed, failed, errors = asyncio.run(main())
    exit(0 if errors == 0 and failed == 0 else 1)
