# Atlas 🔍
**Data Change Intelligence Agent**

*Built for the Google Cloud Rapid Agent Hackathon 2026 (Fivetran Track)*

---

## ⚡ The Problem

Data pipelines break constantly because upstream schema changes (like dropping a column or changing a data type) are made without understanding the downstream impact. Data engineers waste hours manually tracing lineage across dbt, Looker, and machine learning platforms, often discovering breakages only *after* executive dashboards fail.

## 🚀 The Solution

**Atlas** is an AI agent powered by **Gemini 3** and **Fivetran's Model Context Protocol (MCP)**. It proactively analyzes the impact of proposed schema changes before they happen. 

Instead of just answering questions, Atlas **takes action**:
1. It validates the current schema state directly via Fivetran.
2. It traces the lineage of the specific column across all downstream assets (dbt, Tableau, Looker, ML features).
3. It determines the business criticality of the change.
4. It formulates a deprecation plan and drafts custom communications for affected stakeholders.
5. **Upon user approval, it uses Fivetran to automatically soft-deprecate the column and triggers a verification sync.**

## 🧠 Architecture & Multi-Step Reasoning

Atlas isn't a chatbot; it's an agentic workflow. When given a complex prompt (e.g., *"Drop `forecast_category` from Salesforce and `lead_source_legacy` from HubSpot"*), Gemini 3's advanced reasoning dynamically parallelizes its tasks:

1. **Verify** connection health and schema status via Fivetran MCP (`salesforce`, `hubspot`).
2. **Retrieve** lineage maps for both targets.
3. **Synthesize** a combined impact report across multiple data domains.
4. **Execute** multiple `modify_connection_column_config` tool calls.
5. **Trigger** multiple `sync_connection` commands to push changes to production.

## 🛠️ Built With

* **Gemini 3** - Advanced reasoning, planning, and multi-tool orchestration
* **Fivetran MCP Server** - Direct integration with Fivetran's configuration API
* **Streamlit** - Custom glassmorphic UI with dynamic state management
* **Python** - Core logic and API integration

## 💻 Running Locally

1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Add your Gemini API key to a `.env` file: `GEMINI_API_KEY="your-key"`
4. Run the app: `streamlit run app.py`

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
