#!/usr/bin/env python3
"""财经秘书日报生成脚本 - 独立于 WorkBuddy，通过 yfinance 获取全球市场数据"""

import yfinance as yf
import json
import os
import sys
import math
from datetime import datetime, timedelta

# ─── 配置 ───────────────────────────────────────────
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
MORNING_DIR = os.path.join(OUTPUT_DIR, "morning")
EVENING_DIR = os.path.join(OUTPUT_DIR, "evening")

TICKERS = {
    "us": {
        "DJI": {"code": "^DJI", "name": "道琼斯工业指数"},
        "IXIC": {"code": "^IXIC", "name": "纳斯达克综合指数"},
        "SPX": {"code": "^GSPC", "name": "标普500指数"},
    },
    "cn": {
        "SH": {"code": "000001.SS", "name": "上证指数"},
        "SZ": {"code": "399001.SZ", "name": "深证成指"},
        "CY": {"code": "399006.SZ", "name": "创业板指"},
    },
    "hk": {
        "HSI": {"code": "^HSI", "name": "恒生指数"},
        "HSTECH": {"code": "HSTECH.HK", "name": "恒生科技"},
    },
    "jp_kr": {
        "N225": {"code": "^N225", "name": "日经225"},
        "KOSPI": {"code": "^KS11", "name": "韩国KOSPI"},
    },
    "commodity": {
        "GOLD": {"code": "GC=F", "name": "COMEX黄金"},
        "OIL": {"code": "CL=F", "name": "WTI原油"},
    },
    "forex": {
        "USDCNY": {"code": "USDCNY=X", "name": "美元人民币"},
        "DXY": {"code": "DX-Y.NYB", "name": "美元指数"},
    },
}


def fmt_price(v):
    """格式化价格，保留2位小数"""
    try:
        return f"{float(v):,.2f}"
    except (TypeError, ValueError):
        return "数据暂缺"


def fmt_change(v):
    """格式化涨跌幅，带正负号"""
    try:
        val = float(v)
        if math.isnan(val):
            return "数据暂缺"
        return f"{val:+.2f}%"
    except (TypeError, ValueError):
        return "数据暂缺"


def fmt_volume(v):
    """格式化成交量（亿）"""
    try:
        val = float(v)
        if val > 1e8:
            return f"{val/1e8:.2f}亿"
        return f"{val:,.0f}"
    except (TypeError, ValueError):
        return ""


def fmt_val(v, unit=""):
    """格式化数值"""
    try:
        return f"{float(v):,.2f}{unit}"
    except (TypeError, ValueError):
        return "数据暂缺"


def up_down(v):
    """判断涨跌: 'up' / 'down' / '' """
    try:
        val = float(v)
        if math.isnan(val):
            return ""
        return "up" if val > 0 else "down" if val < 0 else ""
    except (TypeError, ValueError):
        return ""


def up_down_color(v):
    """涨跌颜色: 红涨绿跌"""
    try:
        val = float(v)
        if math.isnan(val):
            return "#999"
        return "#e74c3c" if val > 0 else "#27ae60" if val < 0 else "#999"
    except (TypeError, ValueError):
        return "#999"


def _is_valid(v):
    """检查数值是否有效（非None、非NaN）"""
    if v is None:
        return False
    try:
        if math.isnan(float(v)):
            return False
    except (TypeError, ValueError):
        return False
    return True


def fetch_data(ticker_group):
    """批量获取 ticker 数据，fast_info 无效时 fallback 到 history"""
    results = {}
    for key, info in ticker_group.items():
        code = info["code"]
        price = None
        prev_close = None
        change_pct = None
        volume = None
        error_msg = None

        try:
            t = yf.Ticker(code)
            # 1. 尝试 fast_info（最快）
            fi = t.fast_info
            price = fi.get("lastPrice") or fi.get("regularMarketPreviousClose") or fi.get("previousClose")
            prev_close = fi.get("regularMarketPreviousClose") or fi.get("previousClose")
            volume = fi.get("lastVolume") or fi.get("regularMarketVolume") or fi.get("volume")

            # 验证 fast_info 数据有效性
            if not _is_valid(price) or not _is_valid(prev_close):
                price = None
                prev_close = None

            # 2. fallback: 使用 history(2d) 获取最近两天收盘价
            if not _is_valid(price) or not _is_valid(prev_close):
                try:
                    hist = t.history(period="5d")
                    if hist is not None and len(hist) >= 2:
                        price = hist["Close"].iloc[-1]
                        prev_close = hist["Close"].iloc[-2]
                        volume = hist["Volume"].iloc[-1]
                except Exception as e2:
                    pass  # history fallback 失败，继续保留 None

            # 计算涨跌幅
            if _is_valid(price) and _is_valid(prev_close) and prev_close != 0:
                change_pct = round((price - prev_close) / prev_close * 100, 2)

        except Exception as e:
            error_msg = str(e)

        results[key] = {
            "name": info["name"],
            "code": code,
            "price": price if _is_valid(price) else None,
            "prev_close": prev_close if _is_valid(prev_close) else None,
            "change_pct": change_pct if _is_valid(change_pct) else None,
            "volume": volume if _is_valid(volume) else None,
            "error": error_msg,
        }
    return results


# ─── HTML 生成 ──────────────────────────────────────

MORNING_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>财经早盘简报 | {date_str}</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", Roboto, sans-serif; background: #f5f6fa; color: #333; padding: 16px; }}
  .container {{ max-width: 800px; margin: 0 auto; }}
  .header {{ background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); color: #fff; padding: 28px 24px; border-radius: 14px; margin-bottom: 18px; text-align: center; }}
  .header h1 {{ font-size: 22px; font-weight: 700; margin-bottom: 4px; }}
  .header .date {{ font-size: 13px; opacity: 0.7; }}
  .section {{ background: #fff; border-radius: 14px; padding: 22px; margin-bottom: 16px; box-shadow: 0 1px 6px rgba(0,0,0,0.05); }}
  .section h2 {{ font-size: 16px; font-weight: 700; color: #1a1a2e; margin-bottom: 16px; padding-left: 12px; border-left: 3px solid #e74c3c; }}
  .cards {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }}
  .cards-2 {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }}
  .card {{ background: #f8f9fc; border-radius: 10px; padding: 16px 12px; text-align: center; }}
  .card .label {{ font-size: 11px; color: #999; margin-bottom: 6px; }}
  .card .value {{ font-size: 19px; font-weight: 700; color: #1a1a2e; }}
  .card .change {{ font-size: 13px; font-weight: 600; margin-top: 4px; }}
  .card .vol {{ font-size: 11px; color: #aaa; margin-top: 3px; }}
  .chart-box {{ width: 100%; height: 320px; margin-top: 16px; }}
  .commodity-row {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }}
  .commodity-item {{ text-align: center; padding: 12px 8px; background: #f8f9fc; border-radius: 10px; }}
  .commodity-item .name {{ font-size: 11px; color: #999; }}
  .commodity-item .val {{ font-size: 16px; font-weight: 700; color: #1a1a2e; margin-top: 4px; }}
  .commodity-item .chg {{ font-size: 12px; font-weight: 600; margin-top: 3px; }}
  .up {{ color: #e74c3c; }} .down {{ color: #27ae60; }}
  .footer {{ text-align: center; color: #bbb; font-size: 11px; margin-top: 24px; padding-bottom: 20px; }}
  @media (max-width: 600px) {{ .cards, .cards-2 {{ grid-template-columns: 1fr; }} .commodity-row {{ grid-template-columns: repeat(2, 1fr); }} }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>财经早盘简报</h1>
    <div class="date">{date_str} {weekday}</div>
  </div>

  <div class="section">
    <h2>隔夜美股收盘</h2>
    <div class="cards">
      <div class="card">
        <div class="label">道琼斯工业指数</div>
        <div class="value">{us_dji_price}</div>
        <div class="change {us_dji_updown}">{us_dji_change}</div>
      </div>
      <div class="card">
        <div class="label">纳斯达克综合指数</div>
        <div class="value">{us_ixic_price}</div>
        <div class="change {us_ixic_updown}">{us_ixic_change}</div>
      </div>
      <div class="card">
        <div class="label">标普500指数</div>
        <div class="value">{us_spx_price}</div>
        <div class="change {us_spx_updown}">{us_spx_change}</div>
      </div>
    </div>
    <div id="usChart" class="chart-box"></div>
  </div>

  <div class="section">
    <h2>亚太盘前前瞻</h2>
    <div class="cards-2">
      <div class="card"><div class="label">上证指数</div><div class="value">{cn_sh_price}</div><div class="change {cn_sh_updown}">{cn_sh_change}</div></div>
      <div class="card"><div class="label">深证成指</div><div class="value">{cn_sz_price}</div><div class="change {cn_sz_updown}">{cn_sz_change}</div></div>
      <div class="card"><div class="label">创业板指</div><div class="value">{cn_cy_price}</div><div class="change {cn_cy_updown}">{cn_cy_change}</div></div>
      <div class="card"><div class="label">恒生指数</div><div class="value">{hk_hsi_price}</div><div class="change {hk_hsi_updown}">{hk_hsi_change}</div></div>
      <div class="card"><div class="label">恒生科技</div><div class="value">{hk_hstech_price}</div><div class="change {hk_hstech_updown}">{hk_hstech_change}</div></div>
      <div class="card"><div class="label">日经225</div><div class="value">{jp_price}</div><div class="change {jp_updown}">{jp_change}</div></div>
      <div class="card"><div class="label">韩国KOSPI</div><div class="value">{kr_price}</div><div class="change {kr_updown}">{kr_change}</div></div>
    </div>
  </div>

  <div class="section">
    <h2>大宗商品与外汇</h2>
    <div class="commodity-row">
      <div class="commodity-item"><div class="name">COMEX黄金</div><div class="val">${gold_price}</div><div class="chg {gold_updown}">{gold_change}</div></div>
      <div class="commodity-item"><div class="name">WTI原油</div><div class="val">${oil_price}</div><div class="chg {oil_updown}">{oil_change}</div></div>
      <div class="commodity-item"><div class="name">美元人民币</div><div class="val">{usdcny_price}</div><div class="chg {usdcny_updown}">{usdcny_change}</div></div>
      <div class="commodity-item"><div class="name">美元指数</div><div class="val">{dxy_price}</div><div class="chg {dxy_updown}">{dxy_change}</div></div>
    </div>
  </div>

  <div class="footer">
    由「财经秘书-早盘简报」自动生成 | 数据源：Yahoo Finance<br>
    数据仅供参考，不构成投资建议
  </div>
</div>

<script>
(function() {{
  var chart = echarts.init(document.getElementById('usChart'));
  var option = {{
    tooltip: {{ trigger: 'axis', formatter: '{{b}}: {{c}}%' }},
    grid: {{ left: 110, right: 50, top: 16, bottom: 16 }},
    xAxis: {{ type: 'value', unit: '%', axisLabel: {{ formatter: '{{value}}%' }} }},
    yAxis: {{ type: 'category', data: ['标普500', '纳斯达克', '道琼斯'], axisLabel: {{ fontSize: 12 }} }},
    series: [{{
      type: 'bar',
      data: [
        {{ value: {us_spx_chg_val}, itemStyle: {{ color: '{us_spx_color}' }} }},
        {{ value: {us_ixic_chg_val}, itemStyle: {{ color: '{us_ixic_color}' }} }},
        {{ value: {us_dji_chg_val}, itemStyle: {{ color: '{us_dji_color}' }} }}
      ],
      barWidth: 22,
      label: {{ show: true, position: 'right', formatter: '{{c}}%', fontSize: 12 }}
    }}]
  }};
  chart.setOption(option);
  window.addEventListener('resize', function() {{ chart.resize(); }});
}})();
</script>
</body>
</html>"""


EVENING_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>财经晚盘复盘 | {date_str}</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", Roboto, sans-serif; background: #f5f6fa; color: #333; padding: 16px; }}
  .container {{ max-width: 800px; margin: 0 auto; }}
  .header {{ background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); color: #fff; padding: 28px 24px; border-radius: 14px; margin-bottom: 18px; text-align: center; }}
  .header h1 {{ font-size: 22px; font-weight: 700; margin-bottom: 4px; }}
  .header .date {{ font-size: 13px; opacity: 0.7; }}
  .section {{ background: #fff; border-radius: 14px; padding: 22px; margin-bottom: 16px; box-shadow: 0 1px 6px rgba(0,0,0,0.05); }}
  .section h2 {{ font-size: 16px; font-weight: 700; color: #1a1a2e; margin-bottom: 16px; padding-left: 12px; border-left: 3px solid #e74c3c; }}
  .cards {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }}
  .card {{ background: #f8f9fc; border-radius: 10px; padding: 16px 12px; text-align: center; }}
  .card .label {{ font-size: 11px; color: #999; margin-bottom: 6px; }}
  .card .value {{ font-size: 19px; font-weight: 700; color: #1a1a2e; }}
  .card .change {{ font-size: 13px; font-weight: 600; margin-top: 4px; }}
  .card .vol {{ font-size: 11px; color: #aaa; margin-top: 3px; }}
  .chart-box {{ width: 100%; height: 380px; margin-top: 16px; }}
  .commodity-row {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }}
  .commodity-item {{ text-align: center; padding: 12px 8px; background: #f8f9fc; border-radius: 10px; }}
  .commodity-item .name {{ font-size: 11px; color: #999; }}
  .commodity-item .val {{ font-size: 16px; font-weight: 700; color: #1a1a2e; margin-top: 4px; }}
  .commodity-item .chg {{ font-size: 12px; font-weight: 600; margin-top: 3px; }}
  .status-tag {{ display: inline-block; padding: 2px 10px; border-radius: 4px; font-size: 11px; margin-left: 8px; }}
  .status-open {{ background: #e74c3c; color: #fff; }}
  .status-pre {{ background: #f39c12; color: #fff; }}
  .up {{ color: #e74c3c; }} .down {{ color: #27ae60; }}
  .footer {{ text-align: center; color: #bbb; font-size: 11px; margin-top: 24px; padding-bottom: 20px; }}
  @media (max-width: 600px) {{ .cards {{ grid-template-columns: 1fr; }} .commodity-row {{ grid-template-columns: repeat(2, 1fr); }} }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>财经晚盘复盘</h1>
    <div class="date">{date_str} {weekday}</div>
  </div>

  <div class="section">
    <h2>亚太股市收盘</h2>
    <div class="cards">
      <div class="card"><div class="label">上证指数</div><div class="value">{cn_sh_price}</div><div class="change {cn_sh_updown}">{cn_sh_change}</div><div class="vol">{cn_sh_vol}</div></div>
      <div class="card"><div class="label">深证成指</div><div class="value">{cn_sz_price}</div><div class="change {cn_sz_updown}">{cn_sz_change}</div></div>
      <div class="card"><div class="label">创业板指</div><div class="value">{cn_cy_price}</div><div class="change {cn_cy_updown}">{cn_cy_change}</div></div>
    </div>
    <div class="cards" style="margin-top:12px;">
      <div class="card"><div class="label">恒生指数</div><div class="value">{hk_hsi_price}</div><div class="change {hk_hsi_updown}">{hk_hsi_change}</div></div>
      <div class="card"><div class="label">恒生科技</div><div class="value">{hk_hstech_price}</div><div class="change {hk_hstech_updown}">{hk_hstech_change}</div></div>
      <div class="card"><div class="label">日经225</div><div class="value">{jp_price}</div><div class="change {jp_updown}">{jp_change}</div></div>
    </div>
    <div class="cards" style="margin-top:12px; grid-template-columns: 1fr 1fr;">
      <div class="card"><div class="label">韩国KOSPI</div><div class="value">{kr_price}</div><div class="change {kr_updown}">{kr_change}</div></div>
    </div>
    <div id="asiaChart" class="chart-box"></div>
  </div>

  <div class="section">
    <h2>美股开盘速递 <span class="status-tag {us_status_class}">{us_status}</span></h2>
    <div class="cards">
      <div class="card">
        <div class="label">道琼斯工业指数</div>
        <div class="value">{us_dji_price}</div>
        <div class="change {us_dji_updown}">{us_dji_change}</div>
      </div>
      <div class="card">
        <div class="label">纳斯达克综合指数</div>
        <div class="value">{us_ixic_price}</div>
        <div class="change {us_ixic_updown}">{us_ixic_change}</div>
      </div>
      <div class="card">
        <div class="label">标普500指数</div>
        <div class="value">{us_spx_price}</div>
        <div class="change {us_spx_updown}">{us_spx_change}</div>
      </div>
    </div>
  </div>

  <div class="section">
    <h2>大宗商品与外汇</h2>
    <div class="commodity-row">
      <div class="commodity-item"><div class="name">COMEX黄金</div><div class="val">${gold_price}</div><div class="chg {gold_updown}">{gold_change}</div></div>
      <div class="commodity-item"><div class="name">WTI原油</div><div class="val">${oil_price}</div><div class="chg {oil_updown}">{oil_change}</div></div>
      <div class="commodity-item"><div class="name">美元人民币</div><div class="val">{usdcny_price}</div><div class="chg {usdcny_updown}">{usdcny_change}</div></div>
      <div class="commodity-item"><div class="name">美元指数</div><div class="val">{dxy_price}</div><div class="chg {dxy_updown}">{dxy_change}</div></div>
    </div>
  </div>

  <div class="footer">
    由「财经秘书-晚盘复盘」自动生成 | 数据源：Yahoo Finance<br>
    数据仅供参考，不构成投资建议
  </div>
</div>

<script>
(function() {{
  var chart = echarts.init(document.getElementById('asiaChart'));
  var option = {{
    tooltip: {{ trigger: 'axis', formatter: '{{b}}: {{c}}%' }},
    grid: {{ left: 100, right: 50, top: 16, bottom: 16 }},
    xAxis: {{ type: 'value', unit: '%', axisLabel: {{ formatter: '{{value}}%' }} }},
    yAxis: {{ type: 'category',
      data: ['韩国KOSPI', '日经225', '恒生科技', '恒生指数', '创业板指', '深证成指', '上证指数'],
      axisLabel: {{ fontSize: 11, color: '#333' }} }},
    series: [{{
      type: 'bar',
      data: [
        {{ value: {kr_chg_val}, itemStyle: {{ color: '{kr_color}' }} }},
        {{ value: {jp_chg_val}, itemStyle: {{ color: '{jp_color}' }} }},
        {{ value: {hk_hstech_chg_val}, itemStyle: {{ color: '{hk_hstech_color}' }} }},
        {{ value: {hk_hsi_chg_val}, itemStyle: {{ color: '{hk_hsi_color}' }} }},
        {{ value: {cn_cy_chg_val}, itemStyle: {{ color: '{cn_cy_color}' }} }},
        {{ value: {cn_sz_chg_val}, itemStyle: {{ color: '{cn_sz_color}' }} }},
        {{ value: {cn_sh_chg_val}, itemStyle: {{ color: '{cn_sh_color}' }} }}
      ],
      barWidth: 18,
      label: {{ show: true, position: 'right', formatter: '{{c}}%', fontSize: 11 }}
    }}]
  }};
  chart.setOption(option);
  window.addEventListener('resize', function() {{ chart.resize(); }});
}})();
</script>
</body>
</html>"""


def generate_morning(data_us, data_cn, data_hk, data_jpkr, data_comm, data_fx):
    """生成早盘简报 HTML"""
    now = datetime.now()
    date_str = now.strftime("%Y年%m月%d日")
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    weekday = weekdays[now.weekday()]

    # Helper to get data or default
    def g(d, k, field, default="数据暂缺"):
        item = d.get(k, {})
        v = item.get(field, None)
        if v is None:
            return default
        return v

    def gp(d, k):
        return fmt_price(g(d, k, "price"))
    def gc(d, k):
        return fmt_change(g(d, k, "change_pct"))
    def gud(d, k):
        return up_down(g(d, k, "change_pct"))
    def gchg(d, k):
        v = g(d, k, "change_pct", None)
        try:
            val = float(v)
            if math.isnan(val):
                return 0
            return val
        except (TypeError, ValueError):
            return 0
    def gcol(d, k):
        return up_down_color(g(d, k, "change_pct", None))

    # Build HTML
    html = MORNING_HTML.format(
        date_str=date_str,
        weekday=weekday,
        # US
        us_dji_price=gp(data_us, "DJI"),
        us_dji_change=gc(data_us, "DJI"),
        us_dji_updown=gud(data_us, "DJI"),
        us_ixic_price=gp(data_us, "IXIC"),
        us_ixic_change=gc(data_us, "IXIC"),
        us_ixic_updown=gud(data_us, "IXIC"),
        us_spx_price=gp(data_us, "SPX"),
        us_spx_change=gc(data_us, "SPX"),
        us_spx_updown=gud(data_us, "SPX"),
        # Chart data
        us_dji_chg_val=gchg(data_us, "DJI"),
        us_dji_color=gcol(data_us, "DJI"),
        us_ixic_chg_val=gchg(data_us, "IXIC"),
        us_ixic_color=gcol(data_us, "IXIC"),
        us_spx_chg_val=gchg(data_us, "SPX"),
        us_spx_color=gcol(data_us, "SPX"),
        # CN
        cn_sh_price=gp(data_cn, "SH"),
        cn_sh_change=gc(data_cn, "SH"),
        cn_sh_updown=gud(data_cn, "SH"),
        cn_sz_price=gp(data_cn, "SZ"),
        cn_sz_change=gc(data_cn, "SZ"),
        cn_sz_updown=gud(data_cn, "SZ"),
        cn_cy_price=gp(data_cn, "CY"),
        cn_cy_change=gc(data_cn, "CY"),
        cn_cy_updown=gud(data_cn, "CY"),
        # HK
        hk_hsi_price=gp(data_hk, "HSI"),
        hk_hsi_change=gc(data_hk, "HSI"),
        hk_hsi_updown=gud(data_hk, "HSI"),
        hk_hstech_price=gp(data_hk, "HSTECH"),
        hk_hstech_change=gc(data_hk, "HSTECH"),
        hk_hstech_updown=gud(data_hk, "HSTECH"),
        # JP/KR
        jp_price=gp(data_jpkr, "N225"),
        jp_change=gc(data_jpkr, "N225"),
        jp_updown=gud(data_jpkr, "N225"),
        kr_price=gp(data_jpkr, "KOSPI"),
        kr_change=gc(data_jpkr, "KOSPI"),
        kr_updown=gud(data_jpkr, "KOSPI"),
        # Commodities
        gold_price=fmt_val(g(data_comm, "GOLD", "price")),
        gold_change=gc(data_comm, "GOLD"),
        gold_updown=gud(data_comm, "GOLD"),
        oil_price=fmt_val(g(data_comm, "OIL", "price")),
        oil_change=gc(data_comm, "OIL"),
        oil_updown=gud(data_comm, "OIL"),
        # Forex
        usdcny_price=fmt_val(g(data_fx, "USDCNY", "price")),
        usdcny_change=gc(data_fx, "USDCNY"),
        usdcny_updown=gud(data_fx, "USDCNY"),
        dxy_price=fmt_val(g(data_fx, "DXY", "price")),
        dxy_change=gc(data_fx, "DXY"),
        dxy_updown=gud(data_fx, "DXY"),
    )
    return html


def generate_evening(data_us, data_cn, data_hk, data_jpkr, data_comm, data_fx):
    """生成晚盘复盘 HTML"""
    now = datetime.now()
    date_str = now.strftime("%Y年%m月%d日")
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    weekday = weekdays[now.weekday()]

    def g(d, k, field, default="数据暂缺"):
        item = d.get(k, {})
        v = item.get(field, None)
        if v is None:
            return default
        return v

    def gp(d, k):
        return fmt_price(g(d, k, "price"))
    def gc(d, k):
        return fmt_change(g(d, k, "change_pct"))
    def gud(d, k):
        return up_down(g(d, k, "change_pct"))
    def gchg(d, k):
        v = g(d, k, "change_pct", None)
        try:
            val = float(v)
            if math.isnan(val):
                return 0
            return val
        except (TypeError, ValueError):
            return 0
    def gcol(d, k):
        return up_down_color(g(d, k, "change_pct", None))

    # Determine US market status (before 9:30 PM CST = pre-market)
    us_hour = now.hour
    us_minute = now.minute
    us_is_open = (us_hour >= 21 and us_minute >= 30) or us_hour >= 22
    us_status = "已开盘" if us_is_open else "尚未开盘"
    us_status_class = "status-open" if us_is_open else "status-pre"

    html = EVENING_HTML.format(
        date_str=date_str,
        weekday=weekday,
        # US
        us_dji_price=gp(data_us, "DJI"),
        us_dji_change=gc(data_us, "DJI"),
        us_dji_updown=gud(data_us, "DJI"),
        us_ixic_price=gp(data_us, "IXIC"),
        us_ixic_change=gc(data_us, "IXIC"),
        us_ixic_updown=gud(data_us, "IXIC"),
        us_spx_price=gp(data_us, "SPX"),
        us_spx_change=gc(data_us, "SPX"),
        us_spx_updown=gud(data_us, "SPX"),
        us_status=us_status,
        us_status_class=us_status_class,
        # CN
        cn_sh_price=gp(data_cn, "SH"),
        cn_sh_change=gc(data_cn, "SH"),
        cn_sh_updown=gud(data_cn, "SH"),
        cn_sh_vol=fmt_volume(g(data_cn, "SH", "volume")),
        cn_sz_price=gp(data_cn, "SZ"),
        cn_sz_change=gc(data_cn, "SZ"),
        cn_sz_updown=gud(data_cn, "SZ"),
        cn_cy_price=gp(data_cn, "CY"),
        cn_cy_change=gc(data_cn, "CY"),
        cn_cy_updown=gud(data_cn, "CY"),
        # Chart CN data
        cn_sh_chg_val=gchg(data_cn, "SH"),
        cn_sh_color=gcol(data_cn, "SH"),
        cn_sz_chg_val=gchg(data_cn, "SZ"),
        cn_sz_color=gcol(data_cn, "SZ"),
        cn_cy_chg_val=gchg(data_cn, "CY"),
        cn_cy_color=gcol(data_cn, "CY"),
        # HK
        hk_hsi_price=gp(data_hk, "HSI"),
        hk_hsi_change=gc(data_hk, "HSI"),
        hk_hsi_updown=gud(data_hk, "HSI"),
        hk_hstech_price=gp(data_hk, "HSTECH"),
        hk_hstech_change=gc(data_hk, "HSTECH"),
        hk_hstech_updown=gud(data_hk, "HSTECH"),
        # Chart HK data
        hk_hsi_chg_val=gchg(data_hk, "HSI"),
        hk_hsi_color=gcol(data_hk, "HSI"),
        hk_hstech_chg_val=gchg(data_hk, "HSTECH"),
        hk_hstech_color=gcol(data_hk, "HSTECH"),
        # JP/KR
        jp_price=gp(data_jpkr, "N225"),
        jp_change=gc(data_jpkr, "N225"),
        jp_updown=gud(data_jpkr, "N225"),
        kr_price=gp(data_jpkr, "KOSPI"),
        kr_change=gc(data_jpkr, "KOSPI"),
        kr_updown=gud(data_jpkr, "KOSPI"),
        # Chart JP/KR
        jp_chg_val=gchg(data_jpkr, "N225"),
        jp_color=gcol(data_jpkr, "N225"),
        kr_chg_val=gchg(data_jpkr, "KOSPI"),
        kr_color=gcol(data_jpkr, "KOSPI"),
        # Commodities
        gold_price=fmt_val(g(data_comm, "GOLD", "price")),
        gold_change=gc(data_comm, "GOLD"),
        gold_updown=gud(data_comm, "GOLD"),
        oil_price=fmt_val(g(data_comm, "OIL", "price")),
        oil_change=gc(data_comm, "OIL"),
        oil_updown=gud(data_comm, "OIL"),
        # Forex
        usdcny_price=fmt_val(g(data_fx, "USDCNY", "price")),
        usdcny_change=gc(data_fx, "USDCNY"),
        usdcny_updown=gud(data_fx, "USDCNY"),
        dxy_price=fmt_val(g(data_fx, "DXY", "price")),
        dxy_change=gc(data_fx, "DXY"),
        dxy_updown=gud(data_fx, "DXY"),
    )
    return html


def write_report(html, filename, report_type):
    """写入 HTML 报告到 docs 目录"""
    dir_map = {"morning": MORNING_DIR, "evening": EVENING_DIR}
    out_dir = dir_map.get(report_type, OUTPUT_DIR)
    os.makedirs(out_dir, exist_ok=True)

    # Write latest
    index_path = os.path.join(out_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[OK] 已写入: {index_path}")

    # Write archive
    date_str = datetime.now().strftime("%Y-%m-%d")
    archive_path = os.path.join(out_dir, f"{date_str}.html")
    with open(archive_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[OK] 已归档: {archive_path}")

    return index_path


def is_scheduled_time():
    """检查是否在推送时间窗口内"""
    now = datetime.now()
    hour = now.hour
    minute = now.minute
    # 早报窗口: 07:55-08:10 CST (00:00 UTC for GitHub Actions)
    # 晚报窗口: 16:55-17:10 CST (09:00 UTC for GitHub Actions)
    return True  # Always generate when called


def write_homepage():
    """生成 docs/index.html 导航首页"""
    now = datetime.now()
    date_str = now.strftime("%Y年%m月%d日")
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    weekday = weekdays[now.weekday()]

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>财经秘书日报 | {date_str}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", Roboto, sans-serif; background: #f5f6fa; color: #333; padding: 16px; }}
  .container {{ max-width: 800px; margin: 0 auto; }}
  .header {{ background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); color: #fff; padding: 28px 24px; border-radius: 14px; margin-bottom: 18px; text-align: center; }}
  .header h1 {{ font-size: 22px; font-weight: 700; margin-bottom: 4px; }}
  .header .date {{ font-size: 13px; opacity: 0.7; }}
  .card {{ background: #fff; border-radius: 14px; padding: 22px; margin-bottom: 16px; box-shadow: 0 1px 6px rgba(0,0,0,0.05); display: block; text-decoration: none; color: inherit; transition: transform 0.2s, box-shadow 0.2s; }}
  .card:hover {{ transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.08); }}
  .card h2 {{ font-size: 16px; font-weight: 700; color: #1a1a2e; margin-bottom: 8px; padding-left: 12px; border-left: 3px solid #e74c3c; }}
  .card p {{ font-size: 13px; color: #888; margin-left: 15px; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; margin-left: 8px; }}
  .badge-morning {{ background: #3498db; color: #fff; }}
  .badge-evening {{ background: #9b59b6; color: #fff; }}
  .footer {{ text-align: center; color: #bbb; font-size: 11px; margin-top: 24px; padding-bottom: 20px; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>财经秘书日报</h1>
    <div class="date">{date_str} {weekday}</div>
  </div>

  <a href="morning/" class="card">
    <h2>早盘简报 <span class="badge badge-morning">08:00</span></h2>
    <p>隔夜美股收盘 | 亚太盘前前瞻 | 大宗商品与外汇</p>
  </a>

  <a href="evening/" class="card">
    <h2>晚盘复盘 <span class="badge badge-evening">17:00</span></h2>
    <p>亚太股市收盘 | 美股开盘速递 | 大宗商品与外汇</p>
  </a>

  <div class="footer">
    由「财经秘书」自动生成 | 数据源：Yahoo Finance<br>
    数据仅供参考，不构成投资建议
  </div>
</div>
</body>
</html>"""
    index_path = os.path.join(OUTPUT_DIR, "index.html")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[OK] 已写入首页: {index_path}")
    return index_path


def main():
    report_type = sys.argv[1] if len(sys.argv) > 1 else "morning"

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始生成{report_type}报告...")

    # Fetch all data
    data_us = fetch_data(TICKERS["us"])
    data_cn = fetch_data(TICKERS["cn"])
    data_hk = fetch_data(TICKERS["hk"])
    data_jpkr = fetch_data(TICKERS["jp_kr"])
    data_comm = fetch_data(TICKERS["commodity"])
    data_fx = fetch_data(TICKERS["forex"])

    # Generate HTML
    if report_type == "morning":
        html = generate_morning(data_us, data_cn, data_hk, data_jpkr, data_comm, data_fx)
    else:
        html = generate_evening(data_us, data_cn, data_hk, data_jpkr, data_comm, data_fx)

    # Write
    write_report(html, "index.html", report_type)

    # Generate homepage
    write_homepage()

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {report_type}报告生成完成")


if __name__ == "__main__":
    main()
