#!/usr/bin/env python3
"""
免费数据源API与MCP工具综合测试脚本
使用方法:
1. 修改下方的API密钥配置
2. 运行: python test_all_apis.py
"""

import requests
import json
import time
from datetime import datetime
from typing import Dict, Any

# ==================== 配置区 ====================
# 请替换为你的实际API密钥

CONFIG = {
    "ALAPI_TOKEN": "your_alapi_token_here",
    "APIHZ_ID": "your_apihz_id_here",
    "APIHZ_KEY": "your_apihz_key_here",
    "WORLD_NEWS_API_KEY": "your_worldnews_key_here",
    "ALPHA_VANTAGE_KEY": "your_alphavantage_key_here",
    "STOCK_MCP_HOST": "localhost",
    "STOCK_MCP_PORT": 9898,
}

# ==================== 测试类 ====================


class DataAPITester:
    """数据API测试器"""

    def __init__(self):
        self.results: Dict[str, str] = {}

    def print_header(self, title: str):
        """打印标题"""
        print("\n" + "=" * 60)
        print(title)
        print("=" * 60)

    def test_alapi_weibo(self, token: str) -> Dict[str, Any]:
        """
        测试ALAPI微博热搜

        输入参数:
        - token: ALAPI用户token

        用途: 获取微博热搜榜数据
        """
        print("\n[1] 测试 ALAPI 微博热搜...")
        print(f"    接口: https://v2.alapi.cn/api/new/wbHot")
        print(f"    参数: token={token[:10]}...")

        try:
            url = "https://v2.alapi.cn/api/new/wbHot"
            params = {"token": token}

            start_time = time.time()
            response = requests.get(url, params=params, timeout=10)
            elapsed_time = time.time() - start_time

            data = response.json()

            if data["code"] == 200:
                print(f"✓ 成功 (耗时: {elapsed_time:.2f}s)")
                print(f"  热搜数量: {len(data['data'])}")

                # 显示前3条热搜
                print("\n  热搜示例:")
                for i, item in enumerate(data["data"][:3], 1):
                    print(f"  {i}. {item['hotword']}")
                    print(
                        f"     热度: {item['hotwordnum']} | 标签: {item.get('hottag', 'N/A')}"
                    )

                self.results["alapi_weibo"] = "success"
                return data
            else:
                print(f"✗ 失败: {data['msg']}")
                self.results["alapi_weibo"] = "failed"
                return {}

        except requests.exceptions.Timeout:
            print("✗ 错误: 请求超时")
            self.results["alapi_weibo"] = "timeout"
            return {}
        except Exception as e:
            print(f"✗ 错误: {e}")
            self.results["alapi_weibo"] = "error"
            return {}

    def test_alapi_toutiao(self, token: str) -> Dict[str, Any]:
        """
        测试ALAPI今日热榜

        输入参数:
        - token: ALAPI用户token
        - type: hot(热门) 或 recommend(推荐)

        用途: 获取多平台聚合的热榜数据
        """
        print("\n[2] 测试 ALAPI 今日热榜...")
        print(f"    接口: https://v2.alapi.cn/api/new/toutiao")

        try:
            url = "https://v2.alapi.cn/api/new/toutiao"
            params = {"token": token, "type": "hot"}

            start_time = time.time()
            response = requests.get(url, params=params, timeout=10)
            elapsed_time = time.time() - start_time

            data = response.json()

            if data["code"] == 200:
                print(f"✓ 成功 (耗时: {elapsed_time:.2f}s)")
                print(f"  总条数: {data['data']['total']}")

                # 显示前3条
                print("\n  热榜示例:")
                for item in data["data"]["list"][:3]:
                    print(f"  - [{item['source']}] {item['title']}")
                    if "hot_score" in item:
                        print(f"    热度: {item['hot_score']}")

                self.results["alapi_toutiao"] = "success"
                return data
            else:
                print(f"✗ 失败: {data['msg']}")
                self.results["alapi_toutiao"] = "failed"
                return {}

        except Exception as e:
            print(f"✗ 错误: {e}")
            self.results["alapi_toutiao"] = "error"
            return {}

    def test_yi18_list(self) -> Dict[str, Any]:
        """
        测试Yi18热词列表

        输入参数: 无

        用途: 获取基于百度、搜狗、Google趋势的热点关键词
        """
        print("\n[3] 测试 Yi18 热词列表...")
        print(f"    接口: http://api.yi18.net/top/list")

        try:
            url = "http://api.yi18.net/top/list"

            start_time = time.time()
            response = requests.get(url, timeout=10)
            elapsed_time = time.time() - start_time

            data = response.json()

            if "yi18" in data:
                print(f"✓ 成功 (耗时: {elapsed_time:.2f}s)")
                print(f"  热词数量: {len(data['yi18'])}")

                # 显示前3个热词
                print("\n  热词示例:")
                for item in data["yi18"][:3]:
                    print(f"  - {item['title']}")
                    print(f"    关键词: {item['keywords']}")
                    print(f"    关注度: {item['count']}")

                self.results["yi18_list"] = "success"
                return data
            else:
                print("✗ 失败: 返回数据格式错误")
                self.results["yi18_list"] = "failed"
                return {}

        except Exception as e:
            print(f"✗ 错误: {e}")
            self.results["yi18_list"] = "error"
            return {}

    def test_yi18_detail(self, keyword_id: int = 1001) -> Dict[str, Any]:
        """
        测试Yi18热词详情

        输入参数:
        - id: 热词ID

        用途: 获取热词的详细信息和相关新闻
        """
        print(f"\n[4] 测试 Yi18 热词详情 (ID: {keyword_id})...")
        print(f"    接口: http://api.yi18.net/top/detail")

        try:
            url = "http://api.yi18.net/top/detail"
            params = {"id": keyword_id}

            start_time = time.time()
            response = requests.get(url, params=params, timeout=10)
            elapsed_time = time.time() - start_time

            data = response.json()

            if "title" in data:
                print(f"✓ 成功 (耗时: {elapsed_time:.2f}s)")
                print(f"  标题: {data['title']}")
                print(f"  关键词: {data['keywords']}")
                print(f"  关注度: {data['count']}")

                if "news" in data and len(data["news"]) > 0:
                    print(f"  相关新闻数: {len(data['news'])}")
                    print(f"\n  新闻示例:")
                    print(f"  - {data['news'][0]['title']}")

                self.results["yi18_detail"] = "success"
                return data
            else:
                print("✗ 失败: 无法获取详情")
                self.results["yi18_detail"] = "failed"
                return {}

        except Exception as e:
            print(f"✗ 错误: {e}")
            self.results["yi18_detail"] = "error"
            return {}

    def test_apihz_weibo(self, user_id: str, user_key: str) -> Dict[str, Any]:
        """
        测试接口盒子微博热搜

        输入参数:
        - id: 用户ID
        - key: 用户KEY

        用途: 获取微博实时上升热点
        """
        print("\n[5] 测试 接口盒子 微博热搜...")
        print(f"    接口: https://api.apihz.cn/v1/weibo/hotrising")

        try:
            url = "https://api.apihz.cn/v1/weibo/hotrising"
            params = {"id": user_id, "key": user_key, "format": "json"}

            start_time = time.time()
            response = requests.get(url, params=params, timeout=10)
            elapsed_time = time.time() - start_time

            data = response.json()

            if data["code"] == 200:
                print(f"✓ 成功 (耗时: {elapsed_time:.2f}s)")
                print(f"  热点数量: {len(data['data'])}")

                # 显示前3条
                print("\n  上升热点示例:")
                for item in data["data"][:3]:
                    print(f"  {item['rank']}. {item['keyword']}")
                    print(f"     热度: {item['heat']} | 趋势: {item['trend']}")

                self.results["apihz_weibo"] = "success"
                return data
            else:
                print(f"✗ 失败: {data['msg']}")
                self.results["apihz_weibo"] = "failed"
                return {}

        except Exception as e:
            print(f"✗ 错误: {e}")
            self.results["apihz_weibo"] = "error"
            return {}

    def test_world_news_mcp_search(self, api_key: str) -> Dict[str, Any]:
        """
        测试World News API MCP搜索功能

        输入参数:
        - text: 搜索文本
        - language: 语言代码
        - number: 返回数量

        用途: 搜索全球新闻并支持情感分析
        """
        print("\n[6] 测试 World News API MCP...")
        print(f"    接口: https://mcp.alphavantage.co/mcp")

        try:
            url = f"https://mcp.alphavantage.co/mcp?apikey={api_key}"

            # 先测试工具列表
            payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}

            start_time = time.time()
            response = requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            elapsed_time = time.time() - start_time

            data = response.json()

            if "result" in data:
                tools = data["result"].get("tools", [])
                print(f"✓ MCP服务器连接成功 (耗时: {elapsed_time:.2f}s)")
                print(f"  可用工具数: {len(tools)}")

                # 显示部分工具
                print("\n  工具示例:")
                for tool in tools[:5]:
                    print(
                        f"  - {tool['name']}: {tool.get('description', 'N/A')[:50]}..."
                    )

                self.results["world_news_mcp"] = "success"
                return data
            else:
                print("✗ 失败: 无法获取工具列表")
                self.results["world_news_mcp"] = "failed"
                return {}

        except Exception as e:
            print(f"✗ 错误: {e}")
            self.results["world_news_mcp"] = "error"
            return {}

    def test_alpha_vantage_mcp(self, api_key: str) -> Dict[str, Any]:
        """
        测试Alpha Vantage MCP

        输入参数:
        - symbol: 股票代码

        用途: 获取股票数据和新闻情感
        """
        print("\n[7] 测试 Alpha Vantage MCP...")
        print(f"    接口: https://mcp.alphavantage.co/mcp")

        try:
            url = f"https://mcp.alphavantage.co/mcp?apikey={api_key}"

            # 测试获取股票报价
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "TOOL_CALL",
                    "arguments": {
                        "tool_name": "GLOBAL_QUOTE",
                        "arguments": {"symbol": "AAPL"},
                    },
                },
            }

            start_time = time.time()
            response = requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            elapsed_time = time.time() - start_time

            data = response.json()

            if "result" in data:
                print(f"✓ 成功获取AAPL股票数据 (耗时: {elapsed_time:.2f}s)")

                quote = data["result"].get("Global Quote", {})
                if quote:
                    print(f"  股票代码: {quote.get('01. symbol', 'N/A')}")
                    print(f"  开盘价: ${quote.get('02. open', 'N/A')}")
                    print(f"  最高价: ${quote.get('03. high', 'N/A')}")
                    print(f"  最低价: ${quote.get('04. low', 'N/A')}")
                    print(f"  收盘价: ${quote.get('05. price', 'N/A')}")
                    print(f"  成交量: {quote.get('06. volume', 'N/A')}")

                self.results["alpha_vantage_mcp"] = "success"
                return data
            else:
                print("✗ 失败: 无法获取数据")
                self.results["alpha_vantage_mcp"] = "failed"
                return {}

        except Exception as e:
            print(f"✗ 错误: {e}")
            self.results["alpha_vantage_mcp"] = "error"
            return {}

    def test_stock_mcp(
        self, host: str = "localhost", port: int = 9898
    ) -> Dict[str, Any]:
        """
        测试stock-mcp

        输入参数: 无

        用途: 获取市场报告和A股数据
        """
        print(f"\n[8] 测试 stock-mcp...")
        print(f"    接口: http://{host}:{port}/mcp")

        try:
            url = f"http://{host}:{port}/mcp"

            # 测试获取市场报告
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "get_market_report", "arguments": {}},
            }

            start_time = time.time()
            response = requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            elapsed_time = time.time() - start_time

            data = response.json()

            if "result" in data:
                print(f"✓ 成功获取市场报告 (耗时: {elapsed_time:.2f}s)")
                print(f"  市场状态: {data['result'].get('market_status', 'N/A')}")

                self.results["stock_mcp"] = "success"
                return data
            else:
                print("✗ 失败: 无法获取市场报告")
                print(f"  提示: 请确保stock-mcp服务已启动")
                print(
                    f"  启动命令: python -m uvicorn src.server.app:app --host 0.0.0.0 --port {port}"
                )
                self.results["stock_mcp"] = "failed"
                return {}

        except requests.exceptions.ConnectionError:
            print(f"✗ 错误: 无法连接到服务器 (http://{host}:{port})")
            print(f"  提示: 请确保stock-mcp服务已启动")
            self.results["stock_mcp"] = "connection_error"
            return {}
        except Exception as e:
            print(f"✗ 错误: {e}")
            self.results["stock_mcp"] = "error"
            return {}

    def generate_report(self):
        """生成测试报告"""
        print("\n" + "=" * 60)
        print("测试报告汇总")
        print("=" * 60)

        success_count = sum(1 for v in self.results.values() if v == "success")
        failed_count = sum(1 for v in self.results.values() if v == "failed")
        error_count = sum(
            1
            for v in self.results.values()
            if v in ["error", "timeout", "connection_error"]
        )
        total_count = len(self.results)

        for api_name, status in self.results.items():
            status_icon = {
                "success": "✓",
                "failed": "✗",
                "error": "⚠",
                "timeout": "⏱",
                "connection_error": "🔌",
            }.get(status, "?")

            status_text = {
                "success": "成功",
                "failed": "失败",
                "error": "错误",
                "timeout": "超时",
                "connection_error": "连接失败",
            }.get(status, status)

            print(f"{status_icon} {api_name:25s} - {status_text}")

        print(f"\n统计:")
        print(f"  成功: {success_count}")
        print(f"  失败: {failed_count}")
        print(f"  错误: {error_count}")
        print(f"  总计: {total_count}")

        if total_count > 0:
            success_rate = (success_count / total_count) * 100
            print(f"\n成功率: {success_rate:.1f}%")

        print("=" * 60)


# ==================== 主函数 ====================


def main():
    """主测试函数"""
    tester = DataAPITester()

    tester.print_header("免费数据源API与MCP工具综合测试")
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"测试项目: 8个API/MCP工具")

    # 执行测试
    # 1. ALAPI微博热搜
    if CONFIG["ALAPI_TOKEN"] != "your_alapi_token_here":
        tester.test_alapi_weibo(CONFIG["ALAPI_TOKEN"])
        time.sleep(0.5)

        # 2. ALAPI今日热榜
        tester.test_alapi_toutiao(CONFIG["ALAPI_TOKEN"])
        time.sleep(0.5)

    # 3. Yi18热词列表
    tester.test_yi18_list()
    time.sleep(0.5)

    # 4. Yi18热词详情
    tester.test_yi18_detail(keyword_id=1001)
    time.sleep(0.5)

    # 5. 接口盒子微博热搜
    if CONFIG["APIHZ_ID"] != "your_apihz_id_here":
        tester.test_apihz_weibo(CONFIG["APIHZ_ID"], CONFIG["APIHZ_KEY"])
        time.sleep(0.5)

    # 6. World News API MCP
    if CONFIG["WORLD_NEWS_API_KEY"] != "your_worldnews_key_here":
        tester.test_world_news_mcp_search(CONFIG["WORLD_NEWS_API_KEY"])
        time.sleep(0.5)

    # 7. Alpha Vantage MCP
    if CONFIG["ALPHA_VANTAGE_KEY"] != "your_alphavantage_key_here":
        tester.test_alpha_vantage_mcp(CONFIG["ALPHA_VANTAGE_KEY"])
        time.sleep(0.5)

    # 8. stock-mcp
    tester.test_stock_mcp(host=CONFIG["STOCK_MCP_HOST"], port=CONFIG["STOCK_MCP_PORT"])

    # 生成报告
    tester.generate_report()

    print("\n提示:")
    print("1. 如果某些测试失败，请检查API密钥配置")
    print("2. 免费API有调用频率限制，请勿频繁测试")
    print("3. 详细文档请查看: design/免费数据源API与MCP工具集成文档.md")


if __name__ == "__main__":
    main()
