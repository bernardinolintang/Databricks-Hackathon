"""Fill the official DAISI Round 1 three-slide template for FlatFair.

Keeps the template frame (top bar, SLIDE N label, title, footer) and every
prompt, verbatim, as a label. Answers sit under each prompt; each slide gets
one visual. Run: python build_deck.py  ->  FlatFair_Round1_Deck.pptx
"""

from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION, XL_LABEL_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "daisi-round1-3-slide-template.pptx"
OUT = HERE / "FlatFair_Round1_Deck.pptx"
SCREENSHOT = HERE / "value-crop.png"

RED = RGBColor(0xFF, 0x36, 0x21)      # template accent
INK = RGBColor(0x11, 0x25, 0x30)      # template title colour
GRAY = RGBColor(0x6B, 0x7A, 0x84)     # template prompt colour
HAIR = RGBColor(0xD9, 0xDE, 0xE3)
CARD = RGBColor(0xF4, 0xF6, 0xF8)
TEAL = RGBColor(0x00, 0x92, 0x9C)     # FlatFair chart colour
FONT = "Arial"

LEFT = Inches(0.8)
TOP = Inches(1.95)
FOOTER_TEXT = "FlatFair · DAISI Challenge Singapore 2026 · Round 1 · Problem C1 · Live prototype: flatfair-nine.vercel.app"
TEAM_NAME = "‹Team name›"  # or: python build_deck.py --team "Your team"


# --------------------------------------------------------------------------- helpers
def run(paragraph, text, size=13, bold=False, color=INK):
    r = paragraph.add_run()
    r.text = text
    f = r.font
    f.name, f.size, f.bold, f.color.rgb = FONT, Pt(size), bold, color
    return r


def textbox(slide, x, y, w, h, name):
    box = slide.shapes.add_textbox(x, y, w, h)
    box.name = name
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    return box, tf


def qa_block(tf, label, parts, first=False, answer_size=13, space_before=10):
    """A template prompt as a small gray label, then the answer in ink.
    `parts` is a list of (text, bold) runs."""
    p = tf.paragraphs[0] if first else tf.add_paragraph()
    p.space_before = Pt(0 if first else space_before)
    p.space_after = Pt(2)
    run(p, label, size=11, color=GRAY)
    a = tf.add_paragraph()
    a.line_spacing = 1.08
    for text, bold in parts:
        run(a, text, size=answer_size, bold=bold)
    return a


def frame(slide):
    """Return the template's own shapes by name, and drop its prompt body."""
    shapes = {s.name: s for s in slide.shapes}
    body = shapes["TextBox 4"]
    body._element.getparent().remove(body._element)
    footer = shapes["TextBox 5"]
    para = footer.text_frame.paragraphs[0]
    para.runs[0].text = FOOTER_TEXT
    for extra in para.runs[1:]:
        extra.text = ""
    return shapes


# --------------------------------------------------------------------------- slide 1
def slide_problem(slide):
    frame(slide)
    box, tf = textbox(slide, LEFT, TOP, Inches(7.05), Inches(4.75), "Problem answers")

    p = tf.paragraphs[0]
    p.space_after = Pt(2)
    run(p, "Team name: ", size=11, color=GRAY)
    run(p, TEAM_NAME, size=13, bold=True, color=RED)
    p2 = tf.add_paragraph()
    p2.space_before = Pt(6)
    run(p2, "Problem statement (e.g. A2 — Ageing in place): ", size=11, color=GRAY)
    run(p2, "C1 — FlatFair: HDB resale market intelligence & affordability forecasting", size=13, bold=True)

    qa_block(tf, "The problem in one sentence:", [
        ("Young Singaporeans are making the biggest purchase of their lives in a market where HDB resale prices rose ", False),
        ("56% since 2017", True), (" while household incomes rose ", False), ("33%", True),
        (", with no transparent way to judge whether an asking price, or the repayment behind it, is reasonable.", False),
    ], space_before=12)
    qa_block(tf, "Who is affected, and how badly (use a number from open data):", [
        ("24,662 households", True), (" bought a resale flat in the last 12 months; ", False),
        ("1,847", True), (" of those flats sold for $1 million or more. A median 4-room flat now costs ", False),
        ("4.4 years", True), (" of the median household’s income, up from 3.8 in 2017.", False),
    ], space_before=12)
    qa_block(tf, "Why it matters now:", [
        ("After a 50% climb since 2020, prices have flattened (", False), ("+1.3% year on year", True),
        ("), so rising values no longer cover an overpayment. Since August 2024 an HDB loan needs a ", False),
        ("25% downpayment", True), (" instead of 20%, and the October 2024 Standard, Plus and Prime framework has reset expectations again.", False),
    ], space_before=12)

    # Visual: indexed price vs income, 2017 = 100 (annual medians from the pipeline)
    years = [str(y) for y in range(2017, 2026)]
    price = [410000, 408000, 400000, 425000, 483000, 525000, 550000, 590000, 628000]
    income = [9044, 9315, 9442, 9208, 9544, 10120, 10882, 11314, 12027]
    data = CategoryChartData()
    data.categories = years
    data.add_series("Median resale price", [round(v / price[0] * 100, 1) for v in price])
    data.add_series("Median household income", [round(v / income[0] * 100, 1) for v in income])

    title_box, ttf = textbox(slide, Inches(8.35), TOP, Inches(4.2), Inches(0.6), "Chart title")
    run(ttf.paragraphs[0], "Prices have outrun incomes", size=15, bold=True)
    sub = ttf.add_paragraph()
    run(sub, "Index, 2017 = 100", size=11, color=GRAY)

    gframe = slide.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS, Inches(8.2), Inches(2.6), Inches(4.4), Inches(3.45), data)
    gframe.name = "Price vs income chart"
    chart = gframe.chart
    chart.font.name, chart.font.size, chart.font.color.rgb = FONT, Pt(10), GRAY
    chart.has_legend = True
    chart.legend.position = XL_LEGEND_POSITION.BOTTOM
    chart.legend.include_in_layout = False
    chart.legend.font.size = Pt(10)
    va = chart.value_axis
    va.minimum_scale, va.maximum_scale, va.major_unit = 90, 160, 10
    va.has_major_gridlines = True
    va.major_gridlines.format.line.color.rgb = HAIR
    va.major_gridlines.format.line.width = Pt(0.75)
    va.format.line.fill.background()
    va.tick_labels.font.size = Pt(10)
    ca = chart.category_axis
    ca.format.line.color.rgb = HAIR
    ca.tick_labels.font.size = Pt(10)
    for series, color in zip(chart.plots[0].series, (RED, GRAY)):
        series.smooth = False
        series.format.line.color.rgb = color
        series.format.line.width = Pt(2.25)
        series.marker.size = 5
        series.marker.format.fill.solid()
        series.marker.format.fill.fore_color.rgb = color
        series.marker.format.line.color.rgb = color
        last = series.points[len(years) - 1]
        last.data_label.has_text_frame = False
        last.data_label.show_value = True
        last.data_label.position = XL_LABEL_POSITION.ABOVE
        last.data_label.font.size, last.data_label.font.bold = Pt(11), True
        last.data_label.font.color.rgb = color

    src_box, stf = textbox(slide, Inches(8.35), Inches(6.15), Inches(4.2), Inches(0.5), "Chart source")
    run(stf.paragraphs[0], "Annual medians. Sources: HDB resale flat prices (data.gov.sg); SingStat M810361 median monthly household employment income.", size=9, color=GRAY)


# --------------------------------------------------------------------------- slide 2
def slide_solution(slide):
    frame(slide)
    box, tf = textbox(slide, LEFT, TOP, Inches(7.05), Inches(4.8), "Solution answers")
    qa_block(tf, "Your solution in one sentence:", [
        ("FlatFair turns HDB’s resale records into a five-step decision tool that takes a buyer from ", False),
        ("“what is the market doing?”", True), (" to ", False), ("“is this flat, at this price, sensible for us?”", True),
    ], first=True)
    qa_block(tf, "Who uses it, and what decision it changes:", [
        ("First-time resale buyers, and the counsellors and planners who advise them. It changes ", False),
        ("where they look", True), (" (towns ranked by what the household can repay), ", False),
        ("what they offer", True), (" (asking price vs estimated value and the 5 closest sales) and ", False),
        ("when they buy", True), (" (a tested six-month outlook).", False),
    ])
    p = tf.add_paragraph()
    p.space_before, p.space_after = Pt(10), Pt(2)
    run(p, "Datasets you will use (name + source, e.g. data.gov.sg):", size=11, color=GRAY)
    datasets = [
        ("HDB Resale Flat Prices, Jan 2017 to present", " — data.gov.sg d_8b84c4ee…6abc, 241,822 sales"),
        ("Household Employment Income, key indicators (M810361)", " — SingStat Table Builder"),
        ("HDB Annual Report 2025 · Population by Planning Area", " — HDB, SingStat (supply and demand context)"),
    ]
    for i, (name, src) in enumerate(datasets, 1):
        d = tf.add_paragraph()
        d.space_after = Pt(1)
        run(d, f"{i}.  ", size=12, color=GRAY)
        run(d, name, size=12, bold=True)
        run(d, src, size=12)
    qa_block(tf, "What makes your approach different from a generic dashboard:", [
        ("It values a specific flat, not just the market: an 80% price range tested on ", False),
        ("13,589 sales it never saw", True), (" (median error ", False), ("3.9%", True),
        (" vs 9.5% for the $/sqm rule of thumb), plus repayment against the 30% MSR cap. Every model must beat a simple baseline: when a 3-month average out-forecast our ML model, we published the average.", False),
    ])

    # Visual: the working product
    pic = slide.shapes.add_picture(str(SCREENSHOT), Inches(8.45), TOP, height=Inches(4.0))
    pic.name = "Fair value screenshot"
    pic.line.color.rgb = HAIR
    pic.line.width = Pt(0.75)
    cap_y = pic.top + pic.height + Inches(0.12)
    cap, ctf = textbox(slide, Inches(8.45), cap_y, Inches(4.0), Inches(0.6), "Screenshot caption")
    run(ctf.paragraphs[0], "Working prototype: ", size=10, bold=True)
    run(ctf.paragraphs[0], "a Tampines 4-room asking $690,000 sits within the expected $612k–$710k range. flatfair-nine.vercel.app", size=10, color=GRAY)


# --------------------------------------------------------------------------- slide 3
def slide_architecture(slide):
    frame(slide)
    label, ltf = textbox(slide, LEFT, TOP, Inches(11.75), Inches(0.3), "Pipeline label")
    run(ltf.paragraphs[0], "Pipeline: source → ingestion → transform → model / analytics → output", size=11, color=GRAY)

    steps = [
        ("Source", "data.gov.sg API\nSingStat Table Builder API"),
        ("Ingestion", "Lakeflow Job runs notebooks\nretries · schema check → Bronze Delta"),
        ("Transform", "Silver & Gold Delta in Unity Catalog\n9 quality checks · flags, not deletes"),
        ("Model / analytics", "MLflow: forecast backtest, fair value\nmodel → UC registry · SQL / Genie"),
        ("Output", "Databricks App (FastAPI + JS)\npublic mirror on Vercel"),
    ]
    gap = Inches(0.32)
    width = int((Inches(11.75) - gap * (len(steps) - 1)) / len(steps))
    y, height = Inches(2.35), Inches(1.32)
    for i, (title, body) in enumerate(steps):
        x = LEFT + i * (width + gap)
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, width, height)
        card.name = f"Pipeline {i + 1} {title}"
        card.adjustments[0] = 0.08
        card.fill.solid()
        card.fill.fore_color.rgb = CARD
        card.line.fill.background()
        card.shadow.inherit = False
        tf = card.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = MSO_ANCHOR.TOP
        tf.margin_left = tf.margin_right = Inches(0.14)
        tf.margin_top, tf.margin_bottom = Inches(0.12), Inches(0.08)
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.LEFT
        run(p, f"{i + 1}  ", size=11, bold=True, color=RED)
        run(p, title, size=12, bold=True)
        for line in body.split("\n"):
            q = tf.add_paragraph()
            q.alignment = PP_ALIGN.LEFT
            q.space_before = Pt(3)
            run(q, line, size=10, color=INK)
        if i < len(steps) - 1:
            arrow = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, x + width + Inches(0.07), y + height / 2 - Inches(0.09), gap - Inches(0.14), Inches(0.18))
            arrow.name = f"Arrow {i + 1}"
            arrow.fill.solid()
            arrow.fill.fore_color.rgb = GRAY
            arrow.line.fill.background()
            arrow.shadow.inherit = False

    comp, ctf = textbox(slide, LEFT, Inches(3.8), Inches(11.75), Inches(0.45), "Components")
    run(ctf.paragraphs[0], "(Name the Databricks components) ", size=11, color=GRAY)
    run(ctf.paragraphs[0], "Lakeflow Jobs · Delta Lake · Unity Catalog (lineage, tags, model registry) · MLflow · Databricks SQL / AI-BI · Genie · Databricks Apps", size=12, bold=True)

    columns = [
        ("The user-facing output you will demo:", [
            ("The FlatFair app: ", True),
            ("market explorer, six-month forecast with its range, affordability with “Where can I afford?”, fair value with comparable sales, and town comparison. ", False),
            ("Already working end to end.", True),
        ]),
        ("Measurable impact if it worked:", [
            ("On a typical $630k flat the pricing blind spot narrows from ", False), ("~$60k to ~$25k", True),
            (" (rule-of-thumb vs model median error). Every buyer sees repayment against the 30% MSR cap before committing, refreshed monthly from open data.", False),
        ]),
        ("What you can realistically finish in the two-week sprint:", [
            ("Pipeline, both models, the app and 66 tests are built. ", True),
            ("Sprint: run it as a Lakeflow Job in the final workspace, deploy on Databricks Apps, add a Genie space and dashboard, test with five first-time buyers.", False),
        ]),
    ]
    col_gap = Inches(0.35)
    col_w = int((Inches(11.75) - col_gap * 2) / 3)
    for i, (label_text, parts) in enumerate(columns):
        x = LEFT + i * (col_w + col_gap)
        box, tf = textbox(slide, x, Inches(4.35), col_w, Inches(2.3), f"Impact column {i + 1}")
        qa_block(tf, label_text, parts, first=True, answer_size=13)


def main() -> None:
    import argparse

    global TEAM_NAME
    parser = argparse.ArgumentParser(description="Build the FlatFair Round 1 deck from the DAISI template.")
    parser.add_argument("--team", help="team name for slide 1")
    args = parser.parse_args()
    if args.team:
        TEAM_NAME = args.team
    prs = Presentation(str(TEMPLATE))
    slide_problem(prs.slides[0])
    slide_solution(prs.slides[1])
    slide_architecture(prs.slides[2])
    prs.core_properties.title = "FlatFair — DAISI 2026 Round 1"
    prs.core_properties.subject = "Problem C1: HDB resale market intelligence and affordability forecasting"
    prs.save(str(OUT))
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
