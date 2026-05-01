#!/usr/bin/env python3
"""
微信公众号敏感词一键过滤器
用法：
  python sensitive_filter.py -i article.md -o article_safe.md
  python sensitive_filter.py -d docs/wechat  # 批量处理整个文件夹
  python sensitive_filter.py -e dict.json    # 导出当前词库
"""
import re
import json
import argparse
from pathlib import Path
from typing import Dict

# 核心敏感词映射（长词优先，避免误杀）
SENSITIVE_MAP = {
    # 机构 & 品牌
    "澳门": "市场",
    "Bet365": "主流市场",
    "立博": "主流市场",
    "威廉": "主流市场",
    "主流机构": "主流市场",
    "机构": "市场",
    
    # 玩法 & 术语
    "竞彩": "赛场观察",
    "胜平负": "方向",
    "让球胜": "让球方向",
    "让球负": "让球反向",
    "串关": "组合",
    "二串一": "双赛组合",
    "命中率": "命中比例",
    "回血": "回归",
    "复利": "复合收益",
    "稳赚": "稳健",
    "包红": "高命中",
    "投注": "参考",
    "下注": "介入",
    "购彩": "参考",
    
    # 盘口 & 水位
    "盘口": "让步定位",
    "水位": "赔付区间",
    "中水": "中位赔付",
    "高水": "高赔付区间",
    "低水": "低赔付区间",
    "升盘": "提升让步",
    "降盘": "降低让步",
    "半球": "半档",
    "一球": "一档",
    "平手盘": "均衡定位",
    "让球": "让步",
    "受热": "受关注",
    "筹码": "资金",
    "诱盘": "诱导流向",
    "阻盘": "设置阻力",
    
    # 赔率数字（正则捕获，统一处理）
    r"主胜1\.51": "主胜估值偏低",
    r"2\.20": "中位赔付",
    r"0\.80": "低赔付区间",
    r"1\.42": "偏低赔付",
    
    # 导流 & 营销
    "扫码": "查看",
    "加我": "联系",
    "开通": "获取",
    "会员": "用户",
    "价格": "费用",
    "续费": "续订",
}

# 预编译正则（长词优先，避免短词误杀）
_REGEX_MAP = {re.compile(k): v for k, v in SENSITIVE_MAP.items()}


def replace_sensitive(text: str, custom_map: Dict[str, str] = None) -> str:
    """
    替换敏感词，优先长词，保留大小写与格式
    """
    if custom_map:
        _REGEX_MAP.update({re.compile(k): v for k, v in custom_map.items()})

    # 按关键词长度降序，避免短词误杀
    sorted_items = sorted(
        _REGEX_MAP.items(), key=lambda x: len(x[0].pattern), reverse=True
    )
    for pattern, repl in sorted_items:
        text = pattern.sub(repl, text)
    return text


def process_file(input_path: Path, output_path: Path, custom_map: Dict[str, str] = None):
    """
    处理单个 Markdown 文件
    """
    content = input_path.read_text(encoding="utf-8")
    cleaned = replace_sensitive(content, custom_map)
    output_path.write_text(cleaned, encoding="utf-8")
    print(f"✅ 已输出合规文件：{output_path}")


def process_folder(folder: Path, suffix: str = "_safe", custom_map: Dict[str, str] = None):
    """
    批量处理文件夹内所有 .md 文件
    """
    for md_file in folder.rglob("*.md"):
        out_file = md_file.with_name(md_file.stem + suffix + md_file.suffix)
        process_file(md_file, out_file, custom_map)
    print("✅ 批量处理完成")


def export_dict(path: Path):
    """
    导出当前词库为 JSON，方便人工二次编辑
    """
    path.write_text(json.dumps(SENSITIVE_MAP, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 词库已导出：{path}")


def main():
    parser = argparse.ArgumentParser(description="微信公众号敏感词过滤器")
    parser.add_argument("-i", "--input", type=Path, help="输入 Markdown 文件")
    parser.add_argument("-o", "--output", type=Path, help="输出文件（默认：原文件名+_safe）")
    parser.add_argument("-d", "--dir", type=Path, help="批量处理整个文件夹")
    parser.add_argument("-e", "--export", type=Path, help="导出当前词库 JSON")
    parser.add_argument("--custom", type=Path, help="自定义映射 JSON 文件")
    args = parser.parse_args()

    custom_map = {}
    if args.custom:
        custom_map = json.loads(args.custom.read_text(encoding="utf-8"))

    if args.export:
        export_dict(args.export)
        return

    if args.dir:
        process_folder(args.dir, custom_map=custom_map)
        return

    if args.input:
        out = args.output or args.input.with_name(args.input.stem + "_safe" + args.input.suffix)
        process_file(args.input, out, custom_map)
        return

    parser.print_help()


if __name__ == "__main__":
    main()