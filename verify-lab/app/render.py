"""HTML 模板 + 无头浏览器截图 —— 对照原项目 one/img_generator.py

原项目干的事：把写死的 HTML（Penn State LionPATH 课程表）渲染成 PNG，
冒充真实学生系统截图，再提交给 SheerID。

这里保留完全相同的技术链路（模板 → 渲染 → 截图），但内容换成一张
明确标注 "SAMPLE / 教学用途" 的结业证书，不冒充任何真实机构。

两种后端：
- pillow    ：零依赖，当前环境直接能跑，画出 PNG；
- playwright：如果装了，走真正的 "HTML → 浏览器截图" 流程（更接近原项目）。
"""
from __future__ import annotations

import os
import re
from datetime import date
from functools import lru_cache
from html import escape
from pathlib import Path

CERT_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
  body {{ margin: 0; background: #e9eef5; font-family: Georgia, "Times New Roman", serif; }}
  .cert {{ width: 1000px; height: 700px; background: #fff; margin: 0 auto; padding: 48px;
           box-sizing: border-box; border: 14px solid #1e3a5f; position: relative; }}
  h1 {{ font-size: 40px; letter-spacing: 6px; color: #1e3a5f; text-align: center; margin: 0; }}
  .sub {{ text-align: center; color: #7a8ba0; letter-spacing: 3px; margin-top: 8px; }}
  .name {{ text-align: center; font-size: 46px; color: #12253d; margin: 46px 0 10px;
           border-bottom: 2px solid #c9a227; display: inline-block; padding: 0 28px 8px;
           max-width: 820px; overflow-wrap: anywhere; }}
  .name-wrap {{ text-align: center; }}
  .body {{ text-align: center; font-size: 19px; color: #33475f; line-height: 1.9; margin-top: 26px; }}
  .body b {{ overflow-wrap: anywhere; }}
  .meta {{ display: flex; justify-content: space-between; margin-top: 64px;
           font-size: 15px; color: #5a6b7f; }}
  .seal {{ position: absolute; right: 72px; bottom: 60px; width: 118px; height: 118px;
           border: 3px solid #c9a227; border-radius: 50%; color: #c9a227;
           display: flex; align-items: center; justify-content: center;
           text-align: center; font-size: 12px; line-height: 1.4; transform: rotate(-12deg); }}
  .sample {{ position: absolute; left: 72px; bottom: 66px; font-size: 12px; color: #b0bccb; }}
</style>
</head>
<body>
  <div class="cert">
    <h1>CERTIFICATE</h1>
    <div class="sub">OF COMPLETION &nbsp;·&nbsp; 结业证书</div>
    <div class="name-wrap"><div class="name">{name}</div></div>
    <div class="body">
      完成了 <b>{course}</b> 的全部学习内容<br>
      学习时长 {hours} 小时 · 成绩 {score} 分
    </div>
    <div class="seal">VERIFY<br>LAB<br>SAMPLE</div>
    <div class="meta">
      <span>证书编号：{serial}</span>
      <span>签发日期：{date}</span>
    </div>
    <div class="sample">本证书为教学示例，由 verify-lab 生成，不具备任何效力</div>
  </div>
</body>
</html>
"""

_FONTS = {
    "serif_bold": [r"C:\Windows\Fonts\georgiab.ttf", r"C:\Windows\Fonts\timesbd.ttf",
                   "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"],
    "serif": [r"C:\Windows\Fonts\georgia.ttf", r"C:\Windows\Fonts\times.ttf",
              "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
              "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"],
    # 中文字体：Arial 没有汉字字形，必须用雅黑/黑体/宋体/Noto CJK，否则会画成方框
    "sans": [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf",
             r"C:\Windows\Fonts\simsun.ttc", r"C:\Windows\Fonts\arial.ttf",
             "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    "name_cjk": [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf",
                 r"C:\Windows\Fonts\simsun.ttc",
                 "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
                 "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"],
}


@lru_cache(maxsize=None)
def _font(kind: str, size: int):
    from PIL import ImageFont
    for path in _FONTS[kind]:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _has_cjk(text: str) -> bool:
    return any(
        "\u3400" <= ch <= "\u9fff" or "\uf900" <= ch <= "\ufaff"
        for ch in text
    )


def _normalize_text(value: object, limit: int) -> str:
    """单行化 + 截断；证书是固定尺寸，不能让换行/超长文本把版式冲垮。"""
    text = " ".join(str(value).replace("\x00", " ").split())
    if not text:
        return "（未命名）"
    return text if len(text) <= limit else text[: max(1, limit - 1)] + "…"


def _safe_filename(value: object) -> str:
    """证书编号会进文件名，禁止路径分隔符和 ..，避免目录穿越。"""
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value)).strip(".-")
    return text[:96] or "certificate"


def render_html(name: str, course: str, hours: int, score: int,
                serial: str, issue_date: str | None = None) -> str:
    # 这些值来自 Telegram 用户输入，必须转义后再进 HTML。
    # 否则课程名里的 <script>/<img> 会在 Playwright 里被当成标记执行。
    safe_name = escape(_normalize_text(name, 48), quote=True)
    safe_course = escape(_normalize_text(course, 80), quote=True)
    safe_serial = escape(_normalize_text(serial, 96), quote=True)
    safe_date = escape(str(issue_date or date.today().isoformat()), quote=True)
    return CERT_HTML.format(name=safe_name, course=safe_course, hours=int(hours),
                            score=int(score), serial=safe_serial, date=safe_date)


def render_with_pillow(html_ignored: str, name: str, course: str, hours: int, score: int,
                       serial: str, issue_date: str, out_path: Path) -> Path:
    """用 Pillow 直接绘制（等价于"渲染模板"这一步，只是不用浏览器）。"""
    from PIL import Image, ImageDraw

    W, H = 1000, 700
    img = Image.new("RGB", (W, H), "#ffffff")
    d = ImageDraw.Draw(img)

    d.rectangle([0, 0, W - 1, H - 1], outline="#1e3a5f", width=14)
    d.rectangle([26, 26, W - 27, H - 27], outline="#c9a227", width=2)

    def center(text, y, font, fill="#1e3a5f"):
        w = d.textbbox((0, 0), text, font=font)[2]
        d.text(((W - w) / 2, y), text, font=font, fill=fill)

    def fit(text: str, kind: str, size: int, max_width: int):
        """固定画布上，长名字/长课程名自动缩小字号，避免画出边界。"""
        while size > 10:
            candidate = _font(kind, size)
            if d.textbbox((0, 0), text, font=candidate)[2] <= max_width:
                return candidate
            size -= 2
        return _font(kind, 10)

    center("CERTIFICATE", 78, _font("serif_bold", 46))
    center("OF COMPLETION  ·  结业证书", 140, _font("sans", 18), "#7a8ba0")

    f_name = fit(name, "name_cjk" if _has_cjk(name) else "serif_bold", 50, 860)
    w = d.textbbox((0, 0), name, font=f_name)[2]
    d.text(((W - w) / 2, 230), name, font=f_name, fill="#12253d")
    d.line([(W / 2 - w / 2 - 20, 296), (W / 2 + w / 2 + 20, 296)], fill="#c9a227", width=2)

    course_line = f"完成了 {course} 的全部学习内容"
    center(course_line, 340, fit(course_line, "sans", 20, 900), "#33475f")
    center(f"学习时长 {hours} 小时 · 成绩 {score} 分", 382, _font("sans", 20), "#33475f")

    d.text((92, 596), f"证书编号：{serial}", font=_font("sans", 15), fill="#5a6b7f")
    w2 = d.textbbox((0, 0), f"签发日期：{issue_date}", font=_font("sans", 15))[2]
    d.text((W - 92 - w2, 596), f"签发日期：{issue_date}", font=_font("sans", 15), fill="#5a6b7f")

    # 印章（放在日期上方，避免压字）
    cx, cy, r = W - 160, H - 210, 62
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline="#c9a227", width=3)
    center_seal = ["VERIFY", "LAB", "SAMPLE"]
    for i, line in enumerate(center_seal):
        f = _font("sans", 13)
        w3 = d.textbbox((0, 0), line, font=f)[2]
        d.text((cx - w3 / 2, cy - 24 + i * 17), line, font=f, fill="#c9a227")

    d.text((92, 642), "本证书为教学示例，由 verify-lab 生成，不具备任何效力",
           font=_font("sans", 12), fill="#b0bccb")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


def render_with_playwright(html: str, out_path: Path) -> Path:
    """真正的原项目链路：set_content → 全页截图。需要 pip install playwright。"""
    from playwright.sync_api import sync_playwright

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1080, "height": 760}, device_scale_factor=2)
        page.set_content(html, wait_until="load")
        page.screenshot(path=str(out_path), full_page=True)
        browser.close()
    return out_path


def render_certificate(name: str, course: str, hours: int, score: int, serial: str,
                       out_dir: str | Path = "outputs", backend: str | None = None) -> Path:
    """统一入口：auto 优先 Playwright，装不上就回退 Pillow。

    backend 默认可由环境变量 RENDER_BACKEND 指定（pillow / playwright / auto），
    服务器上没装 Chromium 时直接设 pillow，省掉一次必然失败的尝试。
    """
    backend = backend or os.getenv("RENDER_BACKEND", "auto")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = _normalize_text(name, 48)
    course = _normalize_text(course, 80)
    serial = _safe_filename(serial)
    issue_date = date.today().isoformat()
    html = render_html(name, course, hours, score, serial, issue_date)
    (out_dir / f"{serial}.html").write_text(html, encoding="utf-8")   # 模板始终落盘，方便对比

    png = out_dir / f"{serial}.png"
    if backend in ("auto", "playwright"):
        try:
            return render_with_playwright(html, png)
        except Exception as exc:            # 没装 playwright / 没装 chromium
            if backend == "playwright":
                raise
            print(f"[render] Playwright 不可用（{type(exc).__name__}），回退到 Pillow 绘制")
    return render_with_pillow(html, name, course, hours, score, serial, issue_date, png)
