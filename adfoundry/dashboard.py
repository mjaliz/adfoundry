from __future__ import annotations

from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st

from adfoundry.models import CampaignBrief, RunMode
from adfoundry.settings import get_settings
from adfoundry.workflow import run_campaign


st.set_page_config(page_title="AdFoundry", page_icon="AF", layout="wide")


def main() -> None:
    settings = get_settings()
    st.title("AdFoundry CEO Demo")
    st.caption("Autonomous creative team for brand-aware landing hero campaigns.")

    with st.sidebar:
        st.header("Campaign Brief")
        url = st.text_input("Landing page URL", "https://www.nike.com")
        theme = st.text_input("Theme", "Christmas")
        goal = st.text_input("Goal", "Drive holiday gift purchases")
        audience = st.text_input("Audience", "Holiday shoppers buying athletic gifts")
        tone = st.text_input("Tone", "Premium and energetic")
        offer = st.text_input("Offer", "Holiday gift edit")
        cta = st.text_input("CTA preference", "Shop Gifts")
        mode = st.selectbox(
            "Runtime mode",
            ["hybrid", "fixture", "live"],
            index=["hybrid", "fixture", "live"].index(settings.default_run_mode),
            help="Hybrid tries live services and falls back to fixtures.",
        )
        run = st.button("Build Campaign", type="primary", use_container_width=True)

    if run or "package" not in st.session_state:
        if run:
            brief = CampaignBrief(
                url=url,
                theme=theme,
                goal=goal,
                audience=audience,
                tone=tone,
                offer=offer,
                cta_preference=cta,
            )
            with st.spinner("Agents are building, critiquing, and repairing the campaign..."):
                st.session_state.package = run_campaign(brief, mode=mode)  # type: ignore[arg-type]
        elif "package" not in st.session_state:
            st.info("Use the sidebar to build the default CEO demo campaign.")
            return

    package = st.session_state.package

    metrics = st.columns(4)
    metrics[0].metric("QA score", package.qa_report.overall_score)
    metrics[1].metric("Agent events", len(package.activities))
    metrics[2].metric("Repair rounds", max(0, len(package.repair_history) - 1))
    metrics[3].metric("Mode used", package.mode_used)

    tab_room, tab_decisions, tab_preview, tab_export = st.tabs(
        ["Agent Room", "Decision Board", "Preview & QA", "Export"]
    )

    with tab_room:
        st.subheader("Agent Activity")
        for activity in package.activities:
            with st.container(border=True):
                left, right = st.columns([0.28, 0.72])
                left.markdown(f"**{activity.agent}**")
                if activity.artifact:
                    left.caption(activity.artifact)
                right.write(activity.message)

    with tab_decisions:
        st.subheader("Decision Board")
        for decision in package.decisions:
            with st.container(border=True):
                st.markdown(f"**{decision.decision}**")
                st.write(f"Selected: {decision.selected}")
                if decision.rejected:
                    st.caption("Rejected: " + ", ".join(decision.rejected))
                st.write(decision.reason)
                if decision.score is not None:
                    st.progress(min(decision.score, 45) / 45)

        st.subheader("Strategy Scorecards")
        for option in package.strategy_options:
            with st.expander(f"{option.name}: {option.angle}", expanded=option == package.selected_strategy):
                st.write(option.rationale)
                st.json(option.scorecard.model_dump() | {"total": option.scorecard.total})

    with tab_preview:
        st.subheader(package.campaign_copy.headline)
        st.write(package.campaign_copy.subheadline)
        st.link_button(package.campaign_copy.cta, package.brief.url)

        preview_path = Path(package.preview_html_path)
        if preview_path.exists():
            st.components.v1.html(preview_path.read_text(encoding="utf-8"), height=760, scrolling=True)

        st.subheader("Visual QA")
        st.write(package.qa_report.summary)
        qa_cols = st.columns(6)
        qa_cols[0].metric("Visual", package.qa_report.visual_quality)
        qa_cols[1].metric("Brand", package.qa_report.brand_consistency)
        qa_cols[2].metric("Readability", package.qa_report.readability)
        qa_cols[3].metric("CTA", package.qa_report.cta_visibility)
        qa_cols[4].metric("Mobile", package.qa_report.responsive_layout)
        qa_cols[5].metric("A11y", package.qa_report.accessibility)

        if package.repair_history:
            with st.expander("QA repair history", expanded=True):
                for index, report in enumerate(package.repair_history, start=1):
                    st.write(f"Round {index}: {report.overall_score} - {report.summary}")
                    for issue in report.issues:
                        st.warning(f"{issue.severity.upper()}: {issue.problem} Fix: {issue.recommended_fix}")

        image_cols = st.columns(2)
        if package.desktop_screenshot:
            image_cols[0].image(package.desktop_screenshot, caption="Desktop render", use_container_width=True)
        if package.mobile_screenshot:
            image_cols[1].image(package.mobile_screenshot, caption="Mobile render", use_container_width=True)

    with tab_export:
        st.subheader("Campaign Package")
        st.code(package.output_dir)
        st.download_button(
            "Download campaign JSON",
            data=package.model_dump_json(indent=2),
            file_name=f"{package.run_id}.json",
            mime="application/json",
        )
        st.download_button(
            "Download HTML",
            data=package.campaign_html.html,
            file_name="index.html",
            mime="text/html",
        )


if __name__ == "__main__":
    main()
