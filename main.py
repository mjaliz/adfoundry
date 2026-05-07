from adfoundry.models import CampaignBrief
from adfoundry.workflow import run_campaign


def main():
    package = run_campaign(CampaignBrief(), mode="fixture")
    print(f"Built AdFoundry demo campaign: {package.output_dir}")
    print(f"QA score: {package.qa_report.overall_score}")


if __name__ == "__main__":
    main()
