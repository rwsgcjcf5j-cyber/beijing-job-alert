#!/usr/bin/env python3
"""Beijing recruitment leads digest. Official-site search leads, NOT eligibility verification."""
import datetime as dt
import email.utils
import html
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
SEARCHES = [
    ("北京市人社局招聘", "site:rsj.beijing.gov.cn 公开招聘 事业单位"),
    ("北京市国资委招聘", "site:gzw.beijing.gov.cn 招聘 社会招聘"),
    ("石景山区招聘", "site:bjshijingshan.gov.cn 招聘 社区工作者"),
    ("北京市政府招聘", "site:beijing.gov.cn 招聘 综合管理"),
]
ALLOWED = ("beijing.gov.cn", "bjshijingshan.gov.cn")
POSITIVE = ("招聘", "招录", "招考", "选聘", "招募")
NEGATIVE = ("拟聘", "录用公示", "成绩公示", "面试成绩", "资格复审", "面试公告", "体检公告")
PREFERRED = ("石景山", "综合管理", "采购", "运营", "经营分析", "行政", "国企", "社区工作者", "事业单位", "社会招聘")
USER_AGENT = "Mozilla/5.0 (compatible; BeijingJobAlert/1.0)"

def request(url, data=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=25) as response:
        return response.read()

def official(url):
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return any(host == domain or host.endswith("." + domain) for domain in ALLOWED)

def find_jobs():
    found, errors = {}, []
    now = dt.datetime.now(dt.timezone.utc)
    for label, query in SEARCHES:
        rss_url = "https://www.bing.com/search?format=rss&q=" + urllib.parse.quote(query)
        try:
            root = ET.fromstring(request(rss_url))
            entries = root.findall("./channel/item")
            if not entries:
                errors.append(label + "：搜索未返回结果")
            for item in entries:
                title = html.unescape(" ".join((item.findtext("title") or "").split()))
                link = (item.findtext("link") or "").strip()
                description = html.unescape(re.sub(r"<[^>]*>", " ", item.findtext("description") or ""))
                content = title + " " + description
                if not official(link) or not any(w in content for w in POSITIVE):
                    continue
                if any(w in title for w in NEGATIVE):
                    continue
                pub = item.findtext("pubDate")
                date_text = "日期未核实"
                if pub:
                    try:
                        published = email.utils.parsedate_to_datetime(pub)
                        if published.tzinfo is None:
                            published = published.replace(tzinfo=dt.timezone.utc)
                        if (now - published).days > 30:
                            continue
                        date_text = published.astimezone(TZ).strftime("%Y-%m-%d")
                    except (ValueError, TypeError):
                        pass
                score = sum(1 for word in PREFERRED if word in content)
                found[link] = {"title": title, "url": link, "source": label,
                               "date": date_text, "score": score}
        except Exception as exc:
            errors.append(label + "：搜索失败（" + type(exc).__name__ + "）")
    return sorted(found.values(), key=lambda x: (x["score"], x["date"]), reverse=True), errors

def digest(jobs, errors):
    date = dt.datetime.now(TZ).strftime("%Y-%m-%d")
    lines = [f"## 北京招聘线索日报｜{date}", "",
             "以下是公开搜索检索到的**招聘公告线索**，并非已核实仍在报名或符合个人资格的岗位。",
             "重点关注石景山区、事业单位、国企、社区及综合管理/采购/运营方向。", ""]
    if jobs:
        for index, job in enumerate(jobs[:12], 1):
            title = job["title"].replace("[", "［").replace("]", "］")
            lines.extend([f"{index}. **[{title}]({job['url']})**",
                          f"   来源：{job['source']}｜搜索日期：{job['date']}｜资格与截止日期：待核实", ""])
    else:
        lines.append("本次未检索到符合关键词的官方公告线索；不代表没有招聘。")
    lines.extend(["", "### 请核实", "公告是否仍接受报名、附件岗位表、学历性质、专业、年龄、户籍及其他资格。",
                  "搜索结果可能延迟或遗漏，且发布日期可能是搜索索引时间。"])
    if errors:
        lines.extend(["", "### 搜索异常", *["- " + e for e in errors]])
    return "\n".join(lines)

def main():
    key = os.environ.get("SERVERCHAN_SENDKEY", "").strip()
    if not key:
        print("Missing SERVERCHAN_SENDKEY secret", file=sys.stderr)
        return 1
    jobs, errors = find_jobs()
    message = digest(jobs, errors)
    title = f"北京招聘日报 {dt.datetime.now(TZ):%m-%d}｜{len(jobs)}条线索"
    payload = urllib.parse.urlencode({"title": title, "desp": message}).encode("utf-8")
    endpoint = "https://sctapi.ftqq.com/" + urllib.parse.quote(key, safe="") + ".send"
    try:
        response = request(endpoint, payload).decode("utf-8", errors="replace")
        import json
        result = json.loads(response)
        if result.get("code") != 0:
            print("ServerChan rejected request; code:", result.get("code"), file=sys.stderr)
            return 1
        print(f"Sent digest: {len(jobs)} leads, {len(errors)} source warnings")
        return 0
    except Exception as exc:
        print("ServerChan delivery failed:", type(exc).__name__, file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
