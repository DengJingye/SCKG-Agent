import re
import os
import time
from datetime import datetime, timezone
from typing import Dict, Optional

import requests

class GitHubCrawler:
    """
    GitHub 数据爬虫，负责抓取单细胞工具的工程化证据。
    """
    def __init__(self):
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
        }
        token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def extract_repo_path(self, url: str) -> Optional[str]:
        """从 GitHub 链接中智能提取 'owner/repo' 路径"""
        # 支持处理各种脏数据，例如带有 .git 后缀或 http/https 混用的情况
        match = re.search(r"github\.com/([^/]+/[^/]+)", url)
        if match:
            repo_path = match.group(1).replace(".git", "")
            # 去除末尾可能带有的斜杠或参数
            repo_path = repo_path.split('/')[0] + '/' + repo_path.split('/')[1].split('?')[0].split('#')[0]
            return repo_path
        return None

    def fetch_repo_metrics(self, url: str) -> Dict:
        """根据仓库 URL 获取核心指标字典"""
        repo_path = self.extract_repo_path(url)
        if not repo_path:
            return {"error": f"无法从 {url} 解析出仓库路径"}

        api_url = f"https://api.github.com/repos/{repo_path}"
        
        try:
            # 设置 10 秒超时，防止服务器网络卡死
            response = requests.get(api_url, headers=self.headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "tool_name": data.get("name"),
                    "repo_full_name": data.get("full_name"),
                    "repo_url": data.get("html_url") or url,
                    "github_stars": data.get("stargazers_count", 0),
                    "forks": data.get("forks_count", 0),
                    "open_issues": data.get("open_issues_count", 0),
                    "last_updated": data.get("pushed_at"), # 最后提交时间，判断工具是否活跃的重要依据
                    "api_updated_at": data.get("updated_at"),
                    "created_at": data.get("created_at"),
                    "archived": data.get("archived", False),
                    "default_branch": data.get("default_branch"),
                    "license": (data.get("license") or {}).get("spdx_id")
                    or (data.get("license") or {}).get("name"),
                    "language": data.get("language"),
                    "maintenance_status": maintenance_status(data.get("pushed_at")),
                }
            elif response.status_code == 403:
                return {"error": "API 请求频率超限！请配置 GitHub Token。"}
            elif response.status_code == 404:
                return {"error": "仓库不存在，可能已改名或被删除。"}
            else:
                return {"error": f"请求失败，状态码 {response.status_code}"}
                
        except Exception as e:
            return {"error": f"网络异常: {str(e)}"}


def maintenance_status(pushed_at: Optional[str], now: Optional[datetime] = None) -> str:
    if not pushed_at:
        return "unknown"
    now = now or datetime.now(timezone.utc)
    try:
        pushed = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
    except ValueError:
        return "unknown"
    age_days = (now - pushed).days
    if age_days <= 548:
        return "active"
    if age_days <= 1095:
        return "low_activity"
    return "stale"

# ==========================================
# 本地测试逻辑
# ==========================================
if __name__ == "__main__":
    crawler = GitHubCrawler()
    
    print("🕷️ 启动 GitHub 爬虫测试...\n")
    
    test_urls = [
        "https://github.com/immunogenomics/harmony", # 批次校正一哥
        "https://github.com/scverse/scvi-tools",     # 深度学习生态核心
        "https://github.com/theislab/scanpy.git"     # Python 单细胞生态基石 (带脏后缀)
    ]
    
    for url in test_urls:
        print(f"👉 正在抓取: {url}")
        metrics = crawler.fetch_repo_metrics(url)
        
        if "error" in metrics:
            print(f"   ❌ 失败: {metrics['error']}")
        else:
            print(f"   ✅ 成功: {metrics['tool_name']}")
            print(f"      ⭐ Stars: {metrics['github_stars']} | 🍴 Forks: {metrics['forks']}")
            print(f"      🕒 最近更新: {metrics['last_updated']} | 💻 语言: {metrics['language']}")
        print("-" * 40)
        time.sleep(1) # 礼貌性休眠，防止被封 IP
