#!/usr/bin/env python3
"""
交互式测试脚本：选择模型，发送问题，查看响应
不并发，一问一答
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

MODELS = {
    "1": ("deepseek-chat", "cheap", "DeepSeek 直连"),
    "2": ("gpt-5.4", "expensive", "Lingya 中转"),
    "3": ("kimi-k2.5", "cheap", "Kimi 直连"),
    "4": ("qwen3.6-plus", "expensive", "Lingya 中转"),
    "5": ("glm-5.1", "expensive", "智谱 直连"),
}


def show_menu():
    print("\n" + "=" * 60)
    print("LLM Gateway 交互测试")
    print(f"网关地址: {BASE_URL}")
    print("=" * 60)
    print("可用模型:")
    for key, (name, tier, desc) in MODELS.items():
        print(f"  {key}. {name:20s} [{tier:10s}] {desc}")
    print("  6. 自动路由 (cheap)")
    print("  7. 自动路由 (expensive)")
    print("  0. 退出")
    print("=" * 60)


async def send_request(model_or_tier, question, stream=False, preferred=None):
    """发送请求到 gateway"""
    payload = {
        "messages": [{"role": "user", "content": question}],
        "stream": stream,
    }
    if model_or_tier in MODELS:
        payload["model"] = MODELS[model_or_tier][0]
    elif model_or_tier == "cheap":
        payload["tier"] = "cheap"
    elif model_or_tier == "expensive":
        payload["tier"] = "expensive"
        if preferred:
            payload["preferred_model"] = preferred

    print(f"\n>>> 发送请求:")
    print(f"    Payload: {json.dumps(payload, ensure_ascii=False)}")

    timeout = httpx.Timeout(120.0, connect=10.0)
    start = time.time()

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{BASE_URL}/api/runs", json=payload, headers=HEADERS)
        elapsed = (time.time() - start) * 1000

    if resp.status_code != 200:
        print(f"    ❌ HTTP {resp.status_code}: {resp.text[:200]}")
        return

    if stream:
        print(f"    📡 流式响应 (SSE):")
        lines = resp.text.strip().split("\n\n")
        content = ""
        model = ""
        for group in lines:
            for line in group.split("\n"):
                if line.startswith("data:"):
                    data = json.loads(line[5:])
                    if "content" in data and data["content"]:
                        content += data["content"]
                    if "model" in data:
                        model = data["model"]
        print(f"    模型: {model}")
        print(f"    耗时: {elapsed:.0f}ms")
        print(f"    内容: {content}")
    else:
        data = resp.json()
        print(f"    ✅ 模型: {data.get('model')}")
        print(f"    📊 Tier: {data.get('tier')}")
        print(f"    📈 Tokens: {data.get('usage', {}).get('total_tokens', 0)}")
        print(f"    ⏱️  耗时: {elapsed:.0f}ms")
        print(f"    💬 内容: {data.get('content', '')[:500]}")


async def interactive():
    while True:
        show_menu()
        choice = input("\n选择模型 (1-7, 0退出): ").strip()

        if choice == "0":
            print("再见！")
            break

        if choice not in MODELS and choice not in ("6", "7"):
            print("无效选择，请重试")
            continue

        if choice in ("6", "7"):
            model_or_tier = "cheap" if choice == "6" else "expensive"
        else:
            model_or_tier = choice

        # Auto route tests
        if choice in ("6", "7"):
            preferred = input("  指定 preferred provider? (回车跳过): ").strip() or None
        else:
            preferred = None

        question = input("  请输入你的问题: ").strip()
        if not question:
            question = "你好，用一句话介绍自己"

        stream_choice = input("  是否流式? (y/N): ").strip().lower()
        stream = stream_choice == "y"

        await send_request(model_or_tier, question, stream, preferred)


if __name__ == "__main__":
    try:
        asyncio.run(interactive())
    except KeyboardInterrupt:
        print("\n\n中断退出")
