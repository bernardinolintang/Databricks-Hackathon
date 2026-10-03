# Devpost submission text: Round 1

**Project name:** FlatFair

**Tagline (≤ 60 chars):** Know the market. Know what you can afford.

**Problem statement:** C1 — FlatFair: HDB resale market intelligence & affordability forecasting

**Attachments:** `FlatFair_Round1_Deck.pdf` (3-slide template)

**Links:**
* Live prototype: https://flatfair-nine.vercel.app
* Repository: https://github.com/bernardinolintang/Databricks-Hackathon *(make public or add judges before sharing)*

## About the project

**Inspiration.** HDB resale prices are up 56% since 2017 while median household income rose 33%. A median 4-room flat now costs 4.4 years of the median household's income, up from 3.8. Singapore publishes every resale transaction, yet a young couple still can't easily tell whether an asking price is fair or whether the repayment fits their budget.

**What it does.** FlatFair is a five-step decision tool built on official open data:
1. **Market**: prices, momentum and volume for any town, flat type, storey band and year.
2. **Forecast**: a six-month outlook with an honest 80% range, chosen by backtest.
3. **Affordability**: repayment, upfront cash and stamp duty against the 30% MSR cap, and which towns are within reach.
4. **Fair value**: what a specific flat should sell for today, where the asking price sits, and the five most comparable recent sales.
5. **Compare**: up to three towns side by side.

**How we built it.** data.gov.sg and SingStat APIs feed bronze/silver/gold Delta tables in Unity Catalog. Nine quality checks flag problem rows instead of deleting them. MLflow tracks a four-method forecast backtest and a gradient-boosted fair value model, which is registered in Unity Catalog. A FastAPI + JavaScript app runs on Databricks Apps, with a public mirror on Vercel.

**Accomplishments.** The fair value model was tested on 13,589 sales it never saw: median error 3.9%, against 9.5% for the $/sqm rule of thumb. When a simple 3-month average beat our ML forecast in backtesting, we published the average and show the scorecard.

**What's next.** Run the pipeline as a Lakeflow Job in the final workspace, add a Genie space over the gold tables, bring in BTO supply context from the HDB Annual Report, and test the journey with first-time buyers.

**Built with:** Databricks (Delta Lake, Unity Catalog, MLflow, Lakeflow Jobs, Databricks SQL, Databricks Apps), Python, pandas, scikit-learn, FastAPI, Apache ECharts, data.gov.sg, SingStat Table Builder.

## Team (fill in on Devpost)
| Name | Institution | Course | Year | Email |
|---|---|---|---|---|
| | | | | |
