from src.crawler.leisu_crawler import LeisuCrawler
from src.llm.predictor import LLMPredictor
from src.processor.data_fusion import _apply_leisu_data


def test_extract_swot_modules_parses_home_away_and_neutral_sections():
    body = (
        "斯特拉斯堡有利情报斯特拉斯堡身价≥巴列卡诺身价的3倍，阵容实力占优。"
        "近10场正赛多达8场比赛半场有得失球。"
        "不利情报首回合客场0比1告负，总比分落后1球。"
        "轮换后卫安塞尔米诺和主力前锋帕尼切利仍因伤缺席。"
        "中立情报斯洛伐克裁判伊万·克鲁日利亚克将执法本场比赛。"
        "巴列卡诺有利情报近6场欧协联比赛进攻端斩获11球表现相当惊艳。"
        "不利情报主力中卫费利佩与主力边锋加西亚双双伤缺。"
    )

    parsed = LeisuCrawler._extract_swot_modules(body, "斯特拉斯", "巴列卡诺")

    assert parsed["home_team"] == "斯特拉斯堡"
    assert parsed["away_team"] == "巴列卡诺"
    assert parsed["home"]["pros"]
    assert parsed["home"]["cons"]
    assert parsed["away"]["pros"]
    assert parsed["away"]["cons"]
    assert parsed["neutral"]


def test_format_leisu_intelligence_block_outputs_structured_lines():
    predictor = object.__new__(LLMPredictor)
    match_data = {
        "home_team": "斯特拉斯",
        "away_team": "巴列卡诺",
        "leisu_intelligence": {
            "home_team": "斯特拉斯堡",
            "away_team": "巴列卡诺",
            "home": {
                "pros": ["首回合落后回到主场具备反扑战意", "近10场正赛多达8场半场有球"],
                "cons": ["主力前锋帕尼切利仍因伤缺席"],
            },
            "away": {
                "pros": ["近6场欧协联进攻端斩获11球"],
                "cons": ["主力边锋加西亚伤缺"],
            },
            "neutral": ["裁判执法严格且依赖VAR"],
        },
    }

    lines = predictor._format_leisu_intelligence_block(match_data)

    assert any("情报要点-主队有利" in line for line in lines)
    assert any("情报要点-主队不利" in line for line in lines)
    assert any("情报要点-客队有利" in line for line in lines)
    assert any("情报要点-客队不利" in line for line in lines)
    assert any("情报要点-中立因素" in line for line in lines)


def test_build_swot_url_from_analysis_reuses_same_match_id():
    swot_url = LeisuCrawler._build_swot_url_from_analysis(
        "https://live.leisu.com/shujufenxi-4532045"
    )

    assert swot_url == "https://www.leisu.com/guide/swot-4532045"


def test_apply_leisu_data_keeps_structured_intelligence_for_predict_flow():
    match = {"home_team": "斯特拉斯", "away_team": "巴列卡诺"}
    leisu_data = {
        "injuries": "主队无重大伤停",
        "match_intelligence": {
            "home_team": "斯特拉斯堡",
            "away_team": "巴列卡诺",
            "home": {"pros": ["主场反扑战意强"], "cons": []},
            "away": {"pros": ["反击效率高"], "cons": ["主力边锋伤缺"]},
            "neutral": ["裁判尺度偏严格"],
        },
    }

    _apply_leisu_data(match, leisu_data)

    assert match["leisu_data"]["match_intelligence"]["home"]["pros"] == ["主场反扑战意强"]
    assert match["leisu_intelligence"]["away"]["cons"] == ["主力边锋伤缺"]


def test_extract_swot_modules_filters_navigation_and_footer_noise():
    body = (
        "首页 体育直播 赛事推荐 资讯中心 资料库 数据服务 APP下载 自媒体 登录 注册 情报对比 走势分析 "
        "弗赖堡 联赛排名德甲7 2026-05-08 03:00欧联 半决赛 进入聊天室 > 布拉加 联赛排名葡超4 "
        "有利情报弗赖堡近10场正赛多达7场比赛半场有得失球。"
        "弗赖堡本赛季近10个主场比赛，在领先的情况下最终主场赢球率达83%。"
        "不利情报弗赖堡近5场正赛连续失球，且场均丢球达2.0球。"
        "中立情报首回合比分为1比2。"
        "布拉加有利情报布拉加近九场正式比赛取得5胜3平1负。"
        "不利情报布拉加本赛季近10个客场比赛，在领先的情况下最终客场输球率达66%。"
        "以上各种走势数据截止时间：05月07日 19时47分，本文由雷速体育独家原创，内容仅供参考。"
        "热门雷速推荐 利雅得青年人 VS 利雅得胜利 点击查看 查看更多 关于雷速 网站地图 Copyright © 2015-2026 Leisu.ALL Rights Reserved"
    )

    parsed = LeisuCrawler._extract_swot_modules(body, "弗赖堡", "布拉加")

    assert parsed["home_team"] == "弗赖堡"
    assert parsed["away_team"] == "布拉加"
    assert parsed["home"]["pros"] == ["弗赖堡近10场正赛多达7场比赛半场有得失球", "弗赖堡本赛季近10个主场比赛，在领先的情况下最终主场赢球率达83%"]
    assert parsed["away"]["cons"] == ["布拉加本赛季近10个客场比赛，在领先的情况下最终客场输球率达66%"]
    assert all("雷速" not in item for item in parsed["away"]["cons"])
